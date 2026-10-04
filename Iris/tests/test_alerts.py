"""Alertes cliniques : règles simples, valeurs confirmées par la sage-femme uniquement."""
import json

from app.models import ExtractedField, FieldSource, FieldStatus, Record
from app.services.alerts import compute, message, record_alerts

V = "grossesse_actuelle.visites."


def codes(values):
    return [a.code for a in compute(values)]


def test_seuils_tension():
    assert codes({V + "T2V2.ta": {"sys": 135, "dia": 85}}) == []
    assert codes({V + "T2V2.ta": {"sys": 140, "dia": 80}}) == ["hta"]
    assert codes({V + "T2V2.ta": {"sys": 150, "dia": 110}}) == ["hta_severe"]       # TAD ≥ 110
    assert codes({V + "T2V2.ta": {"sys": 160, "dia": 95}}) == ["hta_severe"]


def test_preeclampsie_seulement_apres_20_sa():
    v = {V + "T1V3.ta": {"sys": 145, "dia": 92}, V + "T1V3.albuminurie": "POSITIF", V + "T1V3.age_probable_sa": 14}
    assert "preeclampsie" not in codes(v)
    v[V + "T1V3.age_probable_sa"] = 24
    assert "preeclampsie" in codes(v)
    v[V + "T1V3.oedemes"] = "Oui"
    assert "preeclampsie_oed" in codes(v)


def test_ta_en_hausse_sur_3_visites():
    v = {V + "T2V1.ta": {"sys": 110, "dia": 70}, V + "T2V2.ta": {"sys": 118, "dia": 72},
         V + "T2V3.ta": {"sys": 126, "dia": 80}}
    a = compute(v)
    assert [x.code for x in a] == ["ta_hausse"] and a[0].params["seq"] == "110/70 → 118/72 → 126/80"
    v[V + "T2V3.ta"] = {"sys": 115, "dia": 80}
    assert codes(v) == []


def test_anemie_bcf_terme():
    assert codes({V + "M7.hemoglobine": 10.9}) == ["anemie"]
    assert codes({V + "M7.hemoglobine": 6.5}) == ["anemie_severe"]
    assert codes({V + "M7.hemoglobine": 11.0}) == []
    assert codes({V + "M8.bcf": 100}) == ["bcf"] and codes({V + "M8.bcf": 165}) == ["bcf"]
    assert codes({V + "M8.bcf": 140}) == []
    assert codes({V + "M9.age_probable_sa": 41.5}) == ["terme"]
    assert codes({V + "M9.age_probable_sa": 41.5, "accouchement.date": "2026-01-20"}) == []


def test_message_aide_a_la_decision():
    msg = message(compute({V + "M7.hemoglobine": 10.9}), "fr")
    assert msg == "⚠️ Signes d'alerte : anémie (Hb 10,9 g/dL). À évaluer selon le protocole."
    assert message([], "fr") is None
    assert "diagnostic" not in msg.lower()


def _ef(key, value, status, source):
    section, fk = key.split(".", 1)
    return ExtractedField(section=section, field_key=fk, value_json=json.dumps(value), status=status,
                          source=source, confidence=1.0, is_current=True)


def test_jamais_sur_une_valeur_a_verifier_ou_non_confirmee():
    rec = Record()
    rec.fields = [_ef(V + "M7.ta", {"sys": 170, "dia": 115}, FieldStatus.A_REVISER, FieldSource.IA),
                  _ef(V + "M8.hemoglobine", 8.0, FieldStatus.CONNU, FieldSource.IA),      # IA seule
                  _ef(V + "M9.bcf", 90, FieldStatus.A_REVISER, FieldSource.SAGE_FEMME)]
    assert record_alerts(rec) == []
    rec.fields.append(_ef(V + "M9.hemoglobine", 10.0, FieldStatus.CONNU, FieldSource.SAGE_FEMME))
    assert [a.code for a in record_alerts(rec)] == ["anemie"]
