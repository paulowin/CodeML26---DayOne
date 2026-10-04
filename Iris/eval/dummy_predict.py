"""Prédicteur bidon : recopie la vérité terrain avec du bruit, pour tester
l'évaluateur de bout en bout (il ne lit PAS les images).

    python -m eval.dummy_predict --out eval/preds/dummy [--noise 0.15] [--seed 0]
    python -m eval.evaluate --pred eval/preds/dummy

Avec --noise 0, la prédiction est la vérité elle-même (score attendu : 100 %).
Les erreurs injectées sont surtout signalées (A_REVISER, confiance basse) mais
une partie est volontairement « silencieuse » (CONNU, confiance > 0.9).
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from app.templates import get_template
from app.templates.normalize import normalize_value
from eval.common import EVAL_DIR, gt_name_for, load_manifest, write_json
from eval.evaluate import ILLEGIBLE, load_ground_truth

TEMPLATE = get_template()


def _corrupt(f, v, rng: random.Random):
    if f.type == "bool":
        return not v
    if f.type == "enum":
        others = [c for c in f.choice_codes if c != v]
        return rng.choice(others) if others else None
    if f.type == "checkbox_group":
        codes = set(v or [])
        codes ^= {rng.choice(f.choice_codes)}
        return sorted(codes)
    if f.type == "bp":
        return {"sys": v["sys"] + rng.choice((-20, 10, 20)), "dia": v["dia"] + rng.choice((-10, 10))}
    if f.type in ("int", "float"):
        out = v * rng.choice((0.7, 0.8, 1.2, 1.5)) + rng.choice((1, 2, 3))
        return int(round(out)) if f.type == "int" else round(out, 1)
    if f.type == "date" and isinstance(v, str) and len(v) == 10:
        d = (int(v[:2]) % 28) + 1
        return f"{d:02d}{v[2:]}" if f"{d:02d}" != v[:2] else f"{(d % 28) + 1:02d}{v[2:]}"
    s = str(v)
    return (s[:-1] + "x") if len(s) > 1 else "x"


def predict_from_gt(gt: dict, image: str, noise: float = 0.0, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random(0)
    fields = {}
    for key, v in gt.get("fields", {}).items():
        f = TEMPLATE.fields.get(key)
        if f is None or v is None or v == ILLEGIBLE:
            continue
        v = normalize_value(f, v)
        if noise and rng.random() < noise:
            if rng.random() < 0.3:      # erreur silencieuse : le pire cas
                fields[key] = {"value": _corrupt(f, v, rng), "status": "CONNU",
                               "confidence": round(rng.uniform(0.91, 0.99), 2)}
            else:
                fields[key] = {"value": _corrupt(f, v, rng), "status": "A_REVISER",
                               "confidence": round(rng.uniform(0.2, 0.7), 2)}
        else:
            conf = 1.0 if not noise else round(rng.uniform(0.8, 1.0), 2)
            fields[key] = {"value": v, "status": "CONNU", "confidence": conf}
    for key in gt.get("vides", []):
        fields[key] = {"value": None, "status": "NON_FOURNI", "confidence": 0.9}
    return {"image": image, "fields": fields}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prédicteur bidon (vérité + bruit)")
    ap.add_argument("--out", type=Path, default=EVAL_DIR / "preds" / "dummy")
    ap.add_argument("--noise", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="inclure les doublons exacts")
    args = ap.parse_args(argv)

    gts = load_ground_truth()
    rng = random.Random(args.seed)
    n = 0
    for e in load_manifest()["images"]:
        gname = gt_name_for(e)
        if gname not in gts or (not e["unique"] and not args.all):
            continue
        if not any(v is not None for v in gts[gname].get("fields", {}).values()):
            continue                    # modèle de photo réelle pas encore rempli
        write_json(args.out / f"{Path(e['file']).stem}.json", predict_from_gt(gts[gname], e["file"], args.noise, rng))
        n += 1
    print(f"{n} prédictions écrites dans {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
