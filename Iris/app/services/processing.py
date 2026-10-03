"""Reprise des dossiers dont la lecture IA a échoué.

L'appel à l'IA locale arrive au bloc 3 : ici, on ne fait que remettre en file
(EN_ATTENTE_IA) ou, après MAX_AI_ATTEMPTS échecs, passer en révision manuelle.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Midwife, Record, RecordStatus
from app.services import outbox
from app.state_machine import MAX_AI_ATTEMPTS, transition
from app.whatsapp import text_message


def retry_failed_processing(db: Session) -> int:
    failed = db.scalars(select(Record).where(Record.status == RecordStatus.ECHEC_TRAITEMENT)).all()
    for rec in failed:
        if rec.ai_attempts < MAX_AI_ATTEMPTS:
            transition(db, rec, RecordStatus.EN_ATTENTE_IA, "system",
                       f"nouvelle tentative ({rec.ai_attempts}/{MAX_AI_ATTEMPTS})")
        else:
            transition(db, rec, RecordStatus.REVISION_MANUELLE_REQUISE, "system",
                       reason=f"lecture automatique impossible après {rec.ai_attempts} tentatives")
            mw = db.get(Midwife, rec.midwife_id)
            outbox.enqueue(db, text_message(mw.wa_id, f"Je n'arrive pas à lire le dossier {rec.id[:8]} "
                                                      "automatiquement. Nous allons le saisir ensemble."))
    db.commit()
    return len(failed)
