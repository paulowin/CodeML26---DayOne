"""Chemins et utilitaires partagés par les scripts d'évaluation."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data-defi" / "Paper Registry"      # fichiers d'origine : lecture seule
PDF_PATH = DATA_DIR / "dossiers_specimen_10_patientes.pdf"
EVAL_DIR = ROOT / "eval"
MANIFEST_PATH = EVAL_DIR / "manifest.json"
GT_DIR = EVAL_DIR / "ground_truth"
REPORTS_DIR = EVAL_DIR / "reports"

SPECIMEN_RE = re.compile(r"^dossiers_specimen_10_patientes-(\d+)(?:__.+)?\.png$")
REAL_RE = re.compile(r"^(\d+-\d+)\.jpe?g$", re.I)


def gt_name_for(entry: dict) -> str:
    if entry["source"] == "specimen":
        return f"specimen_p{entry['pdf_page']:02d}.json"
    return f"reel_{Path(entry['file']).stem}.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
