"""Outbox : tout message sortant est d'abord persisté, puis envoyé.
Si le réseau tombe, le worker renvoie plus tard -> aucun message perdu.

Anti double envoi : la tâche de fond du webhook ET le worker (20 s) appellent tous deux
`flush_pending`. Chaque message est RÉSERVÉ de façon atomique avant l'envoi
(UPDATE ... SET status='ENVOI_EN_COURS' WHERE status='EN_ATTENTE' : un seul gagnant) et
un verrou de processus sérialise les vidages. Un message resté ENVOI_EN_COURS plus de
2 min (processus tué en plein envoi) repasse EN_ATTENTE.
"""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import OutboundMessage, OutboundStatus
from app.whatsapp import WhatsAppClient, get_client, WhatsAppError

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 8
STALE_CLAIM = timedelta(minutes=2)
_flush_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim(db: Session, msg_id: int) -> bool:
    """Réserve le message pour CET envoi ; False si un autre appel l'a déjà pris."""
    res = db.execute(update(OutboundMessage)
                     .where(OutboundMessage.id == msg_id, OutboundMessage.status == OutboundStatus.EN_ATTENTE)
                     .values(status=OutboundStatus.ENVOI_EN_COURS, claimed_at=_now()))
    db.commit()
    return res.rowcount == 1


def release_stale(db: Session) -> int:
    res = db.execute(update(OutboundMessage)
                     .where(OutboundMessage.status == OutboundStatus.ENVOI_EN_COURS,
                            OutboundMessage.claimed_at < _now() - STALE_CLAIM)
                     .values(status=OutboundStatus.EN_ATTENTE))
    db.commit()
    if res.rowcount:
        log.warning("Outbox : %d message(s) bloqué(s) en ENVOI_EN_COURS remis en attente", res.rowcount)
    return res.rowcount


def enqueue(db: Session, payload: dict) -> OutboundMessage:
    msg = OutboundMessage(to_wa_id=payload["to"], payload_json=json.dumps(payload, ensure_ascii=False))
    db.add(msg)
    db.flush()
    return msg


def try_send(db: Session, msg: OutboundMessage, client: WhatsAppClient | None = None) -> bool | None:
    """True = envoyé ; False = erreur temporaire (réseau) ; None = erreur définitive."""
    client = client or get_client()
    msg.attempts += 1
    try:
        payload = json.loads(msg.payload_json)
        spec = payload.pop("_preview", None)
        if spec is not None:                     # aperçu : image fabriquée en mémoire, puis téléversée
            from app.services import preview
            data = preview.build(db, spec)
            if data is None:
                msg.status, msg.last_error = OutboundStatus.ECHEC, "aperçu indisponible (page absente)"
                return None
            payload["image"]["id"] = client.upload_media(data, "image/jpeg")
        msg.wa_message_id = client.send(payload)
        msg.status, msg.sent_at, msg.last_error = OutboundStatus.ENVOYE, datetime.now(timezone.utc), None
        log.info("Outbox #%s envoyé -> %s", msg.id, msg.wa_message_id)
        return True
    except WhatsAppError as e:
        msg.last_error = str(e)[:500]
        if e.permanent:
            msg.status = OutboundStatus.ECHEC
            log.error("Envoi WhatsApp refusé définitivement (vérifier jeton / Phone Number ID) : %s", e)
            return None
        msg.status = OutboundStatus.ECHEC if msg.attempts >= MAX_ATTEMPTS else OutboundStatus.EN_ATTENTE
        log.warning("Outbox #%s : envoi échoué (tentative %s) : %s", msg.id, msg.attempts, e)
        return False
    except Exception as e:  # réseau coupé, DNS, timeout...
        msg.last_error = f"{type(e).__name__}: {e}"[:500]
        msg.status = OutboundStatus.ECHEC if msg.attempts >= MAX_ATTEMPTS else OutboundStatus.EN_ATTENTE
        log.warning("Outbox #%s : envoi échoué (tentative %s) : %s", msg.id, msg.attempts, e)
        return False


def flush_pending(db: Session, client: WhatsAppClient | None = None, limit: int = 50) -> int:
    """Envoie les messages en attente dans l'ordre. Une erreur réseau arrête la boucle
    (on réessaiera) ; une erreur définitive ne bloque pas les messages suivants."""
    with _flush_lock:
        release_stale(db)
        ids = db.scalars(select(OutboundMessage.id)
                         .where(OutboundMessage.status == OutboundStatus.EN_ATTENTE)
                         .order_by(OutboundMessage.id).limit(limit)).all()
        sent = 0
        for msg_id in ids:
            if not claim(db, msg_id):          # déjà pris par un autre processus
                log.info("Outbox #%s déjà réservé ailleurs : ignoré", msg_id)
                continue
            msg = db.get(OutboundMessage, msg_id, populate_existing=True)
            result = try_send(db, msg, client)
            db.commit()
            if result is False:
                break
            if result:
                sent += 1
        return sent
