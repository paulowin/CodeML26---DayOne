"""Anti doublons : la tâche de fond du webhook et le worker tournent en parallèle."""
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import InboundMessage, InboundStatus, OutboundMessage, OutboundStatus
from app.services import ingest, outbox
from app.whatsapp import text_message
from tests.conftest import MIDWIFE, body_of


def _parallel(fn, n=2):
    barrier = threading.Barrier(n)
    errors = []

    def run():
        try:
            barrier.wait()
            fn()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def test_flush_pending_depuis_deux_threads_un_seul_envoi_par_message(client, fake_wa, monkeypatch):
    with SessionLocal() as db:
        for i in range(6):
            outbox.enqueue(db, text_message(MIDWIFE, f"message {i}"))
        db.commit()
    slow_send = fake_wa.send

    def send(self, payload):
        time.sleep(0.02)                                     # élargit la fenêtre de course
        return slow_send(self, payload)
    from app.whatsapp import WhatsAppClient
    monkeypatch.setattr(WhatsAppClient, "send", send)

    def flush():
        with SessionLocal() as db:
            outbox.flush_pending(db)
    _parallel(flush)
    bodies = [body_of(p) for p in fake_wa.sent]
    assert sorted(bodies) == [f"message {i}" for i in range(6)]          # chacun exactement une fois
    with SessionLocal() as db:
        assert {m.status for m in db.scalars(select(OutboundMessage))} == {OutboundStatus.ENVOYE}


def test_reservation_atomique_un_seul_gagnant(client):
    with SessionLocal() as db:
        mid = outbox.enqueue(db, text_message(MIDWIFE, "x")).id
        db.commit()
    with SessionLocal() as a, SessionLocal() as b:
        assert outbox.claim(a, mid) is True
        assert outbox.claim(b, mid) is False


def test_reservation_bloquee_liberee_apres_2_min(client, fake_wa):
    with SessionLocal() as db:
        m = outbox.enqueue(db, text_message(MIDWIFE, "bloqué"))
        m.status, m.claimed_at = OutboundStatus.ENVOI_EN_COURS, datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
        assert outbox.flush_pending(db) == 1
    assert body_of(fake_wa.sent[-1]) == "bloqué"


def test_photo_traitee_une_seule_fois_meme_en_parallele(client, fake_wa, monkeypatch):
    """Reproduit le bug du test réel : « Page 1 reçue » puis « Cette photo a déjà été reçue »."""
    fake_wa.media["m1"] = b"\xff\xd8photo"
    real_download = fake_wa.download_media

    def slow_download(self, media_id):
        time.sleep(0.3)                                      # téléchargement d'une photo (~2 s en vrai)
        return real_download(self, media_id)
    from app.whatsapp import WhatsAppClient
    monkeypatch.setattr(WhatsAppClient, "download_media", slow_download)
    with SessionLocal() as db:
        [iid] = ingest.persist_inbound(db, [{
            "wa_message_id": "wamid.photo1", "wa_from": MIDWIFE, "msg_type": "image",
            "wa_timestamp": datetime.now(timezone.utc), "media_id": "m1", "mime_type": "image/jpeg", "text": None}])

    def process():                                           # tâche de fond ET worker en même temps
        with SessionLocal() as db:
            ingest.process_inbound(db, iid)
            outbox.flush_pending(db)
    _parallel(process)
    bodies = [body_of(p) for p in fake_wa.sent]
    assert len(bodies) == 1 and bodies[0].startswith("Page 1 reçue")
    with SessionLocal() as db:
        msg = db.get(InboundMessage, iid)
        assert msg.status == InboundStatus.TRAITE and msg.attempts == 1


def test_entrant_bloque_en_cours_repris_apres_2_min(client, fake_wa):
    with SessionLocal() as db:
        [iid] = ingest.persist_inbound(db, [{
            "wa_message_id": "wamid.txt1", "wa_from": MIDWIFE, "msg_type": "text",
            "wa_timestamp": datetime.now(timezone.utc), "media_id": None, "mime_type": None, "text": "AIDE"}])
        m = db.get(InboundMessage, iid)
        m.status, m.claimed_at = InboundStatus.EN_COURS, datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
        ingest.retry_failed_inbound(db)
        assert db.get(InboundMessage, iid, populate_existing=True).status == InboundStatus.TRAITE
