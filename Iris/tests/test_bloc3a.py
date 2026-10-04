"""Bloc 3a : schéma réel du carnet, vérité terrain, manifeste, évaluateur."""
import copy

import pytest

from app.registry_schema import FIELD_INDEX, IDENTIFIER_KEYS, sanitize_extraction
from app.templates import get_template
from app.templates.normalize import normalize_value, values_equal
from eval.common import PDF_PATH, gt_name_for, load_manifest
from eval.dummy_predict import predict_from_gt
from eval.evaluate import calibration_table, evaluate, load_ground_truth, metrics

T = get_template()
NEEDS_PDF = pytest.mark.skipif(not PDF_PATH.exists(), reason="data-defi/ absent (non versionné)")


@pytest.fixture(scope="module")
def gts():
    return load_ground_truth()


@pytest.fixture(scope="module")
def truth_preds(gts):
    """Prédictions = vérité elle-même, une par page unique."""
    return [predict_from_gt(gts[gt_name_for(e)], e["file"]) for e in load_manifest()["images"]
            if e["unique"] and e["source"] == "specimen"]


# ------------------------------------------------------------------ template / liste blanche
def test_template_cles_indexees():
    assert T.fields["grossesse_actuelle.visites.T2V1.poids_kg"].unit == "kg"
    assert "grossesse_actuelle.visites.M9.ta" in FIELD_INDEX
    assert "antecedents_obstetricaux.accouchements.5.poids_nne_g" in FIELD_INDEX
    assert FIELD_INDEX["accouchement.poids_naissance_g"].csv_column == "child birth weight (g)"
    # les identifiants sont décrits dans le template mais jamais dans l'index stocké
    assert "identification.cin" in IDENTIFIER_KEYS and "identification.cin" not in FIELD_INDEX


def test_sanitize_rejette_les_identifiants():
    kept, rejected = sanitize_extraction({
        "couverture.nom_parturiente": "X", "identification.cin": "AB123", "identification.telephone": "06",
        "identification.nom_mari": "Y", "identification.adresse": "Rue", "pp_precoce_nne.vu_par": "Inf. Z",
        "grossesse_actuelle.visites.T1V1.examen_fait_par": "Dr X", "accouchement.nom_patiente": "Z",
        "grossesse_actuelle.visites.T2V1.poids_kg": 62.7, "accouchement.poids_naissance_g": 3587,
    })
    assert set(kept) == {"grossesse_actuelle.visites.T2V1.poids_kg", "accouchement.poids_naissance_g"}
    assert len(rejected) == 8


def test_normalisation():
    ta = T.fields["grossesse_actuelle.visites.T1V1.ta"]
    assert normalize_value(ta, "11/7") == {"sys": 110, "dia": 70}            # cmHg -> mmHg
    assert normalize_value(ta, "104/74") == {"sys": 104, "dia": 74}
    assert normalize_value(T.fields["grossesse_actuelle.visites.T1V1.age_probable_sa"], "16SA+3j") == 16.4
    assert normalize_value(T.fields["accouchement.date"], "3/2/26") == "03/02/2026"
    assert normalize_value(T.fields["accouchement.poids_naissance_g"], "3587 g") == 3587
    assert normalize_value(T.fields["grossesse_actuelle.visites.T1V1.bcf"], "—") is None
    niveau = T.fields["identification.niveau_instruction"]
    assert values_equal(niveau, "Coll\x00ge", "Collège")                    # glyphe absent = joker
    assert not values_equal(niveau, "Coll\x00ge", "Lycée")


# ------------------------------------------------------------------ manifeste
def test_manifeste_80_pages_uniques_et_5_reelles():
    m = load_manifest()
    spec = [e for e in m["images"] if e["source"] == "specimen"]
    assert len({e["pdf_page"] for e in spec if e["unique"]}) == 80
    assert sum(e["unique"] for e in spec) == 80 and sum(not e["unique"] for e in spec) == 44
    assert sum(e["source"] == "reel" for e in m["images"]) == 5
    assert all(e["page_type_verifie"] for e in spec)
    dup = next(e for e in spec if not e["unique"])
    first = next(e for e in spec if e["file"] == dup["doublon_de"])
    assert (first["sha256"], first["pdf_page"]) == (dup["sha256"], dup["pdf_page"])


# ------------------------------------------------------------------ vérité terrain
def _check_accouchement_p1(doc):
    assert doc["page_type"] == "accouchement" and doc["patient"] == 1
    f = doc["fields"]
    assert f["accouchement.date"] == "03/02/2026"
    assert f["accouchement.sexe"] == "F"
    assert f["accouchement.poids_naissance_g"] == 3587
    assert f["accouchement.perimetre_cranien_cm"] == 34
    assert f["accouchement.age_gestationnel_sa"] == 40
    assert "accouchement.mode:voie_basse_non_instrumentale" in doc["checked"]
    # le nom UNIQUEMENT dans _identifiants
    assert doc["_identifiants"] == {"accouchement.nom_patiente": "Tazi Meryem"}
    public = {k: v for k, v in doc.items() if k != "_identifiants"}
    assert "Tazi" not in str(public) and "Meryem" not in str(public)


def test_verite_terrain_versionnee_patiente1_accouchement(gts):
    _check_accouchement_p1(gts["specimen_p04.json"])


