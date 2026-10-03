"""Tests du bloc 1 : webhook, idempotence, multipage, hors ligne, chiffrement, accès."""
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.main import run_maintenance_cycle
from app.models import (AccessLog, InboundMessage, InboundStatus, Midwife, OutboundMessage, OutboundStatus,
                        Page, Record, RecordStatus, Role, Staff)
from app.registry_schema import sanitize_extraction
from app.security import hash_api_key
from app.storage import get_store
from tests.conftest import (MIDWIFE, button_msg, image_msg, post_webhook, text_msg, wa_payload)

NOW = int(time.time())
JPEG = b"\xff\xd8\xff\xe0" + b"fake-registre-page-1" * 50
JPEG2 = b"\xff\xd8\xff\xe0" + b"fake-registre-page-2" * 50


# ------------------------------------------------------------------ webhook
def test_verification_meta(client):
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                        "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "faux",
                                         "hub.challenge": "42"})
    assert bad.status_code == 403


def test_signature_obligatoire(client, fake_wa):
    r = post_webhook(client, wa_payload(text_msg("w1", "bonjour", NOW)), signed=False)
    assert r.status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(InboundMessage)) is None


def test_statuts_de_livraison_ignores(client, fake_wa):
    payload = {"entry": [{"changes": [{"field": "messages", "value": {"statuses": [{"id": "x"}]}}]}]}
    assert post_webhook(client, payload).json()["new"] == 0


# ------------------------------------------------------------------ capture multipage
def test_capture_multipage_puis_fin(client, fake_wa):
    fake_wa.media = {"m1": JPEG, "m2": JPEG2}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW, caption="Fatima Zahra 0612345678")))
    post_webhook(client, wa_payload(image_msg("w2", "m2", NOW + 30)))

    with SessionLocal() as db:
        rec = db.scalar(select(Record))
        assert rec.status == RecordStatus.CAPTURE and rec.session_open
        assert [p.page_number for p in rec.pages] == [1, 2]
        # la légende (identifiants) n'est stockée nulle part
        assert all(m.text is None for m in db.scalars(select(InboundMessage)))

    post_webhook(client, wa_payload(button_msg("w3", "CMD_FIN", NOW + 60)))
    with SessionLocal() as db:
        rec = db.scalar(select(Record))
        assert rec.status == RecordStatus.EN_ATTENTE_IA and not rec.session_open
        assert [e.to_status for e in rec.events] == ["CAPTURE", "EN_ATTENTE_IA"]
    # 3 réponses : page 1, page 2, confirmation FIN
    assert len(fake_wa.sent) == 3
    assert fake_wa.sent[0]["interactive"]["action"]["buttons"][0]["reply"]["id"] == "CMD_FIN"


def test_nouvelle_session_si_delai_depasse(client, fake_wa):
    fake_wa.media = {"m1": JPEG, "m2": JPEG2}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    post_webhook(client, wa_payload(image_msg("w2", "m2", NOW + 3600)))
    with SessionLocal() as db:
        assert len(db.scalars(select(Record)).all()) == 2


def test_messages_hors_ligne_arrives_en_rafale(client, fake_wa):
    """Photos prises hors ligne à 2 min d'intervalle, livrées d'un coup au retour du réseau."""
    fake_wa.media = {"m1": JPEG, "m2": JPEG2}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW - 7200), image_msg("w2", "m2", NOW - 7080)))
    with SessionLocal() as db:
        rec = db.scalar(select(Record))
        assert len(rec.pages) == 2
        assert int(rec.pages[0].captured_at.timestamp()) == NOW - 7200   # heure de prise conservée


# ------------------------------------------------------------------ idempotence / doublons
def test_meme_message_livre_deux_fois(client, fake_wa):
    fake_wa.media = {"m1": JPEG}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    r = post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    assert r.json()["new"] == 0
    with SessionLocal() as db:
        assert len(db.scalars(select(Page)).all()) == 1


