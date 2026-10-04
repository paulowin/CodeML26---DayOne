"""Étape 3d : OCR classique (faux moteur OCR, aucune dépendance lourde ni GPU)."""
import io

import pytest
from PIL import Image, ImageDraw

from ai import ocr_classique as O
from ai.ocr_classique import Token, header_match, split_label

W, H = 1654, 2339                     # même format que les PNG du spécimen
S = W / O.PT_WIDTH                    # points PDF -> pixels


def px(x0, y0, x1, y1):
    return (x0 * S, y0 * S, x1 * S, y1 * S)


def test_libelle_imprime_reconnu_et_coupe():
    labels = O.page_labels("grossesse_actuelle")
    assert split_label("DDR：26/04/2025", labels) == ("DDR :", "26/04/2025")      # deux-points pleine largeur
    assert split_label("Taille： 155 cm", labels) == ("Taille :", "155 cm")
    assert split_label("Venue le", labels)[0] == "Venue le"
    assert split_label("12 SA", labels) == (None, "12 SA")                           # valeur manuscrite
    assert split_label("Hemoglobine", labels)[0] == "Hémoglobine"                    # erreur d'OCR tolérée


def test_entete_de_colonne_exige_le_bon_chiffre():
    assert header_match("visite 1", "visite 1") and header_match("vlsite 2", "visite 2")
    assert not header_match("visites", "visite 1")       # « Prestations / Visites » ne décale plus le tableau
    assert not header_match("visite", "visite 1")        # chiffre perdu -> colonne interpolée
    assert header_match("8eme mois", "8eme mois") and not header_match("geme mois", "9eme mois")


def _page(draw_marks: list[tuple[float, float]], boxes: list[tuple[float, float]] = ()) -> bytes:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for y in range(80, 2300, 120):                       # lignes du formulaire (qualité OK)
        d.line((60, y, W - 60, y), fill=(40, 30, 30), width=2)
    for x, y in list(boxes) + list(draw_marks):          # cadre imprimé de la case (8 pt)
        d.rectangle((x * S, y * S, (x + 8) * S, (y + 8) * S), outline=(30, 20, 25), width=2)
    for x, y in draw_marks:                              # croix bleue dans une case (points PDF)
        d.line((x * S, y * S, (x + 8) * S, (y + 8) * S), fill=(20, 33, 140), width=4)
        d.line((x * S, (y + 8) * S, (x + 8) * S, y * S), fill=(20, 33, 140), width=4)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_lecture_ocr_page_accouchement_avec_cases(monkeypatch):
    tokens = [
        Token("DÉROULEMENT DE L'ACCOUCHEMENT", px(40, 34, 300, 46), 0.99),
        Token("Date de l'accouchement : 03/02/2026", px(40, 296, 230, 309), 0.95),
        Token("Etat du nouveau-né :", px(40, 676, 150, 689), 0.99),
        Token("Vivant", px(227, 676, 260, 689), 0.99),
        Token("Mort-né", px(297, 676, 330, 689), 0.99),
        Token("Sexe :", px(215, 701, 240, 714), 0.99),
        Token("F", px(246, 701, 252, 714), 0.93),
        Token("Poids à la naissance :", px(215, 721, 298, 734), 0.99),
        Token("3587 g", px(301, 721, 330, 734), 0.97),
    ]
    monkeypatch.setitem(O.ENGINES, "fake", lambda img: tokens)
    data = _page([(215, 678)])                           # case « Vivant » cochée (à gauche du libellé)
    res = O.extract_pages_ocr([data], engine="fake", seuil=0.8)[0]
    f = res.fields
    assert res.page_type == "accouchement" and res.models["main"] == "ocr:fake"
    assert f["accouchement.date"]["value"] == "2026-02-03"
    assert f["accouchement.sexe"]["value"] == "F" and f["accouchement.sexe"]["status"] == "CONNU"
    assert f["accouchement.poids_naissance_g"]["value"] == 3587
    assert f["accouchement.poids_naissance_g"]["status"] == "A_REVISER"   # critique : jamais CONNU seul
    assert f["accouchement.etat_nne"]["value"] == "vivant"                # case : taux d'encre, pas d'IA
    assert "lecture_cv" in f["accouchement.etat_nne"]["flags"]


def test_case_non_cochee_lue_comme_vide(monkeypatch):
    tokens = [Token("DÉROULEMENT DE L'ACCOUCHEMENT", px(40, 34, 300, 46), 0.99),
              Token("Avec épisiotomie", px(262, 412, 330, 424), 0.99)]
    monkeypatch.setitem(O.ENGINES, "fake", lambda img: tokens)
    res = O.extract_pages_ocr([_page([], boxes=[(250, 409)])], engine="fake", seuil=0.8)[0]
    assert res.fields["accouchement.episiotomie"]["value"] is False


