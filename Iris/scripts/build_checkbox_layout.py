"""Disposition des cases à cocher du carnet -> app/templates/carnet_maroc_cases.json.

Depuis le PDF spécimen (patiente 1, une page de chaque type), même géométrie que
scripts/build_ground_truth.py : pour chaque type de page,
- `boxes` : chaque case (champ, option, rectangle en points PDF) ;
- `anchors` : libellés imprimés UNIQUES sur la page (texte + centre), qui servent à recaler
  une photo sur la page modèle (homographie depuis les libellés lus par l'OCR).
Aucune valeur manuscrite n'est conservée. À relancer seulement si le template change.

    python -m scripts.build_checkbox_layout
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pdfplumber

from app.templates.base import norm_label
from app.templates.carnet_maroc import SPECIMEN_PAGE_ORDER
from eval.common import PDF_PATH
from eval.pdf_layout import page_layout
from scripts.build_ground_truth import PageGT

OUT = Path(__file__).resolve().parent.parent / "app" / "templates" / "carnet_maroc_cases.json"


def page_boxes(gt: PageGT) -> list[dict]:
    squares = [s for s in gt.L.strokes
               if 6 < s.x1 - s.x0 < 10 and 6 < s.bottom - s.top < 10 and len(s.pts) >= 4]
    if not squares:
        return []
    form = Counter(str(s.color) for s in squares).most_common(1)[0][0]
    out = []
    for b in (s for s in squares if str(s.color) == form):
        cy = (b.top + b.bottom) / 2
        label = gt._box_label(b, cy)
        hit = gt._box_field(label, cy) if label else None
        if not hit:
            continue
        key, f, code = hit
        out.append({"key": key, "code": code, "label": label.text,
                    "box": [round(b.x0, 2), round(b.top, 2), round(b.x1, 2), round(b.bottom, 2)]})
    return out


def page_anchors(gt: PageGT) -> list[dict]:
    known = set()
    for f in gt.fields.values():
        known.update(norm_label(l) for l in f.labels)
        known.update(norm_label(l) for c in f.choices for l in c.labels)
    for sec in gt.sections:
        from app.templates import get_template
        for tb in get_template().section(sec).tables:
            known.update(norm_label(l) for _, l in tb.cols)
    counts = Counter(norm_label(w.text) for w in gt.prints)
    out = []
    for w in gt.prints:
        n = norm_label(w.text)
        if n in known and counts[n] == 1 and len(n) >= 3:
            out.append({"text": w.text, "x0": round(w.x0, 2), "x1": round(w.x1, 2), "cy": round(w.cy, 2)})
    return out


def main() -> None:
    data = {"page_size": None, "pages": {}}
    with pdfplumber.open(PDF_PATH) as pdf:
        for n, ptype in enumerate(SPECIMEN_PAGE_ORDER, start=1):
            page = pdf.pages[n - 1]
            data["page_size"] = [round(float(page.width), 2), round(float(page.height), 2)]
            gt = PageGT(page_layout(page), ptype)
            boxes, anchors = page_boxes(gt), page_anchors(gt)
            data["pages"][ptype] = {"boxes": boxes, "anchors": anchors}
            print(f"{ptype:28} {len(boxes):3} cases  {len(anchors):3} ancres")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
