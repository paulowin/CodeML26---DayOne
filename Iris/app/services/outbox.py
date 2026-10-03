"""Outbox : tout message sortant est d'abord persisté, puis envoyé.
Si le réseau tombe, le worker renvoie plus tard -> aucun message perdu."""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboundMessage, OutboundStatus
from app.whatsapp import WhatsAppClient, WhatsAppError

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 8


def enqueue(db: Session, payload: dict) -> OutboundMessage:
    msg = OutboundMessage(to_wa_id=payload["to"], payload_json=json.dumps(payload, ensure_ascii=False))
    db.add(msg)
    db.flush()
    return msg


def try_send(db: Session, msg: OutboundMessage, client: WhatsAppClient | None = None) -> bool:
    client = client or WhatsAppClient()
    msg.attempts += 1
    try:
        msg.wa_message_id = client.send(json.loads(msg.payload_json))
        msg.status, msg.sent_at, msg.last_error = OutboundStatus.ENVOYE, datetime.now(timezone.utc), None
        return True
    except (WhatsAppError, OSError, Exception) as e:  # httpx.ConnectError hérite d'Exception
        msg.last_error = str(e)[:500]
        if msg.attempts >= MAX_ATTEMPTS:
            msg.status = OutboundStatus.ECHEC
        log.warning("Envoi WhatsApp échoué (tentative %s) : %s", msg.attempts, e)
        return False


def flush_pending(db: Session, client: WhatsAppClient | None = None, limit: int = 50) -> int:
    """Envoie les messages en attente dans l'ordre de création. Retourne le nb envoyé."""
    pending = db.scalars(select(OutboundMessage)
                         .where(OutboundMessage.status == OutboundStatus.EN_ATTENTE)
                         .order_by(OutboundMessage.id).limit(limit)).all()
    sent = 0
    for msg in pending:
        ok = try_send(db, msg, client)
        db.commit()
        if not ok:
            break          # réseau probablement coupé : on garde l'ordre, on réessaiera
        sent += 1
    return sent
