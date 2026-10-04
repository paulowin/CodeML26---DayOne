"""Bloc 3b : cerveau IA local, testé avec un FAUX Ollama (aucun GPU, aucun réseau)."""
import io
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from PIL import Image, ImageDraw

from ai import confidence as C
from ai.extract import FieldState, Reading, apply_verify, contains_identifier, extract_pages, merge, privacy_filter
from ai.ollama_client import GenResult, OllamaClient, OllamaUnavailable, first_json_object
from ai.prompts import build_prompt, build_schema, page_spec
from ai.validate import validate
from app.templates import get_template
from app.templates.normalize import interpret, text_equal, values_equal
from tests.conftest import body_of

T = get_template()
F = T.fields
V = "grossesse_actuelle.visites.T1V1."


# ------------------------------------------------------------------ normalisation (≥ 25 cas)
@pytest.mark.parametrize("key,raw,value,status", [
    (V + "seins", "RAS", "RAS", None),
    (V + "seins", "R.A.S", "RAS", None),
    (V + "seins", "Néant", "RAS", None),
    (V + "seins", "aucune", "RAS", None),
    ("identification.niveau_instruction", "Aucun", "Aucun", None),         # « Aucun » = vraie réponse ici
    (V + "syphilis", "nég", "NEGATIF", None),
    (V + "syphilis", "Neg", "NEGATIF", None),
    (V + "vih", "négatif", "NEGATIF", None),
    (V + "vih", "pos", "POSITIF", None),
    (V + "albuminurie", "+", "POSITIF", None),
    (V + "bcf", "—", None, "NON_APPLICABLE"),
    (V + "bcf", "-", None, "NON_APPLICABLE"),
    (V + "bcf", "", None, "NON_FOURNI"),
    (V + "bcf", "#ILLISIBLE", None, "ILLISIBLE"),
    (V + "ta", "11/7", {"sys": 110, "dia": 70}, None),
    (V + "ta", "151/97", {"sys": 151, "dia": 97}, None),
    (V + "age_probable_sa", "16SA+3j", 16.4, None),
    (V + "age_probable_sa", "16 SA 3j", 16.4, None),
    (V + "age_probable_sa", "12 SA", 12.0, None),
    (V + "glycemie", "0,76 g/l", 76.0, None),                           # g/L -> mg/dL
    (V + "hemoglobine", "11,5 g/dL", 11.5, None),
    (V + "poids_kg", "63 kg", 63.0, None),
    ("accouchement.poids_naissance_g", "3,4 kg", 3400, None),
    ("pp_precoce_mere.temperature_c", "37,2", 37.2, None),
    ("antecedents_obstetricaux.gestite", "1G", 1, None),
    ("antecedents_obstetricaux.enfants_vivants", "00", 0, None),
    ("grossesse_actuelle.ddr", "19/05/2025", "2025-05-19", None),
    ("grossesse_actuelle.ddr", "/19/05/2025/", "2025-05-19", None),
    ("grossesse_actuelle.ddr", "3-2-26", "2026-02-03", None),
    ("grossesse_actuelle.ddr", "13.01.2026", "2026-01-13", None),
])
def test_normalisation(key, raw, value, status):
    it = interpret(F[key], raw)
    assert (it.value, it.status) == (value, status)


def test_normalisation_date_partielle_et_accents():
    it = interpret(F[V + "venue_le"], "12/05")
    assert it.value == "12/05" and "date_partielle" in it.flags
    # accents : ni la police sans accents (vérité) ni le modèle (prédiction) ne sont pénalisés
    assert text_equal("Coll�ge", "Collège") and text_equal("Collège", "Collge")
    assert text_equal("Céphalique", "Cephalique") and not text_equal("Lycée", "Collège")
    assert values_equal(F["grossesse_actuelle.ddr"], "19/05/2025", "2025-05-19")