def test_meme_photo_renvoyee(client, fake_wa):
    fake_wa.media = {"m1": JPEG, "m1bis": JPEG}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    post_webhook(client, wa_payload(image_msg("w2", "m1bis", NOW + 10)))
    with SessionLocal() as db:
        assert len(db.scalars(select(Page)).all()) == 1
    assert "déjà été reçue" in fake_wa.sent[-1]["text"]["body"]


# ------------------------------------------------------------------ robustesse réseau
def test_echec_telechargement_puis_rattrapage(client, fake_wa):
    fake_wa.media = {"m1": JPEG}
    fake_wa.online = False
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    with SessionLocal() as db:
        msg = db.scalar(select(InboundMessage))
        assert msg.status == InboundStatus.ECHEC and msg.attempts == 1
        assert db.scalar(select(Page)) is None

    fake_wa.online = True
    run_maintenance_cycle()
    with SessionLocal() as db:
        assert db.scalar(select(InboundMessage)).status == InboundStatus.TRAITE
        assert db.scalar(select(Page)) is not None
        assert db.scalar(select(OutboundMessage)).status == OutboundStatus.ENVOYE


def test_outbox_conserve_les_reponses_si_envoi_echoue(client, fake_wa, monkeypatch):
    fake_wa.media = {"m1": JPEG}
    real_send = fake_wa.send

    def send_fail(*a):
        raise RuntimeError("réseau coupé")

    monkeypatch.setattr(fake_wa, "send", send_fail)
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    with SessionLocal() as db:
        assert db.scalar(select(OutboundMessage)).status == OutboundStatus.EN_ATTENTE

    monkeypatch.setattr(fake_wa, "send", real_send)
    run_maintenance_cycle()
    with SessionLocal() as db:
        assert db.scalar(select(OutboundMessage)).status == OutboundStatus.ENVOYE


# ------------------------------------------------------------------ stockage / accès
def test_image_chiffree_sur_disque(client, fake_wa):
    fake_wa.media = {"m1": JPEG}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    with SessionLocal() as db:
        page = db.scalar(select(Page))
    store = get_store()
    on_disk = (store.root / page.storage_key).read_bytes()
    assert JPEG not in on_disk and b"fake-registre" not in on_disk
    assert store.load(page.storage_key) == JPEG


def _staff(db, role, midwife_id=None, key="k"):
    db.add(Staff(label=key, role=role, api_key_hash=hash_api_key(key), midwife_id=midwife_id))
    db.commit()


def test_acces_image_selon_role(client, fake_wa):
    fake_wa.media = {"m1": JPEG}
    post_webhook(client, wa_payload(image_msg("w1", "m1", NOW)))
    with SessionLocal() as db:
        rec = db.scalar(select(Record))
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE))
        other = Midwife(wa_id="212600000999")
        db.add(other)
        db.flush()
        _staff(db, Role.SAGE_FEMME, mw.id, key="sf-proprio")
        _staff(db, Role.SAGE_FEMME, other.id, key="sf-autre")
        _staff(db, Role.SUPERVISEUR, key="sup")

    url = f"/api/records/{rec.id}/pages/1/image"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-API-Key": "faux"}).status_code == 401
    assert client.get(url, headers={"X-API-Key": "sf-autre"}).status_code == 403
    r = client.get(url, headers={"X-API-Key": "sf-proprio"})
    assert r.status_code == 200 and r.content == JPEG and r.headers["cache-control"] == "no-store"
    assert client.get(url, headers={"X-API-Key": "sup"}).status_code == 200
    with SessionLocal() as db:
        logs = db.scalars(select(AccessLog)).all()
        assert [l.allowed for l in logs] == [False, True, True]


# ------------------------------------------------------------------ anonymisation
def test_liste_blanche_du_schema():
    kept, rejected = sanitize_extraction({
        "profil.age": 27, "grossesse_en_cours.ta_systolique": 120,
        "profil.nom": "X", "identification.telephone": "06", "nom_conjoint": "Y", "champ_invente": 1,
    })
    assert set(kept) == {"profil.age", "grossesse_en_cours.ta_systolique"}
    assert len(rejected) == 4