def test_moteur_absent_ne_plante_pas(monkeypatch):
    def boom(img):
        raise RuntimeError("PaddleOCR absent")
    monkeypatch.setitem(O.ENGINES, "fake", boom)
    res = O.extract_pages_ocr([_page([])], engine="fake")[0]
    assert res.error and "PaddleOCR absent" in res.error and res.fields == {}


@pytest.mark.parametrize("mode", ["ocr", "vlm"])
def test_mode_configurable_pour_le_worker(monkeypatch, mode):
    from app.config import get_settings
    from app.services import ai_worker
    monkeypatch.setattr(get_settings(), "ai_mode", mode)
    monkeypatch.setattr(get_settings(), "ai_model_verify", "")
    fn = ai_worker._default_extractor()
    assert callable(fn) and (fn.__name__ == "run") == (mode == "ocr")


# ------------------------------------------------------------------ ai/checkboxes.py
def _form_from_layout(page_type: str, ticked: set[tuple[str, str]], scale: float = 1.0, dx=0, dy=0):
    """Page synthétique : cases du gabarit (cadre noir) + croix bleues + ancres en tokens OCR."""
    from ai.checkboxes import layout
    lay = layout()["pages"][page_type]
    k = S * scale
    img = Image.new("RGB", (W, H), (245, 205, 215))                     # papier rose
    d = ImageDraw.Draw(img)
    for b in lay["boxes"]:
        x0, y0, x1, y1 = (v * k for v in b["box"])
        x0, x1, y0, y1 = x0 + dx, x1 + dx, y0 + dy, y1 + dy
        d.rectangle((x0, y0, x1, y1), outline=(30, 20, 25), width=2)
        if (b["key"], b["code"]) in ticked:
            d.line((x0, y0, x1, y1), fill=(25, 40, 150), width=4)
            d.line((x0, y1, x1, y0), fill=(25, 40, 150), width=4)
    tokens = [Token(a["text"], (a["x0"] * k + dx, (a["cy"] - 5) * k + dy, a["x1"] * k + dx, (a["cy"] + 5) * k + dy), 0.99)
              for a in lay["anchors"]]
    return img, tokens


def test_cases_par_homographie_sur_les_ancres(tmp_path):
    from ai.checkboxes import read_checkboxes
    ticked = {("accouchement.etat_nne", "vivant"), ("accouchement.mode", "voie_basse_non_instrumentale"),
              ("accouchement.episiotomie", None)}
    img, tokens = _form_from_layout("accouchement", ticked, scale=0.9, dx=60, dy=-30)   # photo décalée/réduite
    res, method = read_checkboxes(img, "accouchement", tokens=tokens, debug_path=tmp_path / "debug.png")
    assert method == "homographie" and len(res) == 24
    cochees = {(r.key, r.code) for r in res if r.decision == "cochee"}
    assert cochees == ticked
    assert all(r.decision == "vide" for r in res if (r.key, r.code) not in ticked)   # le cadre noir ne compte pas
    assert (tmp_path / "debug.png").exists()


def test_cases_decision_et_seuils(monkeypatch):
    from ai.checkboxes import decide
    from app.config import get_settings
    assert decide(0.30)[0] == "cochee" and decide(0.30)[1] > 0.8
    assert decide(0.01)[0] == "vide" and decide(0.01)[1] > 0.8
    assert decide(0.08) == ("incertaine", 0.4)
    monkeypatch.setattr(get_settings(), "ai_case_cochee", 0.07)
    assert decide(0.08)[0] == "cochee"                                   # seuils dans la config


def test_case_incertaine_donne_a_reviser():
    from ai.checkboxes import BoxResult
    from ai.extract import FieldState, add_checkbox_readings, merge
    from ai.preprocess import Band
    states: dict = {}
    bands = [Band(0, 0.0, 1.0, b"")]
    add_checkbox_readings(states, [BoxResult("accouchement.episiotomie", None, (0, 0, 10, 10), 0.08, "incertaine", 0.4),
                                   BoxResult("accouchement.mode", "voie_basse_instrumentale", (0, 20, 10, 30), 0.3,
                                             "cochee", 0.95)], bands, 100)
    for st in states.values():
        merge(st)
    assert "case_incertaine" in states["accouchement.episiotomie"].flags
    assert states["accouchement.episiotomie"].evidence.declared == 0.4
    assert states["accouchement.mode"].interp.value == "voie_basse_instrumentale"



def test_faute_de_frappe_ocr_corrigee_mais_a_verifier():
    from ai.ocr_classique import snap_vocabulary
    assert snap_vocabulary("Nbrmaux") == "Normaux" and snap_vocabulary("Ou;") == "Oui"
    for typo in ("Qui", "ouj", "Oul", "Ouj"):
        assert snap_vocabulary(typo) == "Oui", typo
    assert snap_vocabulary("Nprlaux") == "Normaux"
    assert snap_vocabulary("Asthme léger") == "Asthme léger" and snap_vocabulary("11.8 g/dL") == "11.8 g/dL"
