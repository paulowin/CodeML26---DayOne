"""Évaluation de bout en bout du cerveau IA sur les images du défi.

    python -m ai.run_eval --source specimen --limit 8 [--main qwen2.5vl:3b] [--verify ''] [--calibrate]

Prédit les images UNIQUES du manifeste (sans doublons), écrit eval/preds/<run_id>/,
lance eval.evaluate (rapport eval/reports/<run_id>.md) et affiche d'abord :
exactitude globale, erreurs silencieuses, temps moyen par page, top 15 des champs ratés.
--calibrate : propose le SEUIL_CONNU qui minimise les erreurs silencieuses (faux
avec statut CONNU) en gardant le plus de CONNU possible.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from ai.extract import extract_pages
from ai.ollama_client import OllamaClient, OllamaUnavailable
from app.config import get_settings
from app.templates import get_template
from app.templates.normalize import values_equal
from eval.common import DATA_DIR, EVAL_DIR, REPORTS_DIR, gt_name_for, load_manifest, write_json
from eval.evaluate import ILLEGIBLE, console_summary, evaluate, load_ground_truth, load_predictions, render_markdown

T = get_template()
PREDS_DIR = EVAL_DIR / "preds"


def select_images(source: str, limit: int | None, page_type: str | None = None,
                  exclude: list[str] | None = None) -> list[dict]:
    imgs = [e for e in load_manifest()["images"] if e["source"] == source and e["unique"]]
    imgs.sort(key=lambda e: (e.get("pdf_page") or 0, e["file"]))
    imgs = imgs[:limit] if limit else imgs
    if page_type:
        imgs = [e for e in imgs if e["page_type"] == page_type]
    return [e for e in imgs if e["page_type"] not in (exclude or [])]


def calibrate(preds: list[dict], gts: dict[str, dict], grid=None) -> dict:
    """Rejoue la règle de statut sur une grille de seuils.
    Éligible à CONNU : lu (statut CONNU/A_REVISER), sans candidats concurrents, confiance ≥ seuil,
    et ≥ 2 lectures concordantes s'il est critique."""
    grid = grid or [round(0.5 + i * 0.01, 2) for i in range(50)]
    img2gt = {e["file"]: gt_name_for(e) for e in load_manifest()["images"]}
    items = []                                   # (confiance, juste, éligible hors seuil)
    for p in preds:
        gt = gts.get(img2gt.get(p.get("image"), ""))
        if not gt:
            continue
        for k, tv in gt.get("fields", {}).items():
            fp = p.get("fields", {}).get(k)
            f = T.fields.get(k)
            if fp is None or f is None or tv is None or tv == ILLEGIBLE:
                continue
            if fp.get("status") not in ("CONNU", "A_REVISER") or fp.get("candidates"):
                continue
            if f.critique and (fp.get("lectures") or 1) < 2:
                continue
            items.append((float(fp.get("confidence") or 0), values_equal(f, tv, fp.get("value"))))
    rows = []
    for t in grid:
        connu = [ok for c, ok in items if c >= t]
        rows.append({"seuil": t, "connu": len(connu), "silencieuses": sum(not ok for ok in connu)})
    if not rows:
        return {"seuil": None, "table": []}
    best_silent = min(r["silencieuses"] for r in rows)
    best = min((r for r in rows if r["silencieuses"] == best_silent), key=lambda r: r["seuil"])
    return {"seuil": best["seuil"], "table": rows, "n": len(items)}


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description="Évaluation du cerveau IA local")
    ap.add_argument("--source", choices=("specimen", "reel"), default="specimen")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--page-type", help="ne traiter qu'un type de page")
    ap.add_argument("--exclude", action="append", default=[], help="type de page à exclure (répétable)")
    ap.add_argument("--mode", choices=("vlm", "ocr"), default=s.ai_mode,
                    help="vlm : Ollama lit tout ; ocr : OCR classique + 2e avis Ollama sur les champs critiques")
    ap.add_argument("--ocr-engine", choices=("paddle", "easyocr"), default=s.ai_ocr_engine)
    ap.add_argument("--files", nargs="*", help="noms de fichiers du manifeste à traiter (sinon --limit)")
    ap.add_argument("--main", default=s.ai_model_main)
    ap.add_argument("--verify", default=s.ai_model_verify, help="'' = pas de 2e avis")
    ap.add_argument("--seuil", type=float, default=s.ai_seuil_connu)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--resume", action="store_true", help="sauter les images déjà prédites (reprise après coupure)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    engine = f"ocr-{args.ocr_engine}" if args.mode == "ocr" else args.main.replace(":", "-")
    run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M}_{engine}_{args.source}"
    out_dir = PREDS_DIR / run_id
    client = OllamaClient(s.ollama_url, timeout=s.ai_timeout_seconds, num_ctx=s.ai_num_ctx, num_predict=s.ai_num_predict,
                          cache_dir=None if args.no_cache else EVAL_DIR / "cache")
    try:
        client.ping()
    except OllamaUnavailable as e:
        if args.mode == "vlm" or args.verify:
            print(f"Ollama indisponible : {e}", file=sys.stderr)
            return 3
        client = None

    images = select_images(args.source, args.limit, args.page_type, args.exclude)
    if args.files:
        wanted = set(args.files)
        images = [e for e in load_manifest()["images"] if e["file"] in wanted]
    print(f"{len(images)} image(s) -> {out_dir}  (mode {args.mode}"
          f"{' ' + args.ocr_engine if args.mode == 'ocr' else ', principal ' + args.main}, "
          f"2e avis {args.verify or 'aucun'})")
    t_all = time.monotonic()
    for i, e in enumerate(images, 1):
        if args.resume and (out_dir / f"{Path(e['file']).stem}.json").exists():
            print(f"[{i}/{len(images)}] {e['file']} : déjà prédit (reprise)")
            continue
        data = (DATA_DIR / e["file"]).read_bytes()
        if args.mode == "ocr":
            from ai.ocr_classique import extract_pages_ocr
            res = extract_pages_ocr([data], engine=args.ocr_engine, client=client, verify_model=args.verify or None,
                                    seuil=args.seuil, use_cache=not args.no_cache)[0]
        else:
            res = extract_pages([data], client=client, main_model=args.main, verify_model=args.verify,
                                seuil=args.seuil, use_cache=not args.no_cache)[0]
        doc = res.to_dict(e["file"])
        write_json(out_dir / f"{Path(e['file']).stem}.json", doc)
        st = {}
        for v in doc["fields"].values():
            st[v["status"]] = st.get(v["status"], 0) + 1
        print(f"[{i}/{len(images)}] {e['file']} : {doc['page_type']} (attendu {e['page_type']}), "
              f"{doc['duration_s']:.0f} s, {st}" + (f", ERREUR {doc['error']}" if doc.get("error") else ""))

    preds, gts = load_predictions(out_dir), load_ground_truth()
    res = evaluate(preds, gts, args.source)
    report = REPORTS_DIR / f"{run_id}.md"
    md = render_markdown(res, str(out_dir))
    cal = calibrate(preds, gts) if args.calibrate else None
    if cal and cal["table"]:
        md += "\n## Calibration du SEUIL_CONNU\n\n| seuil | CONNU | erreurs silencieuses |\n|---|---|---|\n"
        md += "".join(f"| {r['seuil']:.2f} | {r['connu']} | {r['silencieuses']} |\n" for r in cal["table"][::5])
        md += f"\nSeuil proposé : **{cal['seuil']:.2f}**\n"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(md, encoding="utf-8")
    print()
    print(console_summary(res))
    print(f"Durée totale : {time.monotonic() - t_all:.0f} s")
    if cal:
        if cal["seuil"] is None:
            print("Calibration : pas assez de champs lus.")
        else:
            row = next(r for r in cal["table"] if r["seuil"] == cal["seuil"])
            print(f"Calibration : SEUIL_CONNU proposé = {cal['seuil']:.2f} "
                  f"({row['connu']} CONNU, {row['silencieuses']} erreur(s) silencieuse(s) sur {cal['n']} champs lus)")
    print(f"Rapport : {report}")
    return 2 if res["leaks"] else 0


if __name__ == "__main__":
    sys.exit(main())
