"""Prépare une démo fiable du flux conversationnel (sans attendre le traitement IA).

    python -m scripts.demo_seed 2126XXXXXXXX        # wa_id de la sage-femme (son numéro WhatsApp)

Crée : la sage-femme, 2 patientes (codes A64125 avec 3 visites synchronisées et A64128
avec 1 visite), et un dossier A_REVISER construit depuis la vérité terrain de la page
spécimen 3 (grossesse actuelle, données FICTIVES) avec 5 champs volontairement douteux
(dont une TA avec 2 lectures concurrentes). Le message résumé [Vérifier] est mis dans
l'outbox et envoyé tout de suite si le réseau répond (sinon au prochain cycle du worker).
Le code de registre lu est A64125 : à la liaison, A64125 (exact) et A64128 (proche) sont proposés.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import (ExtractedField, FieldSource, FieldStatus, Midwife, Page, Patient, Record, RecordEvent,
                        RecordStatus)
from app.templates import get_template
from app.templates.normalize import interpret
from eval.common import DATA_DIR, GT_DIR

T = get_template()
DEMO_PAGE = 3                       # spécimen : grossesse actuelle, patiente fictive 1
CODE = "A64125"
V = "grossesse_actuelle.visites."
DOUBTS = {                          # clé -> (statut, confiance, candidats, drapeaux = raison du doute)
    V + "T2V2.ta": (FieldStatus.A_REVISER, 0.5, [{"sys": 106, "dia": 77}, {"sys": 166, "dia": 77}], []),
    V + "T2V3.poids_kg": (FieldStatus.A_REVISER, 0.55, [], []),
    V + "T1V2.hemoglobine": (FieldStatus.ILLISIBLE, 0.3, [], []),
    "grossesse_actuelle.ddr": (FieldStatus.A_REVISER, 0.6, [], ["dpa_incoherente_avec_ddr"]),
    V + "M8.age_probable_sa": (FieldStatus.A_REVISER, 0.45, [], ["age_gestationnel_incoherent_ddr"]),
}


def _field(rec: Record, key: str, value, status=FieldStatus.CONNU, conf=0.9, source=FieldSource.IA,
           raw=None, details=None, page=1):
    section, fk = key.split(".", 1)
    rec.fields.append(ExtractedField(section=section, field_key=fk, value_json=json.dumps(value, ensure_ascii=False),
                                     raw_text=raw, status=status, confidence=conf, source=source, page_number=page,
                                     is_current=True, details_json=json.dumps(details) if details else None))


def _visit(db, mw: Midwife, patient: Patient, when: datetime, venue: str) -> Record:
    rec = Record(midwife_id=mw.id, patient_id=patient.id, status=RecordStatus.SYNCHRONISE, session_open=False,
                 first_captured_at=when, last_page_at=when, synced_at=when)
    db.add(rec)
    db.flush()
    _field(rec, V + "T1V1.venue_le", venue, source=FieldSource.SAGE_FEMME, conf=1.0)
    db.add(RecordEvent(record=rec, from_status=None, to_status=RecordStatus.SYNCHRONISE.value,
                       actor="system:demo", note="visite de démonstration"))
    return rec


def seed(wa_id: str, send: bool = True) -> str:
    init_db()
    gt = json.loads((GT_DIR / f"specimen_p{DEMO_PAGE:02d}.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == wa_id)) or Midwife(wa_id=wa_id)
        mw.conversation_state = None
        db.add(mw)
        db.flush()
        p1 = Patient(midwife_id=mw.id, code=CODE)
        p2 = Patient(midwife_id=mw.id, code="A64128")
        db.add_all([p1, p2])
        db.flush()
        for i, d in enumerate(("2025-09-28", "2025-11-01", "2025-12-01")):
            _visit(db, mw, p1, now - timedelta(days=90 - 30 * i), d)
        _visit(db, mw, p2, now - timedelta(days=20), "2025-12-15")

        rec = Record(midwife_id=mw.id, status=RecordStatus.A_REVISER, session_open=False,
                     first_captured_at=now, last_page_at=now, extraction_model="demo (vérité terrain)")
        db.add(rec)
        db.flush()
        png = next(DATA_DIR.glob(f"dossiers_specimen_10_patientes-{DEMO_PAGE:02d}*.png"), None) \
            if DATA_DIR.exists() else None
        if png is not None:
            from app.storage import get_store
            key, sha = get_store().save(png.read_bytes())
            rec.pages.append(Page(page_number=1, storage_key=key, sha256=sha, mime_type="image/png",
                                  size_bytes=png.stat().st_size, wa_message_id=f"demo-{rec.id}", captured_at=now,
                                  page_type="grossesse_actuelle"))
        _field(rec, "couverture.numero_fiche", CODE, raw=CODE, conf=0.85)
        for key, v in gt["fields"].items():
            f = T.fields.get(key)
            if f is None or f.identifiant:
                continue
            raw = gt["raw"].get(key)
            value = interpret(f, raw).value if raw is not None and not f.is_checkbox else v
            if key in DOUBTS:
                status, conf, cands, flags = DOUBTS[key]
                if status == FieldStatus.ILLISIBLE:
                    value = None
                details = {"candidates": cands, "flags": flags}
                _field(rec, key, cands[0] if cands else value, status, conf, raw=raw, details=details)
            else:
                _field(rec, key, value, conf=0.9, raw=raw)
        for from_s, to_s in ((None, "CAPTURE"), ("CAPTURE", "EN_ATTENTE_IA"), ("EN_ATTENTE_IA", "TRAITE_IA"),
                             ("TRAITE_IA", "A_REVISER")):
            db.add(RecordEvent(record=rec, from_status=from_s, to_status=to_s, actor="system:demo"))
        db.flush()

        from app.services import conversation, outbox
        conversation.on_record_ready(db, rec)
        db.commit()
        if send:
            try:
                outbox.flush_pending(db)
            except Exception as e:  # noqa: BLE001  (hors ligne : le worker enverra plus tard)
                print(f"Envoi différé ({type(e).__name__}) : le worker enverra le message.")
        print(f"Sage-femme {wa_id} : patientes {CODE} (3 visites) et A64128 (1 visite) ; "
              f"dossier {rec.id[:8]} en A_REVISER ({len(rec.fields)} champs, {len(DOUBTS)} douteux).")
        return rec.id


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("wa_id", help="numéro WhatsApp de la sage-femme (format international sans +)")
    ap.add_argument("--no-send", action="store_true", help="ne pas envoyer tout de suite (outbox seulement)")
    a = ap.parse_args()
    seed(a.wa_id, send=not a.no_send)


if __name__ == "__main__":
    main()
