"""Tests du bloc 2 : machine à états, synchronisation hors ligne, doublons, API admin."""
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.main import run_maintenance_cycle
from app.models import (CentralRecord, ExtractedField, FieldSource, FieldStatus, Midwife, OutboundMessage,
                        Page, Patient, Record, RecordEvent, RecordStatus, Role, Staff)
from app.security import hash_api_key
from app.services import sync
from app.state_machine import MAX_AI_ATTEMPTS, TRANSITIONS, InvalidTransition, allowed_next, transition

S = RecordStatus
MW_WA = "212600000042"


# ------------------------------------------------------------------ helpers
def _midwife(db) -> Midwife:
    mw = db.scalar(select(Midwife).where(Midwife.wa_id == MW_WA))
    if not mw:
        mw = Midwife(wa_id=MW_WA)
        db.add(mw)
        db.flush()
    return mw


def _record(db, status: RecordStatus, *, patient: bool = True, attempts: int = MAX_AI_ATTEMPTS,
            fields: dict[str, FieldStatus] | None = None) -> Record:
    """Dossier dans l'état voulu, qui satisfait par défaut toutes les gardes."""
    mw = _midwife(db)
    pat = None
    if patient:
        pat = Patient(midwife_id=mw.id, code=f"P{uuid.uuid4().hex[:6]}")
        db.add(pat)
        db.flush()
    rec = Record(midwife_id=mw.id, status=status, ai_attempts=attempts, patient_id=pat.id if pat else None)
    db.add(rec)
    db.flush()
    rec.pages.append(Page(page_number=1, storage_key=uuid.uuid4().hex, sha256=uuid.uuid4().hex,
                          mime_type="image/jpeg", size_bytes=10, wa_message_id=uuid.uuid4().hex,
                          captured_at=datetime.now(timezone.utc)))
    for key, st in (fields or {}).items():
        section, field_key = key.split(".", 1)
        rec.fields.append(ExtractedField(section=section, field_key=field_key, value_json=json.dumps("x"),
                                         status=st, confidence=0.5, source=FieldSource.IA))
    db.flush()
    return rec


def _field(rec: Record, key: str, value, status=FieldStatus.CONNU):
    section, field_key = key.split(".", 1)
    rec.fields.append(ExtractedField(section=section, field_key=field_key, value_json=json.dumps(value),
                                     status=status, confidence=0.9, source=FieldSource.SAGE_FEMME))


ACTOR = "midwife:test"
ALLOWED = [(frm, to) for frm, tos in TRANSITIONS.items() if frm is not None for to in sorted(tos)]


# ------------------------------------------------------------------ table des transitions
@pytest.mark.parametrize("frm,to", ALLOWED, ids=[f"{f.value}->{t.value}" for f, t in ALLOWED])
def test_transitions_autorisees(client, frm, to):
    with SessionLocal() as db:
        rec = _record(db, frm)
        ev = transition(db, rec, to, ACTOR)
        db.commit()
        assert rec.status == to
        assert (ev.from_status, ev.to_status, ev.actor) == (frm.value, to.value, ACTOR)


@pytest.mark.parametrize("frm,to", [(S.CAPTURE, S.VALIDE), (S.SYNCHRONISE, S.ENREGISTRE),
                                    (S.ANNULE, S.CAPTURE), (S.TRAITE_IA, S.VALIDE),
                                    (S.EN_ATTENTE_IA, S.SYNCHRONISE), (S.VALIDE, S.ENREGISTRE)])
def test_transitions_interdites(client, frm, to):
    with SessionLocal() as db:
        rec = _record(db, frm)
        with pytest.raises(InvalidTransition, match=f"{frm.value} -> {to.value} interdit"):
            transition(db, rec, to, ACTOR)
        assert rec.status == frm and not rec.events


def test_etats_finaux_et_creation():
    assert allowed_next(S.SYNCHRONISE) == set() and allowed_next(S.ANNULE) == set()
    assert allowed_next(None) == {S.CAPTURE}


def test_creation_uniquement_en_capture(client):
    with SessionLocal() as db:
        mw = _midwife(db)
        with pytest.raises(InvalidTransition):
            transition(db, Record(midwife_id=mw.id), S.EN_ATTENTE_IA, ACTOR)
        rec = Record(midwife_id=mw.id)
        db.add(rec)
        ev = transition(db, rec, S.CAPTURE, ACTOR)
        db.commit()
        assert ev.from_status is None and rec.status == S.CAPTURE


def test_chaque_transition_journalisee_avec_acteur(client):
    with SessionLocal() as db:
        rec = _record(db, S.ENREGISTRE)
        transition(db, rec, S.ECHEC_SYNCHRO, "system", reason="réseau coupé")
        transition(db, rec, S.SYNCHRONISE, "staff:abc")
        db.commit()
        evs = db.scalars(select(RecordEvent).where(RecordEvent.record_id == rec.id).order_by(RecordEvent.id)).all()
        assert [(e.from_status, e.to_status, e.actor) for e in evs] == [
            ("ENREGISTRE", "ECHEC_SYNCHRO", "system"), ("ECHEC_SYNCHRO", "SYNCHRONISE", "staff:abc")]


