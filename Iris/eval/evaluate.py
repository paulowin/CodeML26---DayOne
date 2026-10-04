"""Évaluation d'extractions IA contre la vérité terrain.

    python -m eval.evaluate --pred <dossier de JSON prédits> [--source specimen|reel]

Format prédit (sortie du bloc 3b), un fichier par image :
    {"image": "dossiers_specimen_10_patientes-04.png",
     "fields": {"accouchement.poids_naissance_g": {"value": 3587, "status": "CONNU", "confidence": 0.93}, ...}}

Métriques : exactitude par champ (après normalisation), par type de page et par
source ; cases cochées (précision / rappel) ; couverture ; calibration par
tranche de confiance ; statuts des champs vides (NON_FOURNI attendu) ;
« erreurs silencieuses » (faux avec confiance > 0.9) ; CONFIDENTIALITÉ : échec
bloquant si une valeur d'identifiant apparaît n'importe où dans une prédiction.
Erreur silencieuse = valeur fausse avec le statut CONNU (à défaut de statut : confiance > 0.9).
Rapport markdown dans eval/reports/<date>.md + résumé console (exactitude, erreurs silencieuses,
temps moyen par page et top 15 des champs ratés en premier).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.registry_schema import is_forbidden_key
from app.templates import get_template
from app.templates.normalize import fold, is_empty, normalize_value, values_equal
from eval.common import GT_DIR, REPORTS_DIR, gt_name_for, load_manifest

TEMPLATE = get_template()
CONF_BINS = ((0.0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1.0001))
SILENT_CONF = 0.9
EMPTY_STATUSES = {"NON_FOURNI", "NON_APPLICABLE"}
ILLEGIBLE = "#ILLISIBLE"
CHECKBOX_TYPES = ("bool", "enum", "checkbox_group")
# valeurs de rôle qui ne sont pas des identifiants (« Examen fait par : Sage-femme »)
ROLE_WORDS = {"sage femme", "sage-femme", "medecin", "infirmier", "infirmiere", "dr", "inf"}


# ------------------------------------------------------------------ chargement
def load_ground_truth(gt_dir: Path = GT_DIR) -> dict[str, dict]:
    """nom de fichier GT -> document (+ identifiants locaux des photos réelles)."""
    gts = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(gt_dir.glob("*.json"))
           if not p.name.endswith(".local.json")}
    local = gt_dir / "reel_identifiants.local.json"
    if local.exists():
        extra = json.loads(local.read_text(encoding="utf-8"))
        for name, ids in extra.items():
            if name in gts:
                gts[name].setdefault("_identifiants", {}).update({k: v for k, v in ids.items() if v})
    return gts


def gt_for_images(gts: dict[str, dict]) -> dict[str, str]:
    """nom d'image -> nom de fichier GT (doublons inclus)."""
    return {e["file"]: gt_name_for(e) for e in load_manifest()["images"] if gt_name_for(e) in gts}


def identifiers_by_patient(gts: dict[str, dict]) -> dict[Any, set[str]]:
    """Union des identifiants d'une même patiente (le nom figure sur plusieurs pages)."""
    out: dict[Any, set[str]] = defaultdict(set)
    for name, g in gts.items():
        pid = g.get("patient") if g.get("source") == "specimen" else name
        out[pid].update(v for v in g.get("_identifiants", {}).values() if v)
    return out


# ------------------------------------------------------------------ confidentialité
def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings(v)]
    return [str(obj)] if obj is not None else []


def _ident_patterns(value: str) -> list[tuple[str, str]]:
    """-> [(mode, motif)] : texte replié (sous-chaîne) et/ou chiffres seuls (téléphone, CIN)."""
    v = fold(value)
    if not v or v in ROLE_WORDS:
        return []
    pats = []
    tokens = [t for t in v.split() if t not in ROLE_WORDS]
    core = " ".join(tokens)
    if len(core) >= 4:
        pats.append(("text", core))
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 6:
        pats.append(("digits", digits))
    return pats


def find_leaks(pred: dict, identifiers: set[str]) -> list[str]:
    leaks = []
    for key in pred.get("fields", {}):
        if key in TEMPLATE.identifier_fields or is_forbidden_key(key.split(".")[-1]):
            leaks.append(f"clé identifiante dans la prédiction : {key}")
    texts = _strings({k: v for k, v in pred.items() if k != "image"})
    folded = [fold(t) for t in texts]
    digits = [re.sub(r"\D", "", t) for t in texts]
    for ident in identifiers:
        for mode, pat in _ident_patterns(ident):
            hay = folded if mode == "text" else digits
            if any(pat in h for h in hay):
                leaks.append(f"identifiant « {ident} » retrouvé dans la prédiction")
                break
    return leaks


