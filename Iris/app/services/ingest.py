"""Réception des messages WhatsApp : parsing, persistance idempotente, traitement.

Flux : webhook -> persist_inbound() (rapide, 200 OK à Meta) -> process_inbound()
(en tâche de fond, puis rattrapage par le worker si échec ou serveur redémarré).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import InboundMessage, InboundStatus, Midwife, Page, Record, RecordStatus
from app.i18n import plural, t
from app.services import conversation, outbox
from app.state_machine import transition
from app.storage import get_store
from app.whatsapp import WhatsAppClient, get_client, buttons_message, text_message

log = logging.getLogger(__name__)
MAX_INBOUND_ATTEMPTS = 5
ACCEPTED_MIME = {"image/jpeg", "image/png", "image/webp"}
CMD_FIN = {"FIN", "TERMINER", "TERMINE", "DONE", "END", "CMD_FIN"}
CMD_ANNULER = {"ANNULER", "CANCEL", "CMD_ANNULER"}


def _utc(dt: datetime) -> datetime:
    """SQLite renvoie des datetimes naïfs : on les ramène en UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ parsing
def parse_webhook(payload: dict) -> list[dict]:
    """Extrait les messages utiles du payload Meta. Ignore statuts de livraison,
    nom de profil et légendes (risque d'identifiants)."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for m in change.get("value", {}).get("messages", []) or []:
                mtype = m.get("type")
                item = {"wa_message_id": m["id"], "wa_from": m["from"], "msg_type": mtype,
                        "wa_timestamp": datetime.fromtimestamp(int(m["timestamp"]), tz=timezone.utc),
                        "media_id": None, "mime_type": None, "text": None}
                if mtype == "image":
                    item["media_id"] = m["image"]["id"]
                    item["mime_type"] = m["image"].get("mime_type")
                elif mtype == "document" and str(m["document"].get("mime_type", "")).startswith("image/"):
                    # photo envoyée "en document" (qualité non compressée) : on l'accepte
                    item["msg_type"] = "image"
                    item["media_id"] = m["document"]["id"]
                    item["mime_type"] = m["document"]["mime_type"]
                elif mtype == "text":
                    item["text"] = m["text"]["body"]
                elif mtype == "interactive":
                    inter = m["interactive"]
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    item["text"] = reply.get("id")
                elif mtype == "button":  # réponse à un template
                    item["text"] = m["button"].get("payload") or m["button"].get("text")
                out.append(item)
    return out


def persist_inbound(db: Session, items: list[dict]) -> list[int]:
    """Insère les nouveaux messages ; ignore les doublons (Meta re-livre parfois)."""
    new_ids = []
    for it in items:
        if db.scalar(select(InboundMessage.id).where(InboundMessage.wa_message_id == it["wa_message_id"])):
            continue
        msg = InboundMessage(**it)
        db.add(msg)
        try:
            db.commit()
            new_ids.append(msg.id)
        except IntegrityError:          # course entre deux livraisons simultanées
            db.rollback()
    return new_ids


# ------------------------------------------------------------------ helpers
def get_or_create_midwife(db: Session, wa_id: str) -> Midwife:
    mw = db.scalar(select(Midwife).where(Midwife.wa_id == wa_id))
    if not mw:
        mw = Midwife(wa_id=wa_id)
        db.add(mw)
        db.flush()
    return mw


def _lang(db: Session, wa_id: str) -> str:
    mw = db.scalar(select(Midwife).where(Midwife.wa_id == wa_id))
    return mw.language if mw else "fr"


SECONDS_PER_PAGE = 40          # lecture OCR + 2e avis, mesuré (eval/reports/3d_comparaison.md)


def reading_message(lang: str, key: str, record: Record) -> str:
    """« ⏳ Je lis votre registre… (environ 1 minute) »."""
    n = len(record.pages)
    minutes = max(1, -(-n * SECONDS_PER_PAGE // 60))
    return t(lang, key, rid=record.id[:8], pages=plural(lang, n, "pl_page"),
             duration=plural(lang, minutes, "pl_minute"))


def _reply(db: Session, payload: dict):
    outbox.enqueue(db, payload)


def _open_session(db: Session, midwife: Midwife, at: datetime) -> Record | None:
    window = timedelta(seconds=get_settings().session_window_seconds)
    rec = db.scalar(select(Record).where(Record.midwife_id == midwife.id, Record.session_open.is_(True),
                                         Record.status == RecordStatus.CAPTURE)
                    .order_by(Record.last_page_at.desc()))
    if rec and abs(at - _utc(rec.last_page_at)) <= window:
        return rec
    return None


def close_session(db: Session, record: Record, actor: str):
    record.session_open = False
    transition(db, record, RecordStatus.EN_ATTENTE_IA, actor, f"{len(record.pages)} page(s)")


# ------------------------------------------------------------------ traitement
STALE_CLAIM = timedelta(minutes=2)


def claim_inbound(db: Session, inbound_id: int) -> bool:
    """Réserve le message pour CE traitement (tâche de fond du webhook OU worker) : un seul gagnant.
    Sans cela, une photo (2 s de téléchargement) était traitée deux fois -> deux réponses."""
    res = db.execute(update(InboundMessage)
                     .where(InboundMessage.id == inbound_id,
                            InboundMessage.status.in_([InboundStatus.RECU, InboundStatus.ECHEC]))
                     .values(status=InboundStatus.EN_COURS, claimed_at=datetime.now(timezone.utc)))
    db.commit()
    return res.rowcount == 1


def process_inbound(db: Session, inbound_id: int, client: WhatsAppClient | None = None) -> None:
    if not claim_inbound(db, inbound_id):
        log.info("Entrant #%s déjà traité ou en cours : ignoré (pas de double traitement)", inbound_id)
        return
    msg = db.get(InboundMessage, inbound_id, populate_existing=True)
    log.info("Traitement de l'entrant #%s (%s, wamid …%s)", msg.id, msg.msg_type, msg.wa_message_id[-12:])
    try:
        midwife = get_or_create_midwife(db, msg.wa_from)
        if msg.msg_type == "image":
            _handle_image(db, msg, midwife, client or get_client())
        elif msg.msg_type in ("text", "interactive", "button"):
            _handle_text(db, msg, midwife)
        else:
            _reply(db, text_message(msg.wa_from, t(midwife.language, "only_photos")))
            msg.status = InboundStatus.IGNORE
        msg.attempts += 1
        if msg.status != InboundStatus.IGNORE:
            msg.status = InboundStatus.TRAITE
        msg.processed_at = datetime.now(timezone.utc)
        msg.last_error = None
        db.commit()
    except Exception as e:  # on ne perd rien : ECHEC -> retenté par le worker
        db.rollback()
        msg = db.get(InboundMessage, inbound_id, populate_existing=True)
        msg.attempts += 1              # l'incrément précédent a été annulé par le rollback
        msg.status = InboundStatus.ECHEC
        msg.last_error = f"{type(e).__name__}: {e}"[:500]
        if msg.attempts >= MAX_INBOUND_ATTEMPTS and msg.msg_type == "image":
            msg.status = InboundStatus.IGNORE
            _reply(db, text_message(msg.wa_from, t(_lang(db, msg.wa_from), "photo_lost")))
        db.commit()
        log.exception("Traitement du message %s échoué", inbound_id)


def _handle_image(db: Session, msg: InboundMessage, midwife: Midwife, client: WhatsAppClient):
    data, mime = client.download_media(msg.media_id)
    mime = (msg.mime_type or mime or "").split(";")[0].strip()
    if mime not in ACCEPTED_MIME:
        _reply(db, text_message(msg.wa_from, t(midwife.language, "bad_format", mime=mime or "?")))
        msg.status = InboundStatus.IGNORE
        return

    store = get_store()
    storage_key, digest = store.save(data)

    # Doublon exact : même image déjà reçue de cette sage-femme
    dup = db.scalar(select(Page).join(Record).where(Page.sha256 == digest, Record.midwife_id == midwife.id))
    if dup:
        (store.root / storage_key).unlink(missing_ok=True)
        _reply(db, text_message(msg.wa_from, t(midwife.language, "photo_dup", rid=dup.record_id[:8],
                                               n=dup.page_number)))
        msg.status = InboundStatus.IGNORE
        return

    at = _utc(msg.wa_timestamp)
    if conversation.awaiting_photo(midwife):            # « Reprendre la photo » (bloc 4)
        rec = conversation.attach_replacement_photo(db, midwife, dict(
            storage_key=storage_key, sha256=digest, mime_type=mime, size_bytes=len(data),
            wa_message_id=msg.wa_message_id, captured_at=at))
        if rec is not None:
            return
    record = _open_session(db, midwife, at)
    if record is None:
        record = Record(midwife_id=midwife.id, first_captured_at=at, last_page_at=at)
        db.add(record)
        # status encore vide avant le flush : c'est la transition de création -> CAPTURE
        transition(db, record, RecordStatus.CAPTURE, f"midwife:{midwife.id}", "nouvelle session de capture")
        db.flush()

    page_no = len(record.pages) + 1
    record.pages.append(Page(page_number=page_no, storage_key=storage_key, sha256=digest, mime_type=mime,
                             size_bytes=len(data), wa_message_id=msg.wa_message_id, captured_at=at))
    record.last_page_at = max(_utc(record.last_page_at), at)
    db.flush()

    lang = midwife.language
    _reply(db, buttons_message(msg.wa_from, t(lang, "page_received", n=page_no, rid=record.id[:8]),
                               [("CMD_FIN", t(lang, "btn_done")), ("CMD_ANNULER", t(lang, "btn_cancel"))]))


def _handle_text(db: Session, msg: InboundMessage, midwife: Midwife):
    cmd = (msg.text or "").strip().upper()
    record = db.scalar(select(Record).where(Record.midwife_id == midwife.id, Record.session_open.is_(True),
                                            Record.status == RecordStatus.CAPTURE)
                       .order_by(Record.last_page_at.desc()))
    if cmd in CMD_FIN:
        if not record:
            _reply(db, text_message(msg.wa_from, t(midwife.language, "no_capture")))
            return
        close_session(db, record, f"midwife:{midwife.id}")
        _reply(db, text_message(msg.wa_from, reading_message(midwife.language, "reading", record)))
    elif cmd in CMD_ANNULER:
        if record:
            record.session_open = False
            transition(db, record, RecordStatus.ANNULE, f"midwife:{midwife.id}", "annulé par la sage-femme")
        _reply(db, text_message(msg.wa_from, t(midwife.language, "capture_cancelled")))
    elif not conversation.handle_text(db, midwife, msg.text or ""):
        _reply(db, text_message(msg.wa_from, t(midwife.language, "welcome")))


def auto_close_stale_sessions(db: Session) -> int:
    """Ferme les sessions sans nouvelle page depuis N s (heure serveur)."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=get_settings().session_window_seconds)
    stale = db.scalars(select(Record).where(Record.session_open.is_(True), Record.status == RecordStatus.CAPTURE,
                                            Record.updated_at < cutoff)).all()
    for rec in stale:
        close_session(db, rec, "system")
        mw = db.get(Midwife, rec.midwife_id)
        _reply(db, text_message(mw.wa_id, reading_message(mw.language, "auto_closed", rec)))
    db.commit()
    return len(stale)


def retry_failed_inbound(db: Session, client: WhatsAppClient | None = None) -> int:
    # un traitement tué en plein milieu (redémarrage) libère sa réservation après 2 min
    stale = db.execute(update(InboundMessage)
                       .where(InboundMessage.status == InboundStatus.EN_COURS,
                              InboundMessage.claimed_at < datetime.now(timezone.utc) - STALE_CLAIM)
                       .values(status=InboundStatus.ECHEC, last_error="réservation expirée"))
    db.commit()
    if stale.rowcount:
        log.warning("%d entrant(s) bloqué(s) en EN_COURS remis en échec pour reprise", stale.rowcount)
    ids = db.scalars(select(InboundMessage.id).where(InboundMessage.status.in_([InboundStatus.RECU, InboundStatus.ECHEC]))
                     .order_by(InboundMessage.wa_timestamp, InboundMessage.id)).all()
    for i in ids:
        process_inbound(db, i, client)
    return len(ids)
