"""Machine à états du cycle de vie d'un dossier (bloc 2).

Tout changement de `Record.status` passe par `transition()` : la table TRANSITIONS
dit quels passages sont permis, les gardes vérifient les conditions métier, et
chaque passage est tracé dans `RecordEvent`. Aucun commit ici : l'appelant décide.
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExtractedField, FieldStatus, Record, RecordEvent, RecordStatus

S = RecordStatus
MAX_AI_ATTEMPTS = 3

TRANSITIONS: dict[RecordStatus | None, set[RecordStatus]] = {
    None: {S.CAPTURE},                                   # création d'un dossier
    S.CAPTURE: {S.EN_ATTENTE_IA, S.ANNULE},
    S.EN_ATTENTE_IA: {S.TRAITE_IA, S.ECHEC_TRAITEMENT, S.ANNULE},
    S.ECHEC_TRAITEMENT: {S.EN_ATTENTE_IA, S.REVISION_MANUELLE_REQUISE},
    S.TRAITE_IA: {S.A_REVISER},
    S.A_REVISER: {S.VALIDE, S.EN_ATTENTE_IA, S.REVISION_MANUELLE_REQUISE, S.ANNULE},
    S.REVISION_MANUELLE_REQUISE: {S.VALIDE, S.ANNULE},
    S.VALIDE: {S.PATIENTE_LIEE, S.DOUBLON_SUSPECT},
    S.DOUBLON_SUSPECT: {S.PATIENTE_LIEE, S.ANNULE},
    S.PATIENTE_LIEE: {S.ENREGISTRE},
    S.ENREGISTRE: {S.SYNCHRONISE, S.ECHEC_SYNCHRO},
    S.ECHEC_SYNCHRO: {S.SYNCHRONISE},
    S.SYNCHRONISE: set(),                                # états finaux
    S.ANNULE: set(),
}

FAILURE_STATES = {S.ECHEC_TRAITEMENT, S.ECHEC_SYNCHRO, S.DOUBLON_SUSPECT, S.REVISION_MANUELLE_REQUISE}
# champs qui empêchent la validation tant que la sage-femme ne les a pas tranchés
BLOCKING_FIELD_STATUSES = {FieldStatus.A_REVISER, FieldStatus.ILLISIBLE}


class InvalidTransition(Exception):
    pass


def allowed_next(status: RecordStatus | None) -> set[RecordStatus]:
    return set(TRANSITIONS.get(status, set()))


def _name(status: RecordStatus | None) -> str:
    return status.value if status else "(création)"


def _check_guards(record: Record, frm: RecordStatus | None, to: RecordStatus, actor: str):
    def refuse(why: str):
        raise InvalidTransition(f"{_name(frm)} -> {to.value} interdit : {why}")

    if to == S.EN_ATTENTE_IA and frm == S.CAPTURE and not record.pages:
        refuse("le dossier n'a aucune page")
    if to == S.VALIDE:
        if not actor.startswith("midwife:"):
            refuse(f"seule la sage-femme peut valider (acteur « {actor} »)")
        pending = sorted(f"{f.section}.{f.field_key}" for f in record.fields
                         if f.is_current and f.status in BLOCKING_FIELD_STATUSES)
        if pending:
            refuse(f"champ(s) encore à réviser ou illisibles : {', '.join(pending)}")
    if to == S.PATIENTE_LIEE and not record.patient_id:
        refuse("aucune patiente rattachée (patient_id vide)")
    if to == S.REVISION_MANUELLE_REQUISE and frm == S.ECHEC_TRAITEMENT and (record.ai_attempts or 0) < MAX_AI_ATTEMPTS:
        refuse(f"{record.ai_attempts or 0}/{MAX_AI_ATTEMPTS} tentatives IA seulement")


def transition(db: Session, record: Record, to_status: RecordStatus, actor: str,
               note: str | None = None, reason: str | None = None) -> RecordEvent:
    """Change l'état du dossier si la table et les gardes l'autorisent, sinon lève InvalidTransition."""
    frm = record.status
    if to_status not in TRANSITIONS.get(frm, set()):
        raise InvalidTransition(f"{_name(frm)} -> {to_status.value} interdit")
    _check_guards(record, frm, to_status, actor)

    record.status = to_status
    record.failure_reason = (reason or note) if to_status in FAILURE_STATES else None
    event = RecordEvent(record=record, from_status=frm.value if frm else None, to_status=to_status.value,
                        actor=actor, note=note or reason)
    db.add(event)
    return event


def _current_value(record: Record, section: str, key: str) -> str | None:
    for f in record.fields:
        if f.is_current and f.section == section and f.field_key == key:
            return f.value_json
    return None


def find_duplicate(db: Session, record: Record, patient_id: str) -> Record | None:
    """Autre dossier déjà enregistré de la même patiente pour la même date de visite."""
    visit_date = _current_value(record, "identification", "date_visite")
    if visit_date is None or json.loads(visit_date) in (None, ""):
        return None
    db.flush()
    return db.scalar(
        select(Record).join(ExtractedField)
        .where(Record.patient_id == patient_id, Record.id != record.id,
               Record.status.in_([S.ENREGISTRE, S.SYNCHRONISE]),
               ExtractedField.is_current.is_(True), ExtractedField.section == "identification",
               ExtractedField.field_key == "date_visite", ExtractedField.value_json == visit_date)
        .limit(1))