# ------------------------------------------------------------------ cases cochées
def checked_set(fields: dict[str, Any], keys) -> set[str]:
    out = set()
    for k in keys:
        f = TEMPLATE.fields.get(k)
        if f is None or f.type not in CHECKBOX_TYPES or k not in fields:
            continue
        v = normalize_value(f, fields[k])
        if f.type == "bool" and v is True:
            out.add(k)
        elif f.type == "enum" and v is not None:
            out.update(f"{k}:{c}" for c in (v if isinstance(v, list) else [v]))
        elif f.type == "checkbox_group" and v:
            out.update(f"{k}:{c}" for c in v)
    return out


# ------------------------------------------------------------------ évaluation
def _bin(conf: float) -> str:
    for lo, hi in CONF_BINS:
        if lo <= conf < hi:
            return f"{lo:.2f}-{min(hi, 1):.2f}"
    return "?"


def evaluate(preds: list[dict], gts: dict[str, dict], source: str | None = None) -> dict:
    img2gt = gt_for_images(gts)
    idents = identifiers_by_patient(gts)
    groups: dict[tuple[str, str], Counter] = defaultdict(Counter)   # (axe, valeur) -> compteurs
    calib: dict[str, list] = defaultdict(list)
    silent, leaks, skipped, details = [], [], [], []
    per_field: dict[str, Counter] = defaultdict(Counter)
    durations: list[float] = []

    for pred in preds:
        img = pred.get("image")
        gname = img2gt.get(img)
        if not gname:
            skipped.append(f"{img} : pas de vérité terrain")
            continue
        gt = gts[gname]
        if source and gt.get("source") != source:
            continue
        pid = gt.get("patient") if gt.get("source") == "specimen" else gname
        for leak in find_leaks(pred, idents.get(pid, set())):
            leaks.append(f"{img} : {leak}")

        pf = pred.get("fields", {})
        if isinstance(pred.get("duration_s"), (int, float)):
            durations.append(float(pred["duration_s"]))
        pvals = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in pf.items()}
        axes = [("global", "tout"), ("source", gt.get("source", "?")), ("page", gt.get("page_type") or "?")]

        def bump(name: str, n: int = 1):
            for ax in axes:
                groups[ax][name] += n

        bump("images")
        # null = pas (encore) rempli : ignoré ; "" / "—" = vide (NON_FOURNI attendu)
        # ([] = aucune case cochée : c'est une valeur, pas un vide)
        blank = {k for k, v in gt.get("fields", {}).items() if isinstance(v, str) and is_empty(v)}
        truth = {k: v for k, v in gt.get("fields", {}).items() if v is not None and k not in blank}
        vides = list(gt.get("vides", [])) + sorted(blank - set(gt.get("vides", [])))
        for key, tv in truth.items():
            f = TEMPLATE.fields.get(key)
            if f is None:
                continue
            short = re.sub(r"\.(T[12]V[123]|M[789]|[1-5])\.", ".*.", key)
            if tv == ILLEGIBLE:
                bump("illisibles_verite")
                st = (pf.get(key) or {}).get("status") if isinstance(pf.get(key), dict) else None
                bump("illisibles_signales", int(st in ("ILLISIBLE", "A_REVISER")))
                continue
            bump("champs_verite")
            per_field[short]["n"] += 1
            if key not in pf:
                continue
            bump("couverts")
            entry = pf[key] if isinstance(pf[key], dict) else {"value": pf[key]}
            ok = values_equal(f, tv, entry.get("value"))
            conf = float(entry.get("confidence") or 0.0)
            status = entry.get("status")
            bump("corrects", int(ok))
            per_field[short]["ok"] += int(ok)
            calib[_bin(conf)].append((conf, ok))
            if not ok:
                per_field[short]["err"] += 1
                bump("statut_a_reviser_sur_erreur", int(status in ("A_REVISER", "ILLISIBLE", "INCONNU")))
                details.append({"image": img, "champ": key, "verite": tv, "prediction": entry.get("value"),
                                "statut": status, "confiance": conf})
                if is_silent(status, conf):
                    bump("erreurs_silencieuses")
                    silent.append(details[-1])

        for key in vides:
            bump("vides_verite")
            if key not in pf:
                continue
            entry = pf[key] if isinstance(pf[key], dict) else {"value": pf[key]}
            bump("vides_predits")
            if entry.get("status") in EMPTY_STATUSES:
                bump("vides_statut_ok")
            elif not is_empty(entry.get("value")):
                bump("valeurs_inventees")

        page_keys = gt.get("champs_cases") or [k for k in set(truth) | set(vides)
                                               if TEMPLATE.fields[k].type in CHECKBOX_TYPES]
        t_checked = set(gt.get("checked", []))
        p_checked = checked_set(pvals, page_keys)
        bump("cases_vp", len(t_checked & p_checked))
        bump("cases_fp", len(p_checked - t_checked))
        bump("cases_fn", len(t_checked - p_checked))

    return {"groups": {f"{a}:{v}": dict(c) for (a, v), c in groups.items()}, "calibration": dict(calib),
            "silent": silent, "leaks": leaks, "skipped": skipped, "errors": details,
            "per_field": {k: dict(v) for k, v in per_field.items()},
            "duree_moyenne_s": (sum(durations) / len(durations)) if durations else None}


