"""Remet la démo à zéro.

Par défaut : supprime tout ce qui concerne la ou les sages-femmes de DÉMO — dossiers, pages +
fichiers chiffrés, champs, événements, copie centrale, journaux d'accès, patientes, messages
entrants / sortants, liaisons en attente, état de conversation. Sages-femmes de démo = numéros
passés en argument, sinon celles qui ont un dossier créé par scripts/demo_seed.py.
`--all` : efface toutes les données (hors comptes du personnel). Le .env n'est jamais touché.

    python -m scripts.demo_reset                  # sages-femmes de démo détectées
    python -m scripts.demo_reset 15793661803      # cette sage-femme
    python -m scripts.demo_reset --all --yes      # tout
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import Base, SessionLocal, init_db

KEEP_TABLES = {"staff"}
DEMO_MODEL_PREFIX = "demo"


def _unlink(storage_key: str) -> int:
    p = Path(get_settings().storage_dir) / storage_key
    if p.exists():
        p.unlink()
        return 1
    return 0


def reset_all() -> dict[str, int]:
    init_db()
    from app import models  # noqa: F401  (enregistre les tables)
    counts = {}
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):       # enfants d'abord (clés étrangères)
            if table.name in KEEP_TABLES:
                continue
            counts[table.name] = db.execute(table.delete()).rowcount
        db.commit()
    store = Path(get_settings().storage_dir)
    counts["images_chiffrees"] = sum(1 for f in store.glob("*.enc") if f.unlink() is None) if store.exists() else 0
    return counts


def demo_midwives(db, wa_ids: list[str]) -> list:
    from app.models import Midwife, Record
    if wa_ids:
        return db.scalars(select(Midwife).where(Midwife.wa_id.in_(wa_ids))).all()
    ids = db.scalars(select(Record.midwife_id).where(Record.extraction_model.like(f"{DEMO_MODEL_PREFIX}%"))).all()
    return db.scalars(select(Midwife).where(Midwife.id.in_(set(ids)))).all()


def reset_demo(wa_ids: list[str] | None = None) -> dict[str, int]:
    """Supprime les données des sages-femmes de démo ; garde leur ligne (état de conversation remis à zéro)."""
    init_db()
    from app.models import (AccessLog, CentralRecord, ExtractedField, InboundMessage, OutboundMessage, Page, Patient,
                            Record, RecordEvent)
    counts: Counter = Counter()
    with SessionLocal() as db:
        mws = demo_midwives(db, wa_ids or [])
        for mw in mws:
            rec_ids = db.scalars(select(Record.id).where(Record.midwife_id == mw.id)).all()
            if rec_ids:
                for key in db.scalars(select(Page.storage_key).where(Page.record_id.in_(rec_ids))).all():
                    counts["images_chiffrees"] += _unlink(key)
                for model in (ExtractedField, Page, RecordEvent):
                    counts[model.__tablename__] += db.execute(delete(model).where(model.record_id.in_(rec_ids))).rowcount
                counts["central_records"] += db.execute(
                    delete(CentralRecord).where(CentralRecord.record_id.in_(rec_ids))).rowcount
                counts["access_logs"] += db.execute(delete(AccessLog).where(AccessLog.record_id.in_(rec_ids))).rowcount
                counts["records"] += db.execute(delete(Record).where(Record.id.in_(rec_ids))).rowcount
            counts["patients"] += db.execute(delete(Patient).where(Patient.midwife_id == mw.id)).rowcount
            counts["inbound_messages"] += db.execute(
                delete(InboundMessage).where(InboundMessage.wa_from == mw.wa_id)).rowcount
            counts["outbound_messages"] += db.execute(
                delete(OutboundMessage).where(OutboundMessage.to_wa_id == mw.wa_id)).rowcount
            mw.conversation_state = None
            counts["sages_femmes_remises_a_zero"] += 1
        db.commit()
    return dict(counts)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("wa_ids", nargs="*", help="numéros WhatsApp des sages-femmes de démo (sinon détection)")
    ap.add_argument("--all", action="store_true", help="effacer TOUTES les données (hors personnel)")
    ap.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    a = ap.parse_args()
    what = "TOUTES les données (hors comptes du personnel)" if a.all else "les données de la démo"
    if not a.yes and input(f"Effacer {what} ? [o/N] ").lower() != "o":
        print("Annulé.")
        return
    counts = reset_all() if a.all else reset_demo(a.wa_ids)
    total = sum(v for k, v in counts.items() if k != "sages_femmes_remises_a_zero")
    print(f"Remis à zéro ({total} ligne(s)/fichier(s) supprimé(s)) :",
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if v) or "rien à supprimer")


if __name__ == "__main__":
    main()