def test_failure_reason_renseigne_puis_vide(client):
    with SessionLocal() as db:
        rec = _record(db, S.ENREGISTRE)
        transition(db, rec, S.ECHEC_SYNCHRO, "system", reason="réseau coupé")
        assert rec.failure_reason == "réseau coupé"
        transition(db, rec, S.SYNCHRONISE, "system")
        assert rec.failure_reason is None


# ------------------------------------------------------------------ gardes
@pytest.mark.parametrize("actor", ["ia", "system", "staff:x"])
def test_valide_refuse_si_pas_sage_femme(client, actor):
    with SessionLocal() as db:
        rec = _record(db, S.A_REVISER)
        with pytest.raises(InvalidTransition, match="seule la sage-femme"):
            transition(db, rec, S.VALIDE, actor)


@pytest.mark.parametrize("blocking", [FieldStatus.ILLISIBLE, FieldStatus.A_REVISER])
def test_valide_refuse_si_champ_a_reviser(client, blocking):
    with SessionLocal() as db:
        rec = _record(db, S.A_REVISER, fields={"profil.age": FieldStatus.CONNU, "grossesse_en_cours.ta": blocking})
        with pytest.raises(InvalidTransition, match="grossesse_en_cours.ta"):
            transition(db, rec, S.VALIDE, ACTOR)
        # une fois corrigé (ancienne version non courante), la validation passe
        rec.fields[1].is_current = False
        transition(db, rec, S.VALIDE, ACTOR)
        assert rec.status == S.VALIDE


def test_patiente_liee_refusee_sans_patient(client):
    with SessionLocal() as db:
        rec = _record(db, S.VALIDE, patient=False)
        with pytest.raises(InvalidTransition, match="patient_id"):
            transition(db, rec, S.PATIENTE_LIEE, ACTOR)


def test_capture_sans_page_ne_part_pas_en_ia(client):
    with SessionLocal() as db:
        rec = _record(db, S.CAPTURE)
        rec.pages.clear()
        with pytest.raises(InvalidTransition, match="aucune page"):
            transition(db, rec, S.EN_ATTENTE_IA, ACTOR)


def test_revision_manuelle_refusee_avant_3_tentatives(client):
    with SessionLocal() as db:
        rec = _record(db, S.ECHEC_TRAITEMENT, attempts=2)
        with pytest.raises(InvalidTransition, match="2/3"):
            transition(db, rec, S.REVISION_MANUELLE_REQUISE, "system")


# ------------------------------------------------------------------ worker : échecs IA
def test_worker_reprise_echec_traitement(client, fake_wa):
    with SessionLocal() as db:
        retry = _record(db, S.ECHEC_TRAITEMENT, attempts=1)
        manual = _record(db, S.ECHEC_TRAITEMENT, attempts=3)
        db.commit()
        retry_id, manual_id = retry.id, manual.id
    run_maintenance_cycle()
    with SessionLocal() as db:
        assert db.get(Record, retry_id).status == S.EN_ATTENTE_IA
        assert db.get(Record, manual_id).status == S.REVISION_MANUELLE_REQUISE
        assert db.scalar(select(OutboundMessage)) is not None
    assert len(fake_wa.sent) == 1
    assert f"dossier {manual_id[:8]}" in fake_wa.sent[0]["text"]["body"]
    assert "saisir ensemble" in fake_wa.sent[0]["text"]["body"]


# ------------------------------------------------------------------ synchronisation hors ligne
def test_scenario_hors_ligne_puis_retour_reseau(client):
    with SessionLocal() as db:
        recs = [_record(db, S.ENREGISTRE), _record(db, S.ENREGISTRE)]
        _field(recs[0], "profil.age", 27)
        sync.set_flag(db, sync.NETWORK_FLAG, "off")
        db.commit()
        ids = [r.id for r in recs]

        assert sync.sync_pending(db) == 0
        assert all(db.get(Record, i).status == S.ECHEC_SYNCHRO for i in ids)
        assert db.get(Record, ids[0]).failure_reason == "réseau central coupé"
        assert db.scalar(select(CentralRecord)) is None
        # toujours coupé : on reste en ECHEC_SYNCHRO sans erreur de transition
        assert sync.sync_pending(db) == 0

        sync.set_flag(db, sync.NETWORK_FLAG, "on")
        db.commit()
        assert sync.sync_pending(db) == 2
        for i in ids:
            rec = db.get(Record, i)
            assert rec.status == S.SYNCHRONISE and rec.synced_at is not None and rec.failure_reason is None

        central = db.scalars(select(CentralRecord)).all()
        assert len(central) == 2
        for c in central:
            assert MW_WA not in c.payload_json
            payload = json.loads(c.payload_json)
            assert set(payload) == {"record_id", "patient_id", "captured_at", "fields"}
            assert not any(k in c.payload_json for k in ("storage_key", "sha256", "image"))
        assert {"key": "profil.age", "value": 27, "status": "CONNU", "confidence": 0.9,
                "source": "SAGE_FEMME"} in json.loads(db.get(CentralRecord, ids[0]).payload_json)["fields"]

        # relancer la synchro ne crée pas de doublon (rien à faire, et push idempotent)
        assert sync.sync_pending(db) == 0
        sync.push(db, db.get(Record, ids[0]))
        db.commit()
        assert len(db.scalars(select(CentralRecord)).all()) == 2