@NEEDS_PDF
def test_verite_terrain_reconstruite_depuis_le_pdf():
    import pdfplumber
    from scripts.build_ground_truth import build_page
    with pdfplumber.open(PDF_PATH) as pdf:
        doc, stats = build_page(pdf.pages[3], 4)
    _check_accouchement_p1(doc)
    assert stats["orphans"] == 0


def test_verite_terrain_identifiants_jamais_dans_fields(gts):
    for name, g in gts.items():
        if g["source"] != "specimen":
            continue
        assert not set(g["fields"]) & IDENTIFIER_KEYS, name
        public = str({k: v for k, v in g.items() if k not in ("_identifiants", "non_rattache")})
        for v in g["_identifiants"].values():
            if v not in ("Sage-femme",):            # rôle, pas un identifiant
                assert v not in public, (name, v)
    assert gts["specimen_p02.json"]["_identifiants"]["identification.cin"] == "CB609814"


def test_verite_terrain_couverture_rattachement(gts):
    spec = [g for g in gts.values() if g["source"] == "specimen"]
    assert len(spec) == 80
    assert sum(len(g["non_rattache"]) for g in spec) == 0
    assert all(not g["cases_non_rattachees"] for g in spec)


# ------------------------------------------------------------------ évaluateur
def test_evaluation_100_pourcent_sur_la_verite(gts, truth_preds):
    res = evaluate(truth_preds, gts)
    m = metrics(res["groups"]["global:tout"])
    assert m["images"] == 80
    assert m["exactitude"] == 1.0 and m["couverture"] == 1.0
    assert m["cases_precision"] == 1.0 and m["cases_rappel"] == 1.0
    assert m["vides_non_fourni"] == 1.0 and m["valeurs_inventees"] == 0
    assert m["erreurs_silencieuses"] == 0 and res["leaks"] == []


def test_evaluation_detecte_une_fuite_d_identifiant(gts, truth_preds):
    pred = copy.deepcopy(next(p for p in truth_preds if p["image"].startswith("dossiers_specimen_10_patientes-04")))
    pred["fields"]["accouchement.anomalie"] = {"value": "Patiente Tazi Meryem", "status": "CONNU", "confidence": 0.9}
    assert any("Tazi Meryem" in l for l in evaluate([pred], gts)["leaks"])

    # même patiente, autre page : son téléphone (page 2) recopié en chiffres collés
    pred = copy.deepcopy(pred)
    del pred["fields"]["accouchement.anomalie"]
    pred["notes"] = "rappeler au 0600761348"
    assert evaluate([pred], gts)["leaks"]

    # une clé identifiante est une fuite même sans valeur reconnue
    pred = copy.deepcopy(next(p for p in truth_preds if p["image"].startswith("dossiers_specimen_10_patientes-02")))
    pred["fields"]["identification.cin"] = {"value": "XX", "status": "CONNU", "confidence": 0.5}
    assert any("clé identifiante" in l for l in evaluate([pred], gts)["leaks"])


def test_evaluation_calibration_et_erreurs_silencieuses(gts):
    gt = gts["specimen_p04.json"]
    image = "dossiers_specimen_10_patientes-04.png"
    pred = predict_from_gt(gt, image)
    f = pred["fields"]
    f["accouchement.poids_naissance_g"] = {"value": 2500, "status": "CONNU", "confidence": 0.97}      # silencieuse
    f["accouchement.perimetre_cranien_cm"] = {"value": 30, "status": "A_REVISER", "confidence": 0.3}  # signalée
    f["accouchement.date"] = {"value": "3/2/26", "status": "CONNU", "confidence": 0.6}               # juste
    res = evaluate([pred], gts)
    m = metrics(res["groups"]["global:tout"])
    assert m["erreurs_silencieuses"] == 1 and m["erreurs_signalees"] == 0.5
    calib = {r["tranche"]: r for r in calibration_table(res["calibration"])}
    assert calib["0.00-0.50"]["n"] == 1 and calib["0.00-0.50"]["exactitude"] == 0.0
    assert calib["0.50-0.80"]["n"] == 1 and calib["0.50-0.80"]["exactitude"] == 1.0
    assert calib["0.95-1.00"]["exactitude"] < 1.0


def test_evaluation_valeur_inventee_sur_champ_vide(gts):
    gt = gts["specimen_p04.json"]
    pred = predict_from_gt(gt, "dossiers_specimen_10_patientes-04.png")
    pred["fields"]["accouchement.indication_cesarienne"] = {"value": "SFA", "status": "CONNU", "confidence": 0.8}
    m = metrics(evaluate([pred], gts)["groups"]["global:tout"])
    assert m["valeurs_inventees"] == 1 and m["vides_non_fourni"] < 1.0


def test_modeles_photos_reelles(gts):
    for n in range(1, 6):
        g = gts[f"reel_1-{n}.json"]
        assert g["source"] == "reel" and g["fields"]
        assert not set(g["fields"]) & IDENTIFIER_KEYS
    assert "grossesse_actuelle.visites.T1V1.ta" in gts["reel_1-4.json"]["fields"]
    assert "grossesse_actuelle.visites.T2V1.ta" not in gts["reel_1-4.json"]["fields"]