# ------------------------------------------------------------------ validations croisées
def test_validations_croisees():
    flags = validate({
        "antecedents_obstetricaux.gestite": 1, "antecedents_obstetricaux.parite": 3,
        "antecedents_obstetricaux.enfants_vivants": 6,
        "grossesse_actuelle.visites.T1V1.ta": {"sys": 70, "dia": 110},
        "grossesse_actuelle.ddr": "2025-04-26", "grossesse_actuelle.dpa": "2026-03-30",
        "grossesse_actuelle.visites.T1V1.age_probable_sa": 30.0,
        "grossesse_actuelle.visites.T1V1.venue_le": "2025-07-20",
        "accouchement.age_gestationnel_sa": 40.0, "accouchement.poids_naissance_g": 900,
    })
    assert "gestite_parite_incoherentes" in flags["antecedents_obstetricaux.gestite"]
    assert "enfants_vivants_superieurs_parite" in flags["antecedents_obstetricaux.enfants_vivants"]
    assert "ta_sys_inferieure_dia" in flags["grossesse_actuelle.visites.T1V1.ta"]
    assert "dpa_incoherente_avec_ddr" in flags["grossesse_actuelle.dpa"]
    assert "age_gestationnel_incoherent_ddr" in flags["grossesse_actuelle.visites.T1V1.age_probable_sa"]
    assert "poids_incoherent_avec_age" in flags["accouchement.poids_naissance_g"]
    ok = validate({"antecedents_obstetricaux.gestite": 3, "antecedents_obstetricaux.parite": 1,
                   "grossesse_actuelle.ddr": "2025-04-26", "grossesse_actuelle.dpa": "2026-01-31",
                   "accouchement.age_gestationnel_sa": 40.0, "accouchement.poids_naissance_g": 3587})
    assert ok == {}


# ------------------------------------------------------------------ confiance / statuts
def test_confiance_et_statuts():
    seuil = 0.8
    e = C.Evidence(declared=0.99)                                  # plafonnée à 0.85
    assert C.score(e) == 0.85 and C.status(None, 0.85, seuil, False, e) == "CONNU"
    e2 = C.Evidence(declared=0.99, n_agree=2)
    assert C.score(e2) == 0.95
    bad = C.Evidence(declared=0.99, n_agree=2, validation_failed=True)
    assert C.score(bad) <= 0.4 and C.status(None, C.score(bad), seuil, False, bad) == "A_REVISER"
    assert C.status("NON_APPLICABLE", 0.9, seuil, False, e) == "NON_APPLICABLE"
    assert C.status("ILLISIBLE", 0.9, seuil, False, e) == "ILLISIBLE"


def test_champ_critique_jamais_connu_sur_une_lecture():
    e = C.Evidence(declared=0.99)
    assert C.status(None, C.score(e), 0.5, critical=True, e=e) == "A_REVISER"
    e.verified = True                                              # 2e avis concordant
    assert C.score(e) == 0.99 and C.status(None, C.score(e), 0.8, True, e) == "CONNU"


def test_desaccord_donne_des_candidats():
    st = FieldState(F[V + "ta"], [Reading(V + "ta", "11/7", "LISIBLE", 0.9, 0)])
    merge(st)
    st.readings.append(Reading(V + "ta", "17/7", "LISIBLE", 0.9, 0, source="verify"))
    apply_verify(st)
    assert st.evidence.verified is False
    assert st.candidates == [{"sys": 110, "dia": 70}, {"sys": 170, "dia": 70}]
    assert C.status(None, C.score(st.evidence), 0.8, True, st.evidence) == "A_REVISER"

    # deux bandes qui se recouvrent et lisent différemment
    st = FieldState(F[V + "poids_kg"], [Reading(V + "poids_kg", "58.8", "LISIBLE", 0.8, 0),
                                        Reading(V + "poids_kg", "38.8", "LISIBLE", 0.7, 1)])
    merge(st)
    assert st.evidence.disagreement and st.candidates == [58.8, 38.8]
    # une bande coupée qui voit « VIDE » ne contredit pas une lecture
    st = FieldState(F[V + "poids_kg"], [Reading(V + "poids_kg", "58.8", "LISIBLE", 0.8, 0),
                                        Reading(V + "poids_kg", "", "VIDE", 0.9, 1)])
    merge(st)
    assert not st.evidence.disagreement and st.interp.value == 58.8


# ------------------------------------------------------------------ confidentialité
def test_filtre_telephone_et_cin():
    assert contains_identifier("06 00 76 13 48") and contains_identifier("0600761348")
    assert contains_identifier("+212 6 00 76 13 48") and contains_identifier("CIN CB609814")
    assert not contains_identifier("110/70") and not contains_identifier("12/05/2022")
    fields = {
        V + "seins": {"value": "RAS", "raw_text": "RAS tel 0612345678", "candidates": [], "flags": []},
        "antecedents_femme.medicaux": {"value": "voir CB609814", "raw_text": "x", "candidates": [], "flags": []},
        "identification.cin": {"value": "CB609814", "raw_text": "CB609814", "candidates": [], "flags": []},
        "accouchement.poids_naissance_g": {"value": 3587, "raw_text": "3587 g", "candidates": [], "flags": []},
    }
    kept, removed = privacy_filter(fields)
    assert set(kept) == {V + "seins", "accouchement.poids_naissance_g"}
    assert kept[V + "seins"]["raw_text"] is None and "identifiant_retire" in kept[V + "seins"]["flags"]
    assert removed == 3


