"""Inventaire des images du défi -> eval/manifest.json.

Pour chaque image : sha256, unique / doublon_de, source (specimen | reel),
page du PDF, patiente (1..10), type de page attendu (vérifié via le titre
imprimé dans le PDF). Les fichiers de data-defi/ ne sont jamais modifiés.

    python -m scripts.build_manifest
"""
from __future__ import annotations

import hashlib
import re
import sys

import pdfplumber

from app.templates.base import norm_label
from app.templates.carnet_maroc import SPECIMEN_PAGE_ORDER, TEMPLATE
from eval.common import DATA_DIR, MANIFEST_PATH, PDF_PATH, REAL_RE, SPECIMEN_RE, write_json

PAGES_PER_PATIENT = len(SPECIMEN_PAGE_ORDER)

# Contenu des vraies photos (relevé à l'œil : carnet rose, 1 photo = 1 page du carnet).
REAL_PAGES = {
    "1-1": ("couverture", ["couverture"]),
    "1-2": ("identification_antecedents", ["identification", "antecedents_familiaux", "antecedents_femme"]),
    "1-3": ("identification_antecedents", ["antecedents_obstetricaux"]),
    "1-4": ("grossesse_actuelle", ["grossesse_actuelle"]),     # DDR, groupage, visites T1V1..T1V3
    "1-5": ("grossesse_actuelle", ["grossesse_actuelle"]),     # DPA, visites T2V1..M9
}
REAL_VISIT_COLS = {"1-4": ["T1V1", "T1V2", "T1V3"], "1-5": ["T2V1", "T2V2", "T2V3", "M7", "M8", "M9"]}
REAL_HEADER_FIELDS = {"1-4": ["ddr", "taille_cm", "groupage", "rhesus"], "1-5": ["dpa", "date_depassement_terme"]}


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_page_info(pdf) -> dict[int, dict]:
    """n° de page -> {page_type détecté, patiente} d'après le texte imprimé."""
    out = {}
    for i, page in enumerate(pdf.pages, start=1):
        text = norm_label(" ".join(c["text"] for c in page.chars if "Helvetica" in c["fontname"]))
        text = text.replace(" ", "")
        found = [pt.key for pt in TEMPLATE.page_types
                 if all(norm_label(m).replace(" ", "") in text for m in pt.title_markers)]
        m = re.search(r"patientefictiven(?:o|°)?(\d+)/10", text)
        out[i] = {"detected": found, "patient": int(m.group(1)) if m else None}
    return out


def build() -> dict:
    files = sorted(p for p in DATA_DIR.iterdir() if p.is_file())
    with pdfplumber.open(PDF_PATH) as pdf:
        n_pages = len(pdf.pages)
        info = pdf_page_info(pdf)

    images, first_by_sha, problems = [], {}, []
    for p in files:
        m_spec, m_real = SPECIMEN_RE.match(p.name), REAL_RE.match(p.name)
        if not (m_spec or m_real):
            continue
        h = sha256(p)
        entry = {"file": p.name, "sha256": h, "bytes": p.stat().st_size}
        if m_spec:
            n = int(m_spec.group(1))
            expected = SPECIMEN_PAGE_ORDER[(n - 1) % PAGES_PER_PATIENT]
            detected = info[n]["detected"]
            patient = (n - 1) // PAGES_PER_PATIENT + 1
            ok = detected == [expected] and info[n]["patient"] == patient
            if not ok:
                problems.append(f"{p.name}: attendu {expected}/patiente {patient}, PDF dit {detected}/{info[n]['patient']}")
            entry.update(source="specimen", pdf_page=n, patient=patient, page_type=expected,
                         sections=list(TEMPLATE.page_type(expected).sections), page_type_verifie=ok)
        else:
            stem = m_real.group(1)
            page_type, sections = REAL_PAGES.get(stem, (None, []))
            entry.update(source="reel", pdf_page=None, patient=None, page_type=page_type,
                         sections=sections, page_type_verifie=False)
            if stem in REAL_VISIT_COLS:
                entry["visit_cols"] = REAL_VISIT_COLS[stem]
                entry["champs_entete"] = REAL_HEADER_FIELDS[stem]
        dup = first_by_sha.get(h)
        entry["unique"] = dup is None
        entry["doublon_de"] = dup
        first_by_sha.setdefault(h, p.name)
        images.append(entry)

    spec = [e for e in images if e["source"] == "specimen"]
    summary = {
        "images": len(images),
        "specimen_fichiers": len(spec),
        "specimen_pages_uniques": len({e["pdf_page"] for e in spec if e["unique"]}),
        "specimen_doublons": sum(not e["unique"] for e in spec),
        "reelles": sum(e["source"] == "reel" for e in images),
        "pdf_pages": n_pages,
        "pages_pdf_sans_image": sorted(set(range(1, n_pages + 1)) - {e["pdf_page"] for e in spec}),
        "verifications_echouees": problems,
    }
    return {"summary": summary, "images": images}


def main() -> int:
    data = build()
    write_json(MANIFEST_PATH, data)
    s = data["summary"]
    print(f"{s['images']} images : {s['specimen_pages_uniques']} pages spécimen uniques "
          f"(+{s['specimen_doublons']} doublons exacts), {s['reelles']} photos réelles -> {MANIFEST_PATH}")
    if s["pages_pdf_sans_image"]:
        print("Pages du PDF sans image :", s["pages_pdf_sans_image"])
    for pb in s["verifications_echouees"]:
        print("ÉCHEC :", pb)
    return 1 if s["verifications_echouees"] else 0


if __name__ == "__main__":
    sys.exit(main())
