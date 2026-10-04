"""Détection de l'écriture arabe (pas de lecture) : champ A_REVISER « écrit en arabe », jamais CONNU."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ai import arabic
from ai.extract import FieldState, PageResult, Reading, _finalize, apply_verify, merge, privacy_filter
from app.templates import get_template

T = get_template()
F = T.fields
K = "identification.profession"
# « الرباط » en formes de présentation déjà liées, ordre visuel (PIL sans moteur de rendu arabe)
MOT_ARABE = "ﻁﺎﺑﺮﻟﺍ"
MODELE_AR = (Path.home() / ".EasyOCR" / "model" / "arabic.pth").exists()


def case_avec(texte: str) -> np.ndarray:
    """Une case de formulaire (cadre imprimé) avec un mot manuscrit à l'encre bleue."""
    im = Image.new("RGB", (460, 110), (250, 250, 245))
    d = ImageDraw.Draw(im)
    d.rectangle((5, 5, 455, 105), outline=(20, 20, 20), width=3)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        pytest.skip("police arabe absente")
    d.text((30, 20), texte, fill=(20, 30, 140), font=font)
    return np.asarray(im)


def test_caracteres_arabes():
    assert arabic.has_arabic("الرباط") and not arabic.has_arabic("Rabat") and not arabic.has_arabic(None)


@pytest.mark.skipif(not MODELE_AR, reason="modèle EasyOCR arabe non installé (téléchargé au 1er usage)")
def test_case_synthetique_avec_mot_arabe_detectee():
    assert arabic.zone_is_arabic(case_avec(MOT_ARABE), (0, 0, 460, 110))
    assert not arabic.zone_is_arabic(case_avec("Casablanca"), (0, 0, 460, 110))


def _final(st):
    res = PageResult(0, "identification_antecedents")
    _finalize([(res, {K: st})], 0.5)
    return res.fields[K]


def test_lecture_arabe_jamais_connue():
    st = FieldState(F[K], [Reading(K, "Fqtl3", "LISIBLE", 0.95, 0)], flags=["lecture_ocr", "ecrit_arabe"])
    merge(st)
    out = _final(st)
    assert out["status"] == "A_REVISER" and out["value"] is None and "ecrit_arabe" in out["flags"]
    st = FieldState(F[K], [Reading(K, "معلمة", "LISIBLE", 0.99, 0)])              # lecture en arabe
    merge(st)
    assert _final(st)["status"] == "A_REVISER"


def test_second_avis_en_arabe():
    st = FieldState(F[K], [Reading(K, "Chauffeur", "LISIBLE", 0.95, 0),
                           Reading(K, "سائق", "LISIBLE", 0.9, 0, source="verify")], flags=["lecture_ocr"])
    merge(st)
    apply_verify(st)
    out = _final(st)
    assert out["status"] == "A_REVISER" and "ecrit_arabe" in out["flags"]


def test_identifiant_en_arabe_jamais_stocke():
    fields = {"identification.nom_mari": {"value": "فاطمة الزهراء", "status": "A_REVISER", "confidence": 0.3},
              K: {"value": None, "status": "A_REVISER", "confidence": 0.3, "flags": ["ecrit_arabe"]}}
    assert "identification.nom_mari" in T.identifier_fields                  # vrai identifiant du modèle
    kept, n, removed = privacy_filter(fields)
    assert "identification.nom_mari" not in kept and "identification.nom_mari" in removed and K in kept


def test_question_dediee():
    from app.i18n import t
    from app.services.conversation import _FLAG_REASONS
    assert ("ecrit_arabe", "why_arabic") in _FLAG_REASONS and t("fr", "why_arabic") == "écrit en arabe"
    assert t("fr", "arabic_q") == "🟠 Ce champ semble écrit en arabe, pouvez-vous me le donner ?"
