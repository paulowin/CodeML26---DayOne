"""Carnet de vaccination OMS (page « AUTRES VACCINATIONS ») — image SYNTHÉTIQUE uniquement :
les vraies photos (data-perso/, ignoré par git) ne sont jamais versionnées."""
import io
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ai.vaccination import blue_mask, norm_dose, snap_vaccine
from app.templates import get_template

BLUE, GREY, STAMP = (30, 40, 170), (120, 120, 120), (200, 40, 90)


def _font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def page_vaccination() -> bytes:
    W, H = 1600, 1100
    img = Image.new("RGB", (W, H), (235, 233, 228))
    d = ImageDraw.Draw(img)
    for y in range(0, H, 60):                               # trame grise « INSTITUT D'HYGIÈNE »
        d.text((0, y), "INSTITUT D'HYGIENE PUBLIQUE " * 8, fill=(200, 198, 192), font=_font(10))
    d.text((380, 40), "OTHER VACCINATIONS - AUTRES VACCINATIONS", fill=(20, 20, 20), font=_font(36))
    xs = (60, 360, 820, 1100, 1540)
    for x in xs:
        d.line((x, 110, x, 1050), fill=(20, 20, 20), width=3)
    for y in range(110, 1060, 90):
        d.line((60, y, 1540, y), fill=(20, 20, 20), width=3)
    for x, t in zip(xs, ("Date", "Genre de vaccin", "Dose", "Signature du medecin")):
        d.text((x + 20, 140), t, fill=(20, 20, 20), font=_font(30))
    d.ellipse((1150, 180, 1450, 480), outline=STAMP, width=8)   # tampon : ignoré (pas bleu)
    for y, row in ((230, ("29/08/2023", "Typhoide", "0,5 cc", "76BE2027A")),
                   (590, ("12/03/2024", "Fievre jaune", "1 cc", "AB1234"))):
        for x, t in zip(xs, row):
            d.text((x + 20, y), t, fill=BLUE, font=_font(44))
    d.text((80, 320), "29/08/2026", fill=GREY, font=_font(44))  # date au crayon : rappel ?
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def test_modele_et_liste_blanche():
    T = get_template()
    assert "vaccinations.E1.lot" in T.stored_fields and T.fields["vaccinations.E1.lot"].critique
    for k in ("nom", "numero_certificat", "passeport"):              # couverture : jamais stockée
        assert f"vaccination_couverture.{k}" not in T.stored_fields
    assert any(pt.key == "vaccinations" for pt in T.page_types)


def test_vocabulaire_dose_et_encre():
    assert snap_vaccine("Typhoide") == ("Typhoïde", True)
    assert snap_vaccine("DuKlavax")[0] == "Dultavax"
    assert norm_dose("0.5cc") == "0,5 cc" and norm_dose("1 cc") == "1 cc"
    px = np.array([[[35, 32, 47], [200, 40, 90], [140, 137, 130], [30, 40, 170]]], dtype=np.uint8)
    assert blue_mask(px).tolist() == [[True, False, False, True]]      # encre bleue sombre oui, tampon non


@pytest.mark.skipif(not os.environ.get("IRIS_SLOW"), reason="OCR réel ~1 min : IRIS_SLOW=1 pour le lancer")
def test_page_vaccination_synthetique_lue_et_a_verifier():
    from ai.ocr_classique import extract_pages_ocr
    res = extract_pages_ocr([page_vaccination()], engine="easyocr")[0]
    assert res.page_type == "vaccinations"
    f = res.fields
    assert f["vaccinations.E1.date"]["value"] == "2023-08-29"
    assert f["vaccinations.E1.vaccin"]["value"] == "Typhoïde"
    assert f["vaccinations.E1.dose"]["value"] == "0,5 cc"
    assert "vaccinations.E1.lot" in f
    # sans 2e avis : rien n'est CONNU (toutes les cellules sont critiques)
    assert all(v["status"] != "CONNU" for v in f.values())
    rappel = f.get("vaccinations.E1.rappel")
    assert rappel and rappel["status"] == "A_REVISER" and "crayon_gris" in rappel["flags"]