def is_silent(status: str | None, conf: float) -> bool:
    """Erreur silencieuse : valeur fausse présentée comme sûre (statut CONNU ; à défaut de statut,
    confiance > 0.9). C'est le pire cas : la sage-femme ne sera pas invitée à vérifier."""
    return status == "CONNU" if status else conf > SILENT_CONF


def top_missed(res: dict, n: int = 15) -> list[tuple[str, int, int]]:
    """Champs les plus ratés : (champ, nb d'erreurs, nb de valeurs dans la vérité)."""
    rows = [(k, v.get("err", 0), v.get("n", 0)) for k, v in res["per_field"].items() if v.get("err")]
    return sorted(rows, key=lambda r: (-r[1], r[0]))[:n]


# ------------------------------------------------------------------ métriques dérivées
def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def metrics(c: dict) -> dict:
    vp, fp, fn = c.get("cases_vp", 0), c.get("cases_fp", 0), c.get("cases_fn", 0)
    return {
        "images": c.get("images", 0),
        "exactitude": _ratio(c.get("corrects", 0), c.get("champs_verite", 0)),
        "exactitude_sur_couverts": _ratio(c.get("corrects", 0), c.get("couverts", 0)),
        "couverture": _ratio(c.get("couverts", 0), c.get("champs_verite", 0)),
        "cases_precision": _ratio(vp, vp + fp),
        "cases_rappel": _ratio(vp, vp + fn),
        "vides_non_fourni": _ratio(c.get("vides_statut_ok", 0), c.get("vides_predits", 0)),
        "valeurs_inventees": c.get("valeurs_inventees", 0),
        "erreurs_silencieuses": c.get("erreurs_silencieuses", 0),
        "erreurs_signalees": _ratio(c.get("statut_a_reviser_sur_erreur", 0),
                                    c.get("couverts", 0) - c.get("corrects", 0)),
    }


def calibration_table(calib: dict) -> list[dict]:
    rows = []
    for lo, hi in CONF_BINS:
        name = f"{lo:.2f}-{min(hi, 1):.2f}"
        items = calib.get(name, [])
        rows.append({"tranche": name, "n": len(items),
                     "exactitude": _ratio(sum(ok for _, ok in items), len(items)),
                     "confiance_moy": _ratio(sum(c for c, _ in items), len(items))})
    n = sum(r["n"] for r in rows)
    ece = sum(r["n"] / n * abs(r["exactitude"] - r["confiance_moy"]) for r in rows if r["n"]) if n else None
    return rows + [{"tranche": "ECE", "n": n, "exactitude": ece, "confiance_moy": None}]


