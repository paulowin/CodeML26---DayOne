"""Commande « RDV » : patientes dont le rendez-vous est dépassé sans visite depuis.

Rendez-vous = dernière date CONNU parmi « Rendez-vous » (tableau des visites), « Prochain
rendez-vous » et « Revenir pour une visite de suivi » des dossiers rattachés à la patiente ;
dernière visite = dernière date « Venue le » (sinon la date de prise de la photo).
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FieldStatus, Midwife, Patient

RDV_KEYS = ("rendez_vous", "prochain_rdv", "prochaine_visite")


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(json.loads(v))[:10]) if v else None
    except (ValueError, TypeError):
        return None


def overdue(db: Session, mw: Midwife, today: date | None = None) -> list[tuple[str, date]]:
    """[(code patiente, date du RDV manqué)], le plus ancien d'abord."""
    today = today or date.today()
    out = []
    for p in db.scalars(select(Patient).where(Patient.midwife_id == mw.id)).all():
        rdvs, visits = [], []
        for rec in p.records:
            if rec.first_captured_at:
                visits.append(rec.first_captured_at.date())
            seen_venue = False
            for f in rec.fields:
                if not f.is_current or f.status != FieldStatus.CONNU:
                    continue
                d = _date(f.value_json)
                if d is None:
                    continue
                last = f.field_key.rsplit(".", 1)[-1]
                if last in RDV_KEYS:
                    rdvs.append(d)
                elif last == "venue_le":
                    if not seen_venue and rec.first_captured_at:
                        visits.remove(rec.first_captured_at.date())   # la date écrite fait foi
                    seen_venue = True
                    visits.append(d)
        if not rdvs:
            continue
        rdv = max(rdvs)
        if rdv < today and not any(v >= rdv for v in visits):
            out.append((p.code, rdv))
    return sorted(out, key=lambda x: x[1])
