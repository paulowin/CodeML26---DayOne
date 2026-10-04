"""Cases à cocher : précision / rappel AVANT (VLM, bloc 3b) et APRÈS (ai/checkboxes.py, OpenCV).

    python -m scripts.eval_cases [--avant eval/preds/3b_qwen25vl3b_specimen8] [--pages 1 2 ... 8]

Une page à la fois (EasyOCR pour lire les libellés-ancres, puis OpenCV). Écrit
eval/preds/cases_cv/<page>.json (cases seulement) + debug_<page>.png (vert = cochée,
rouge = vide, orange = incertaine) et un rapport eval/reports/cases_avant_apres.md.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from ai.checkboxes import read_checkboxes, to_readings
from ai.preprocess import load_image
from app.templates import get_template
from eval.common import DATA_DIR, EVAL_DIR, REPORTS_DIR, gt_name_for, load_manifest, write_json
from eval.evaluate import checked_set, load_ground_truth, load_predictions

T = get_template()


def pred_from_boxes(image: str, results) -> dict:
    fields = {}
    for key, (codes, conf, unsure) in to_readings(results).items():
        f = T.fields[key]
        if f.type == "bool":
            value = "coche" in codes
        elif f.type == "enum":
            value = codes[0] if len(codes) == 1 else (codes or None)
        else:
            value = codes
        fields[key] = {"value": value, "status": "A_REVISER" if unsure or conf < 0.8 else "CONNU",
                       "confidence": 0.4 if unsure else conf}
    return {"image": image, "fields": fields}


def cases_metrics(preds: list[dict], gts: dict, images: set[str]) -> dict:
    img2gt = {e["file"]: gt_name_for(e) for e in load_manifest()["images"]}
    vp = fp = fn = incertaines = total = 0
    for p in preds:
        if p.get("image") not in images:
            continue
        gt = gts[img2gt[p["image"]]]
        keys = gt.get("champs_cases") or []
        vals = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in p.get("fields", {}).items()}
        pred_c, true_c = checked_set(vals, keys), set(gt.get("checked", []))
        vp, fp, fn = vp + len(pred_c & true_c), fp + len(pred_c - true_c), fn + len(true_c - pred_c)
        total += len(keys)
        incertaines += sum(1 for k in keys if (p["fields"].get(k) or {}).get("status") == "A_REVISER")
    prec = vp / (vp + fp) if vp + fp else None
    rec = vp / (vp + fn) if vp + fn else None
    return {"vp": vp, "fp": fp, "fn": fn, "precision": prec, "rappel": rec,
            "champs_cases": total, "a_reviser": incertaines}


def _pct(x):
    return "—" if x is None else f"{100 * x:.1f} %"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--avant", type=Path, default=EVAL_DIR / "preds" / "3b_qwen25vl3b_specimen8")
    ap.add_argument("--pages", type=int, nargs="*", default=list(range(1, 9)))
    a = ap.parse_args()
    out = EVAL_DIR / "preds" / "cases_cv"
    imgs = {e["pdf_page"]: e for e in load_manifest()["images"] if e["source"] == "specimen" and e["unique"]}
    gts = load_ground_truth()
    done, lines = set(), []
    for n in a.pages:                                   # une page à la fois
        e = imgs[n]
        t0 = time.monotonic()
        img = load_image((DATA_DIR / e["file"]).read_bytes())
        res, method = read_checkboxes(img, e["page_type"], debug_path=out / f"debug_{Path(e['file']).stem}.png")
        write_json(out / f"{Path(e['file']).stem}.json", pred_from_boxes(e["file"], res))
        done.add(e["file"])
        lines.append(f"| {n} | {e['page_type']} | {method} | {len(res)} | {time.monotonic() - t0:.0f} s |")
        print(f"page {n:2} {e['page_type']:28} {method:12} {len(res):3} cases  {time.monotonic() - t0:.0f} s")
    after = cases_metrics(load_predictions(out), gts, done)
    before = cases_metrics(load_predictions(a.avant), gts, done) if a.avant.exists() else None
    md = ["# Cases à cocher : VLM (avant) vs vision classique OpenCV (après)", "",
          f"Pages spécimen : {sorted(a.pages)}", "",
          "| | précision | rappel | VP | FP | FN | à réviser / champs cases |", "|---|---|---|---|---|---|---|"]
    for name, m in (("avant (VLM 3b)", before), ("après (OpenCV)", after)):
        if m:
            md.append(f"| {name} | {_pct(m['precision'])} | {_pct(m['rappel'])} | {m['vp']} | {m['fp']} | {m['fn']} "
                      f"| {m['a_reviser']} / {m['champs_cases']} |")
    md += ["", "| page | type | localisation | cases | durée |", "|---|---|---|---|---|"] + lines
    md += ["", f"Images de debug : `{out}` (vert = cochée, rouge = vide, orange = incertaine)."]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "cases_avant_apres.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    for name, m in (("AVANT (VLM)", before), ("APRÈS (OpenCV)", after)):
        if m:
            print(f"{name:15} précision {_pct(m['precision'])}  rappel {_pct(m['rappel'])}  "
                  f"(VP {m['vp']}, FP {m['fp']}, FN {m['fn']}, à réviser {m['a_reviser']}/{m['champs_cases']})")


if __name__ == "__main__":
    main()