# ------------------------------------------------------------------ rendu
def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def render_markdown(res: dict, pred_dir: str = "") -> str:
    g = res["groups"]
    lines = [f"# Rapport d'évaluation – {datetime.now():%Y-%m-%d %H:%M}", ""]
    if pred_dir:
        lines += [f"Prédictions : `{pred_dir}`", ""]
    lines += ["## Confidentialité", ""]
    if res["leaks"]:
        lines += [f"**ÉCHEC BLOQUANT : {len(res['leaks'])} fuite(s) d'identifiant**", ""]
        lines += [f"- {l}" for l in res["leaks"][:50]] + [""]
    else:
        lines += ["OK : aucun identifiant retrouvé dans les prédictions.", ""]

    cols = ["images", "exactitude", "couverture", "exactitude_sur_couverts", "cases_precision", "cases_rappel",
            "vides_non_fourni", "valeurs_inventees", "erreurs_silencieuses", "erreurs_signalees"]
    lines += ["## Métriques", "", "| groupe | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    order = sorted(g, key=lambda k: ({"global": 0, "source": 1, "page": 2}[k.split(":")[0]], k))
    for k in order:
        m = metrics(g[k])
        cells = [str(m[c]) if isinstance(m[c], int) else _pct(m[c]) for c in cols]
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    lines += ["", "## Calibration (exactitude par tranche de confiance)", "",
              "| tranche | n | exactitude | confiance moyenne |", "|---|---|---|---|"]
    for r in calibration_table(res["calibration"]):
        lines.append(f"| {r['tranche']} | {r['n']} | {_pct(r['exactitude'])} | {_pct(r['confiance_moy'])} |")

    lines += ["", "## Top 15 des champs les plus ratés", "", "| champ | erreurs | n | exactitude |",
              "|---|---|---|---|"]
    lines += [f"| `{k}` | {e} | {n} | {_pct((n - e) / n) if n else '—'} |" for k, e, n in top_missed(res)]

    lines += ["", f"## Erreurs silencieuses (faux avec statut CONNU) : {len(res['silent'])}", ""]
    for e in res["silent"][:40]:
        lines.append(f"- `{e['image']}` `{e['champ']}` : vérité `{e['verite']}` / prédit `{e['prediction']}` "
                     f"({e['statut']}, {e['confiance']:.2f})")
    if res["skipped"]:
        lines += ["", "## Ignorés", ""] + [f"- {s}" for s in res["skipped"][:30]]
    return "\n".join(lines) + "\n"


def console_summary(res: dict) -> str:
    m = metrics(res["groups"].get("global:tout", {}))
    d = res.get("duree_moyenne_s")
    out = [f"EXACTITUDE GLOBALE : {_pct(m['exactitude'])}",
           f"ERREURS SILENCIEUSES (faux + CONNU) : {m['erreurs_silencieuses']}",
           f"TEMPS MOYEN PAR PAGE : {'—' if d is None else f'{d:.1f} s'}",
           "TOP 15 DES CHAMPS LES PLUS RATÉS :"]
    out += [f"  {e:3d}/{n:<3d} {k}" for k, e, n in top_missed(res)] or ["  (aucun)"]
    out += ["",
           f"Images évaluées : {m['images']}",
           f"Couverture {_pct(m['couverture'])}, exactitude sur champs couverts {_pct(m['exactitude_sur_couverts'])}",
           f"Cases cochées : précision {_pct(m['cases_precision'])}, rappel {_pct(m['cases_rappel'])}",
           f"Champs vides -> NON_FOURNI : {_pct(m['vides_non_fourni'])} ; valeurs inventées : {m['valeurs_inventees']}",
           "Calibration : " + ", ".join(f"{r['tranche']} {_pct(r['exactitude'])} (n={r['n']})"
                                        for r in calibration_table(res["calibration"])[:-1]),
           f"CONFIDENTIALITÉ : {'ÉCHEC – ' + str(len(res['leaks'])) + ' fuite(s)' if res['leaks'] else 'OK'}"]
    return "\n".join(out)


def load_predictions(pred_dir: Path) -> list[dict]:
    preds = []
    for p in sorted(pred_dir.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("image", p.stem)
        preds.append(d)
    return preds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pred", required=True, type=Path, help="dossier des JSON prédits")
    ap.add_argument("--source", choices=("specimen", "reel"))
    ap.add_argument("--gt", type=Path, default=GT_DIR)
    ap.add_argument("--report", type=Path, help="chemin du rapport (défaut : eval/reports/<date>.md)")
    args = ap.parse_args(argv)

    res = evaluate(load_predictions(args.pred), load_ground_truth(args.gt), args.source)
    report = args.report or REPORTS_DIR / f"{datetime.now():%Y-%m-%d}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(res, str(args.pred)), encoding="utf-8")
    print(console_summary(res))
    print(f"Rapport : {report}")
    return 2 if res["leaks"] else 0


if __name__ == "__main__":
    sys.exit(main())