# ------------------------------------------------------------------ doublons
def test_find_duplicate_meme_date_meme_patiente(client):
    from app.state_machine import find_duplicate
    with SessionLocal() as db:
        old = _record(db, S.SYNCHRONISE)
        _field(old, "accouchement.date", "03/02/2026")
        other_date = _record(db, S.ENREGISTRE)
        other_date.patient_id = old.patient_id
        _field(other_date, "accouchement.date", "01/08/2026")
        same_date_other_type = _record(db, S.ENREGISTRE)
        same_date_other_type.patient_id = old.patient_id
        _field(same_date_other_type, "pp_precoce_mere.date_consultation", "03/02/2026")
        new = _record(db, S.VALIDE, patient=False)
        _field(new, "accouchement.date", "3/2/26")                 # même date, autre écriture
        db.commit()

        assert find_duplicate(db, new, old.patient_id).id == old.id
        other = _record(db, S.VALIDE)
        assert find_duplicate(db, new, other.patient_id) is None      # autre patiente
        no_date = _record(db, S.VALIDE, patient=False)
        assert find_duplicate(db, no_date, old.patient_id) is None    # date inconnue


def test_date_reference_selon_le_type_de_page(client):
    from app.state_machine import date_reference
    with SessionLocal() as db:
        # grossesse : « venue le » de la visite la plus récente (pas l'ordre des colonnes)
        rec = _record(db, S.A_REVISER)
        _field(rec, "grossesse_actuelle.visites.T1V2.venue_le", "20/07/2025")
        _field(rec, "grossesse_actuelle.visites.M9.venue_le", "18/01/2026")
        _field(rec, "grossesse_actuelle.visites.M8.venue_le", "29/12/2025")
        _field(rec, "grossesse_actuelle.visites.T1V3.rendez_vous", "01/03/2026")   # rendez-vous : ignoré
        _field(rec, "grossesse_actuelle.visites.T2V1.venue_le", "—")               # tiret : ignoré
        assert date_reference(rec) == "18/01/2026"
        # accouchement prioritaire sur le tableau de visites
        _field(rec, "accouchement.date", "2026-02-03")
        assert date_reference(rec) == "03/02/2026"
        # post-partum prioritaire sur tout le reste
        _field(rec, "pp_tardif_nne.date_consultation", "18/03/2026")
        assert date_reference(rec) == "18/03/2026"
        # une valeur corrigée (is_current=False) ne compte plus
        rec.fields[-1].is_current = False
        assert date_reference(rec) == "03/02/2026"
        assert date_reference(_record(db, S.A_REVISER)) is None


# ------------------------------------------------------------------ API admin
def _staff(db, role, key, midwife_id=None):
    db.add(Staff(label=key, role=role, api_key_hash=hash_api_key(key), midwife_id=midwife_id))
    db.commit()


def test_api_admin_acces_par_role(client):
    with SessionLocal() as db:
        _staff(db, Role.ADMIN, "admin")
        _staff(db, Role.SAGE_FEMME, "sf", _midwife(db).id)
        _record(db, S.ENREGISTRE)
        db.commit()

    for method, url, kw in (("post", "/api/admin/reseau", {"json": {"en_ligne": False}}),
                            ("get", "/api/tableau", {})):
        call = getattr(client, method)
        assert call(url, **kw).status_code == 401
        assert call(url, headers={"X-API-Key": "sf"}, **kw).status_code == 403
        assert call(url, headers={"X-API-Key": "admin"}, **kw).status_code == 200

    board = client.get("/api/tableau", headers={"X-API-Key": "admin"}).json()
    assert board["reseau_central"] == "off"
    assert board["par_etat"]["ENREGISTRE"] == 1 and board["par_etat"]["SYNCHRONISE"] == 0
    assert set(board["par_etat"]) == {s.value for s in RecordStatus}

    r = client.post("/api/admin/reseau", json={"en_ligne": True}, headers={"X-API-Key": "admin"})
    assert r.json() == {"reseau_central": "on"}
    run_maintenance_cycle()
    board = client.get("/api/tableau", headers={"X-API-Key": "admin"}).json()
    assert board["par_etat"]["SYNCHRONISE"] == 1
    assert board["derniers_evenements"][0]["vers"] == "SYNCHRONISE"
