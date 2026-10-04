"""API d'administration (ADMIN, SUPERVISEUR) : réseau central simulé + tableau de bord."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExtractedField, FieldSource, FieldStatus, Record, RecordEvent, RecordStatus, Role, Staff
from app.security import require_staff
from app.services import sync

router = APIRouter(prefix="/api", tags=["admin"])


def require_supervisor(staff: Staff = Depends(require_staff)) -> Staff:
    if staff.role not in (Role.ADMIN, Role.SUPERVISEUR):
        raise HTTPException(403, "Réservé aux rôles ADMIN et SUPERVISEUR")
    return staff


class NetworkSwitch(BaseModel):
    en_ligne: bool


@router.post("/admin/reseau")
def switch_network(body: NetworkSwitch, _: Staff = Depends(require_supervisor), db: Session = Depends(get_db)):
    sync.set_flag(db, sync.NETWORK_FLAG, "on" if body.en_ligne else "off")
    db.commit()
    return {"reseau_central": sync.get_flag(db, sync.NETWORK_FLAG, "on")}


@router.get("/tableau")
def dashboard(_: Staff = Depends(require_supervisor), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Record.status, func.count()).group_by(Record.status)).all())
    events = db.scalars(select(RecordEvent).order_by(RecordEvent.id.desc()).limit(10)).all()
    pending_link = db.scalars(select(Record).where(Record.link_pending.is_(True),
                                                   Record.status == RecordStatus.VALIDE)).all()
    supervisor_fields = db.execute(
        select(ExtractedField.record_id, func.count()).where(
            ExtractedField.is_current.is_(True), ExtractedField.source == FieldSource.SYSTEME,
            ExtractedField.status == FieldStatus.A_REVISER).group_by(ExtractedField.record_id)).all()
    return {
        "reseau_central": sync.get_flag(db, sync.NETWORK_FLAG, "on"),
        "par_etat": {s.value: counts.get(s, 0) for s in RecordStatus},
        # « Je ne sais pas » : à rattacher via POST /api/records/{id}/rattacher
        "a_rattacher": [{"dossier": r.id, "depuis": r.updated_at} for r in pending_link],
        # au-delà de 10 questions par dossier : champs laissés au superviseur
        "champs_a_verifier_superviseur": {rid: n for rid, n in supervisor_fields},
        "derniers_evenements": [{"dossier": e.record_id[:8], "de": e.from_status, "vers": e.to_status,
                                 "acteur": e.actor, "note": e.note, "a": e.at} for e in events],
    }
