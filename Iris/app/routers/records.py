"""API interne (personnel) : consultation des dossiers et des images d'origine.

Contrôle d'accès par rôle + journal de chaque accès (autorisé ou refusé) :
- ADMIN, SUPERVISEUR : tous les dossiers
- SAGE_FEMME        : uniquement ses propres dossiers
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccessLog, Page, Patient, Record, RecordStatus, Role, Staff
from app.security import require_staff
from app.storage import StorageError, get_store

router = APIRouter(prefix="/api", tags=["records"])


def _check_access(db: Session, staff: Staff, record: Record, action: str, page_id: str | None = None):
    allowed = staff.role in (Role.ADMIN, Role.SUPERVISEUR) or (
        staff.role == Role.SAGE_FEMME and staff.midwife_id == record.midwife_id)
    db.add(AccessLog(staff_id=staff.id, record_id=record.id, page_id=page_id, action=action, allowed=allowed))
    db.commit()
    if not allowed:
        raise HTTPException(403, "Accès refusé à ce dossier")


@router.get("/records/{record_id}")
def get_record(record_id: str, staff: Staff = Depends(require_staff), db: Session = Depends(get_db)):
    rec = db.get(Record, record_id)
    if not rec:
        raise HTTPException(404, "Dossier introuvable")
    _check_access(db, staff, rec, "view_record")
    return {
        "id": rec.id, "status": rec.status.value, "patient_id": rec.patient_id,
        "failure_reason": rec.failure_reason, "first_captured_at": rec.first_captured_at,
        "pages": [{"id": p.id, "page_number": p.page_number, "captured_at": p.captured_at,
                   "sha256": p.sha256, "mime_type": p.mime_type} for p in rec.pages],
        "fields": [{"key": f"{f.section}.{f.field_key}", "value": json.loads(f.value_json) if f.value_json else None,
                    "status": f.status.value, "confidence": f.confidence, "source": f.source.value}
                   for f in rec.fields if f.is_current],
        "events": [{"from": e.from_status, "to": e.to_status, "actor": e.actor, "note": e.note, "at": e.at}
                   for e in rec.events],
    }


@router.get("/records/{record_id}/pages/{page_number}/image")
def get_page_image(record_id: str, page_number: int, staff: Staff = Depends(require_staff),
                   db: Session = Depends(get_db)):
    rec = db.get(Record, record_id)
    if not rec:
        raise HTTPException(404, "Dossier introuvable")
    page = db.scalar(select(Page).where(Page.record_id == record_id, Page.page_number == page_number))
    if not page:
        raise HTTPException(404, "Page introuvable")
    _check_access(db, staff, rec, "view_image", page.id)
    try:
        data = get_store().load(page.storage_key)
    except StorageError:
        raise HTTPException(500, "Image indisponible ou altérée")
    return Response(content=data, media_type=page.mime_type,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class LinkBody(BaseModel):
    patient_id: str


@router.post("/records/{record_id}/rattacher")
def link_record(record_id: str, body: LinkBody, staff: Staff = Depends(require_staff), db: Session = Depends(get_db)):
    """Résout un « Je ne sais pas » : le superviseur rattache un dossier VALIDE à une patiente
    de la MÊME sage-femme (ADMIN / SUPERVISEUR uniquement)."""
    from app.state_machine import find_duplicate, transition
    if staff.role not in (Role.ADMIN, Role.SUPERVISEUR):
        raise HTTPException(403, "Réservé aux rôles ADMIN et SUPERVISEUR")
    rec = db.get(Record, record_id)
    if not rec:
        raise HTTPException(404, "Dossier introuvable")
    _check_access(db, staff, rec, "link_record")
    if rec.status != RecordStatus.VALIDE:
        raise HTTPException(409, f"Dossier en état {rec.status.value} : seul un dossier VALIDE se rattache")
    patient = db.get(Patient, body.patient_id)
    if not patient or patient.midwife_id != rec.midwife_id:
        raise HTTPException(400, "Patiente inconnue pour cette sage-femme")
    actor = f"staff:{staff.id}"
    rec.patient_id, rec.link_pending = patient.id, False
    dup = find_duplicate(db, rec, patient.id)
    if dup is not None:
        transition(db, rec, RecordStatus.DOUBLON_SUSPECT, actor, f"ressemble au dossier {dup.id[:8]}")
    else:
        transition(db, rec, RecordStatus.PATIENTE_LIEE, actor, f"rattaché par {staff.role.value}")
        transition(db, rec, RecordStatus.ENREGISTRE, actor)
    db.commit()
    return {"id": rec.id, "status": rec.status.value, "patient_id": patient.id,
            "doublon_de": dup.id if dup is not None else None}
