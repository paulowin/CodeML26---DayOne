"""Machine à états du cycle de vie d'un dossier (bloc 2).

Tout changement de `Record.status` passe par `transition()` : la table TRANSITIONS
dit quels passages sont permis, les gardes vérifient les conditions métier, et
chaque passage est tracé dans `RecordEvent`. Aucun commit ici : l'appelant décide.
"""
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FieldStatus, Record, RecordEvent, RecordStatus
from app.templates.normalize import parse_date

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


# Dates de référence d'un dossier, par type de page (de la plus spécifique à la plus générale)
_PP_SECTIONS = ("pp_precoce_mere", "pp_precoce_nne", "pp_tardif_mere", "pp_tardif_nne")


def _date_key(d: str) -> tuple[int, int, int]:
    day, month, year = (int(x) for x in d.split("/"))
    return year, month, day


def _reference(record: Record) -> tuple[str, str] | None:
    """(type, date jj/mm/aaaa) : date de consultation (post-partum), sinon date
    d'accouchement, sinon « venue le » de la visite la plus récente du tableau."""
    found: dict[str, list[str]] = {"post_partum": [], "accouchement": [], "visite": []}
    for f in record.fields:
        if f.is_current is False or f.value_json is None:   # None = pas encore flushé (défaut True)
            continue
        try:
            d = parse_date(json.loads(f.value_json))
        except (ValueError, TypeError):
            continue
        if not d or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", d):
            continue
        if f.section in _PP_SECTIONS and f.field_key == "date_consultation":
            found["post_partum"].append(f"{f.section}|{d}")
        elif f.section == "accouchement" and f.field_key == "date":
            found["accouchement"].append(d)
        elif f.section == "grossesse_actuelle" and re.fullmatch(r"visites\.[A-Z0-9]+\.venue_le", f.field_key):
            found["visite"].append(d)
    if found["post_partum"]:
        kind, d = max((x.split("|") for x in found["post_partum"]), key=lambda kd: _date_key(kd[1]))
        return kind, d
    if found["accouchement"]:
        return "accouchement", max(found["accouchement"], key=_date_key)
    if found["visite"]:
        return "visite", max(found["visite"], key=_date_key)
    return None


def date_reference(record: Record) -> str | None:
    """Date qui situe le dossier dans le suivi de la patiente (jj/mm/aaaa) ou None."""
    ref = _reference(record)
    return ref[1] if ref else None


def find_duplicate(db: Session, record: Record, patient_id: str) -> Record | None:
    """Autre dossier déjà enregistré de la même patiente, même type de page, même date de référence."""
    ref = _reference(record)
    if ref is None:
        return None
    db.flush()
    others = db.scalars(
        select(Record).where(Record.patient_id == patient_id, Record.id != record.id,
                             Record.status.in_([S.ENREGISTRE, S.SYNCHRONISE]))
        .order_by(Record.created_at)).all()
    return next((o for o in others if _reference(o) == ref), None)
