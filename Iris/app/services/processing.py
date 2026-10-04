"""Reprise des dossiers dont la lecture IA a échoué.

L'appel à l'IA locale arrive au bloc 3 : ici, on ne fait que remettre en file
(EN_ATTENTE_IA) ou, après MAX_AI_ATTEMPTS échecs, passer en révision manuelle.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Midwife, Record, RecordStatus
from app.services import outbox
from app.state_machine import MAX_AI_ATTEMPTS, transition
from app.whatsapp import text_message


RETRY_BASE_SECONDS = 60          # attente croissante : 1 min, 2 min, 4 min... (Ollama surchargé, PC chaud)


def retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=RETRY_BASE_SECONDS * 2 ** max(0, (attempts or 1) - 1))


def retry_failed_processing(db: Session) -> int:
    failed = db.scalars(select(Record).where(Record.status == RecordStatus.ECHEC_TRAITEMENT)).all()
    now = datetime.now(timezone.utc)
    for rec in failed:
        last = rec.updated_at if rec.updated_at.tzinfo else rec.updated_at.replace(tzinfo=timezone.utc)
        if rec.ai_attempts < MAX_AI_ATTEMPTS and now - last < retry_delay(rec.ai_attempts):
            continue                                   # pas encore : on laisse respirer la machine
        if rec.ai_attempts < MAX_AI_ATTEMPTS:
            transition(db, rec, RecordStatus.EN_ATTENTE_IA, "system",
                       f"nouvelle tentative ({rec.ai_attempts}/{MAX_AI_ATTEMPTS})")
        else:
            transition(db, rec, RecordStatus.REVISION_MANUELLE_REQUISE, "system",
                       reason=f"lecture automatique impossible après {rec.ai_attempts} tentatives")
            mw = db.get(Midwife, rec.midwife_id)
            from app.i18n import t
            outbox.enqueue(db, text_message(mw.wa_id, t(mw.language, "manual_needed", rid=rec.id[:8])))
            from app.services import conversation
            conversation.on_manual_required(db, rec)          # saisie guidée (bloc 4)
    db.commit()
    return len(failed)