def test_prompt_sans_identifiants_et_restreint_au_type_de_page():
    spec = page_spec("accouchement")
    prompt, schema = build_prompt(spec, 0, 3), json.dumps(build_schema(spec))
    assert "accouchement.poids_naissance_g" in prompt and "grossesse_actuelle" not in prompt
    assert "nom_patiente" not in prompt and "nom_patiente" not in schema
    spec = page_spec("grossesse_actuelle")
    assert not any("examen_fait_par" in k for k in spec.keys)
    sch = build_schema(spec)
    assert sch["required"] == ["champs", "lignes", "cochees", "confiance"]   # conteneurs seulement
    assert "required" not in sch["properties"]["champs"]                     # aucun champ obligatoire
    assert "grossesse_actuelle.visites.T1V1.examen_fait_par" not in json.dumps(sch)


# ------------------------------------------------------------------ client Ollama
def _transport(responses: list, calls: list):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fake"}]})
        r = responses.pop(0)
        return httpx.Response(200, json={"response": r, "done_reason": "stop", "eval_count": 3})
    return httpx.MockTransport(handler)


def test_reponse_vide_puis_nouvelle_tentative_sans_format():
    calls = []
    cl = OllamaClient(transport=_transport(["", "", 'Voici : ```json {"a": 1} ``` fin'], calls))
    res = cl.generate("fake", "p", [b"img"], {"type": "object"})
    assert res.data == {"a": 1} and res.retried_without_format
    assert [("format" in c) for c in calls] == [True, True, False]
    assert first_json_object('bla {"x": {"y": "}"}} {"z": 2}') == {"x": {"y": "}"}}


def test_reponse_tronquee_paires_completes_gardees():
    from ai.ollama_client import repair_truncated_json
    cut = '{"champs": {"a.b": "3587 g", "a.c": "F", "a.d": "RAS RAS RAS R'
    assert repair_truncated_json(cut) == {"champs": {"a.b": "3587 g", "a.c": "F"}}
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"response": cut, "done_reason": "length"})
    res = OllamaClient(transport=httpx.MockTransport(handler)).generate("fake", "p", [], {"type": "object"})
    assert res.data["champs"]["a.c"] == "F" and len(calls) == 1


def test_plantage_grammaire_passe_directement_sans_format():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("format" in body)
        if "format" in body:
            return httpx.Response(500, json={"error": "Unexpected empty grammar stack"})
        return httpx.Response(200, json={"response": '{"ok": 1}', "done_reason": "stop"})
    res = OllamaClient(transport=httpx.MockTransport(handler)).generate("fake", "p", [], {"type": "object"})
    assert res.data == {"ok": 1} and calls == [True, False]


def test_tableau_decoupe_en_petites_requetes():
    parts = page_spec("grossesse_actuelle").chunks(8)
    assert len(parts) == 1 + 4                                    # en-tête + 31 lignes / 8
    assert parts[0].simple and not parts[0].lines and all(len(p.lines) <= 8 for p in parts[1:])
    assert set().union(*(p.keys for p in parts)) == page_spec("grossesse_actuelle").keys


def test_ollama_coupe_leve_unavailable():
    def handler(request):
        raise httpx.ConnectError("refusé", request=request)
    cl = OllamaClient(transport=httpx.MockTransport(handler))
    with pytest.raises(OllamaUnavailable):
        cl.generate("fake", "p", [], None)
    with pytest.raises(OllamaUnavailable):
        cl.ping()


