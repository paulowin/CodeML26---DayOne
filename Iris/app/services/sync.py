"""Synchronisation vers un serveur central SIMULÉ (démo hors ligne).

Le « serveur du ministère » est la table CentralRecord ; le drapeau système
"reseau_central" ("on" / "off") simule la coupure du réseau. Seules des données
anonymisées partent : ni image, ni wa_id de la sage-femme.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CentralRecord, Record, RecordStatus, SystemFlag
from app.state_machine import transition

log = logging.getLogger(__name__)
NETWORK_FLAG = "reseau_central"


def get_flag(db: Session, key: str, default: str) -> str:
    flag = db.get(SystemFlag, key)
    return flag.value if flag else default


def set_flag(db: Session, key: str, value: str) -> None:
    flag = db.get(SystemFlag, key)
    if flag:
        flag.value = value
    else:
        db.add(SystemFlag(key=key, value=value))


def network_online(db: Session) -> bool:
    return get_flag(db, NETWORK_FLAG, "on") == "on"


def build_payload(record: Record) -> dict:
    """Dossier anonymisé : identifiants internes (UUID) + champs courants uniquement."""
    return {
        "record_id": record.id,
        "patient_id": record.patient_id,
        "captured_at": record.first_captured_at.isoformat(),
        "fields": [{"key": f"{f.section}.{f.field_key}",
                    "value": json.loads(f.value_json) if f.value_json else None,
                    "status": f.status.value, "confidence": f.confidence, "source": f.source.value}
                   for f in record.fields if f.is_current],
    }


def push(db: Session, record: Record) -> None:
    """Envoie le dossier au serveur central ; ConnectionError si le réseau est coupé."""
    if not network_online(db):
        raise ConnectionError("réseau central coupé")
    payload = json.dumps(build_payload(record), ensure_ascii=False, default=str)
    central = db.get(CentralRecord, record.id)
    if central:                      # renvoi : on remplace, jamais de doublon
        central.payload_json = payload
    else:
        db.add(CentralRecord(record_id=record.id, payload_json=payload))


def sync_pending(db: Session) -> int:
    """Pousse les dossiers ENREGISTRE / ECHEC_SYNCHRO ; renvoie le nombre synchronisés."""
    pending = db.scalars(select(Record).where(Record.status.in_([RecordStatus.ENREGISTRE,
                                                                 RecordStatus.ECHEC_SYNCHRO]))
                         .order_by(Record.created_at)).all()
    synced = 0
    for rec in pending:
        try:
            push(db, rec)
        except ConnectionError as e:
            if rec.status == RecordStatus.ENREGISTRE:
                transition(db, rec, RecordStatus.ECHEC_SYNCHRO, "system", reason=str(e))
            else:                    # déjà en échec : on garde l'état, on réessaiera au prochain cycle
                rec.failure_reason = str(e)
            continue
        transition(db, rec, RecordStatus.SYNCHRONISE, "system", "envoyé au serveur central")
        rec.synced_at = datetime.now(timezone.utc)
        synced += 1
    db.commit()
    if pending:
        log.info("Synchronisation : %s/%s dossier(s) envoyé(s)", synced, len(pending))
    return synced