# ------------------------------------------------------------------ faux VLM pour le pipeline
def page_png() -> bytes:
    """Fausse page lisible (lignes + texte) : passe le contrôle qualité."""
    img = Image.new("RGB", (1200, 1700), "white")
    d = ImageDraw.Draw(img)
    for y in range(60, 1700, 40):
        d.line((40, y, 1160, y), fill="black", width=2)
        d.text((60, y - 25), "Poids a la naissance : 3587 g   Sexe : F", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class FakeVLM:
    """Répond comme qwen2.5vl (format compact) : classification puis bandes / 2e avis."""

    def __init__(self, verify_poids="3587 g"):
        self.calls = []
        self.verify_poids = verify_poids

    def generate(self, model, prompt, images, schema=None, use_cache=True, num_predict=None):
        self.calls.append((model, prompt[:60]))
        if "titres" in json.dumps(schema or {}):
            return GenResult({"titres": ["DÉROULEMENT DE L'ACCOUCHEMENT"], "type": "accouchement"}, model, 0.1)
        if model == "verify":
            return GenResult({"champs": {"accouchement.poids_naissance_g": self.verify_poids,
                                         "accouchement.date": "03/02/2026"},
                              "cochees": ["accouchement.mode=voie_basse_non_instrumentale"],
                              "confiance": 0.9}, model, 0.1)
        band = int(prompt.split("partie ")[1].split(" ")[0]) if "partie " in prompt else 1
        if band == 1:
            return GenResult({"champs": {
                "accouchement.date": "03/02/2026",
                "accouchement.indication_cesarienne": "Mode de l'accouchement :",   # libellé recopié
                "accouchement.lieu_autre_milieu": "",
                "accouchement.inventee": "x"},                                       # clé inventée
                "cochees": ["accouchement.mode=voie_basse_non_instrumentale", "accouchement.mode=inventee",
                            "accouchement.episiotomie"],
                "confiance": 0.9}, model, 0.1)
        return GenResult({"champs": {
            "accouchement.poids_naissance_g": "3587 g", "accouchement.sexe": "F",
            "accouchement.anomalie": "Aucune", "accouchement.complications_autre": "—",
            "accouchement.age_gestationnel_sa": "40 SA"}, "confiance": 0.95}, model, 0.1)


def test_pipeline_complet_avec_faux_ollama():
    vlm = FakeVLM()
    res = extract_pages([page_png()], client=vlm, main_model="main", verify_model="verify", seuil=0.8)[0]
    f = res.fields
    assert res.page_type == "accouchement" and res.quality["ok"]
    assert f["accouchement.poids_naissance_g"]["value"] == 3587
    assert f["accouchement.poids_naissance_g"]["status"] == "CONNU"           # critique + 2e avis concordant
    assert f["accouchement.date"]["value"] == "2026-02-03" and f["accouchement.date"]["status"] == "CONNU"
    assert f["accouchement.sexe"]["status"] == "CONNU" and f["accouchement.sexe"]["confidence"] == 0.95  # 2 bandes
    assert f["accouchement.complications_autre"]["status"] == "NON_APPLICABLE"
    assert f["accouchement.lieu_autre_milieu"]["status"] == "NON_FOURNI"
    assert "accouchement.indication_cesarienne" not in f                    # libellé recopié -> rejeté
    assert "accouchement.perimetre_cranien_cm" not in f                     # absent de la zone : rien inventé
    assert "accouchement.inventee" not in f
    assert f["accouchement.mode"]["value"] == "voie_basse_non_instrumentale"
    assert f["accouchement.mode"]["status"] == "A_REVISER"                   # case : toujours confirmée
    assert f["accouchement.episiotomie"]["value"] is True
    assert f["accouchement.episiotomie"]["status"] == "A_REVISER"            # case vue une seule fois
    assert "accouchement.instrument" not in f                               # aucune case vue : rien inventé
    assert any(m == "verify" for m, _ in vlm.calls)


def test_pipeline_desaccord_du_2e_avis():
    res = extract_pages([page_png()], client=FakeVLM(verify_poids="3887 g"), main_model="main",
                        verify_model="verify", seuil=0.8)[0]
    p = res.fields["accouchement.poids_naissance_g"]
    assert p["status"] == "A_REVISER" and p["candidates"] == [3587, 3887]


def test_champ_vu_dans_toutes_les_bandes_sans_valeur_est_absent():
    from ai.extract import drop_impossible_readings
    k = "accouchement.anomalie"
    st = FieldState(F[k], [Reading(k, "#ILLISIBLE", "ILLISIBLE", 0.9, b) for b in range(3)])
    ok = FieldState(F[k], [Reading(k, "#ILLISIBLE", "ILLISIBLE", 0.9, 0), Reading(k, "Aucune", "LISIBLE", 0.9, 1),
                           Reading(k, "", "VIDE", 0.9, 2)])
    states = {"a": st, "b": ok}
    drop_impossible_readings(states, 3)
    merge(st), merge(ok)
    assert st.interp is None and "absent_de_la_page" in st.flags
    assert ok.interp.value == "RAS"                    # « Aucune » -> RAS


def test_libelle_recopie_retire_ou_rejete():
    from ai.extract import _printed_labels, strip_printed_label
    labels = _printed_labels("couverture")
    k = "couverture.type_risque_autre"

    def run(raw):
        st = FieldState(F[k])
        r = strip_printed_label(Reading(k, raw, "LISIBLE", 0.9, 0), st, labels)
        return (r.raw, r.etat) if r else None, st.flags
    assert run("Autres à préciser : #ILLISIBLE")[0] == ("#ILLISIBLE", "ILLISIBLE")
    assert run("Autres à préciser : Asthme") == (("Asthme", "LISIBLE"), ["libelle_retire"])
    assert run("Autres à préciser :") == (None, ["libelle_recopie"])
    assert run("Mobile") == (None, ["libelle_recopie"])                     # option imprimée


def test_case_cochee_par_l_ia_jamais_connue():
    vlm = FakeVLM()
    res = extract_pages([page_png()], client=vlm, main_model="main", verify_model="verify", seuil=0.5)[0]
    mode = res.fields["accouchement.mode"]
    assert mode["value"] == "voie_basse_non_instrumentale" and mode["status"] == "A_REVISER"
    assert mode["confidence"] <= C.CHECKBOX_CAP


def test_page_illisible_ne_plante_pas():
    res = extract_pages([b"pas une image"], client=FakeVLM(), main_model="main", verify_model="")[0]
    assert res.error and res.fields == {}


# ------------------------------------------------------------------ worker backend
def _record_en_attente(db, n_pages=1):
    from app.models import Midwife, Page, Record, RecordStatus
    from app.storage import get_store
    mw = Midwife(wa_id="212600000099")
    db.add(mw)
    db.flush()
    rec = Record(midwife_id=mw.id, status=RecordStatus.EN_ATTENTE_IA)
    db.add(rec)
    db.flush()
    for i in range(n_pages):
        key, sha = get_store().save(page_png())
        rec.pages.append(Page(page_number=i + 1, storage_key=key, sha256=sha, mime_type="image/png",
                              size_bytes=10, wa_message_id=uuid.uuid4().hex, captured_at=datetime.now(timezone.utc)))
    db.commit()
    return rec


def test_worker_en_attente_ia_vers_a_reviser(client):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ExtractedField, FieldSource, OutboundMessage, Record, RecordStatus
    from app.services import ai_worker
    vlm = FakeVLM()
    with SessionLocal() as db:
        rec_id = _record_en_attente(db).id
        done = ai_worker.process_next(db, extractor=lambda imgs: extract_pages(
            imgs, client=vlm, main_model="main", verify_model="verify", seuil=0.8))
        assert done == rec_id
        rec = db.get(Record, rec_id)
        assert rec.status == RecordStatus.A_REVISER and rec.ai_attempts == 1
        fields = {f"{f.section}.{f.field_key}": f for f in rec.fields}
        poids = fields["accouchement.poids_naissance_g"]
        assert json.loads(poids.value_json) == 3587 and poids.source == FieldSource.IA
        assert poids.page_number == 1 and poids.is_current and poids.raw_text == "3587 g"
        assert [e.to_status for e in rec.events][-2:] == ["TRAITE_IA", "A_REVISER"]
        assert rec.pages[0].page_type == "accouchement"
        msgs = [body_of(json.loads(m.payload_json)) for m in db.scalars(select(OutboundMessage)).all()]
        assert any(m.startswith("Lecture terminée") for m in msgs)
        assert all(not f.field_key.startswith("nom") for f in db.scalars(select(ExtractedField)).all())
        assert ai_worker.process_next(db) is None                       # plus rien à lire


def test_worker_ollama_coupe_echec_traitement(client):
    from app.db import SessionLocal
    from app.models import Record, RecordStatus
    from app.services import ai_worker

    def down(_imgs):
        raise OllamaUnavailable("connexion refusée")

    with SessionLocal() as db:
        rec_id = _record_en_attente(db).id
        ai_worker.process_next(db, extractor=down)
        rec = db.get(Record, rec_id)
        assert rec.status == RecordStatus.ECHEC_TRAITEMENT and rec.ai_attempts == 1
        assert "indisponible" in rec.failure_reason
        assert rec.fields == []


def test_worker_photo_floue_previent_la_sage_femme(client):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import OutboundMessage, Record
    from app.services import ai_worker

    def blurry(imgs):
        res = extract_pages(imgs, client=FakeVLM(), main_model="main", verify_model="", seuil=0.8)
        res[0].quality = {"ok": False, "raisons": ["floue"]}
        return res

    with SessionLocal() as db:
        rec_id = _record_en_attente(db).id
        ai_worker.process_next(db, extractor=blurry)
        rec = db.get(Record, rec_id)
        assert json.loads(rec.pages[0].quality_json)["raisons"] == ["floue"]
        msgs = [body_of(json.loads(m.payload_json)) for m in db.scalars(select(OutboundMessage)).all()]
        assert any("floue" in m and "reprendre" in m for m in msgs)
