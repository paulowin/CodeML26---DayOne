"""Worker IA : lit UN dossier EN_ATTENTE_IA à la fois (le plus ancien).

Les pages sont déchiffrées EN MÉMOIRE et passées à `ai.extract.extract_pages` ;
les champs sont écrits en `ExtractedField` (source IA), puis
EN_ATTENTE_IA -> TRAITE_IA -> A_REVISER : l'IA ne valide jamais seule, la
sage-femme confirme toujours (bloc 4). Ollama coupé ou erreur -> ECHEC_TRAITEMENT
(la reprise est gérée par `processing.retry_failed_processing`).

`kick()` est appelé par le cycle de maintenance : il lance la lecture dans un
thread à part (une lecture prend plusieurs minutes, elle ne doit pas bloquer
l'outbox ni la synchronisation).
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import ExtractedField, FieldSource, FieldStatus, Midwife, Record, RecordStatus
from app.services import outbox
from app.state_machine import transition
from app.storage import StorageError, get_store
from app.whatsapp import text_message

log = logging.getLogger("iris.ai_worker")
ACTOR = "system:ia"
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _default_extractor() -> Callable[[list[bytes]], list]:
    from ai.extract import extract_pages                    # import paresseux (opencv, numpy)
    return extract_pages


def next_record(db: Session) -> Record | None:
    return db.scalars(select(Record).where(Record.status == RecordStatus.EN_ATTENTE_IA)
                      .order_by(Record.last_page_at, Record.created_at).limit(1)).first()


def _notify(db: Session, rec: Record, body: str) -> None:
    mw = db.get(Midwife, rec.midwife_id)
    if mw:
        outbox.enqueue(db, text_message(mw.wa_id, body))


def _fail(db: Session, rec: Record, reason: str) -> None:
    log.warning("Lecture IA du dossier %s échouée : %s", rec.id[:8], reason)
    transition(db, rec, RecordStatus.ECHEC_TRAITEMENT, ACTOR, reason=reason)
    db.commit()


def _write_fields(db: Session, rec: Record, results) -> tuple[int, int]:
    """Écrit les champs ; renvoie (champs lus, champs à vérifier)."""
    current = {f"{f.section}.{f.field_key}": f for f in rec.fields if f.is_current}
    best: dict[str, dict] = {}
    for res in results:
        for key, d in res.fields.items():
            if key not in best or d["confidence"] > best[key]["confidence"]:
                best[key] = d
    lus = a_verifier = 0
    for key, d in best.items():
        old = current.get(key)
        if old is not None and old.source == FieldSource.SAGE_FEMME:
            continue                                         # jamais écraser une correction humaine
        if old is not None:
            old.is_current = False
        section, field_key = key.split(".", 1)
        status = FieldStatus(d["status"])
        rec.fields.append(ExtractedField(
            section=section, field_key=field_key, value_json=json.dumps(d["value"], ensure_ascii=False),
            raw_text=d.get("raw_text"), status=status, confidence=d["confidence"], source=FieldSource.IA,
            page_number=d.get("page"), is_current=True,
            details_json=json.dumps({"candidates": d.get("candidates") or [], "flags": d.get("flags") or []},
                                    ensure_ascii=False)))
        lus += d["value"] is not None
        a_verifier += status in (FieldStatus.A_REVISER, FieldStatus.ILLISIBLE)
    return lus, a_verifier


def process_next(db: Session, extractor: Callable | None = None) -> str | None:
    """Traite le plus ancien dossier EN_ATTENTE_IA. Renvoie son id, ou None s'il n'y en a pas."""
    rec = next_record(db)
    if rec is None:
        return None
    rec.ai_attempts = (rec.ai_attempts or 0) + 1
    db.commit()                                              # la tentative compte même si le process meurt
    s = get_settings()
    try:
        from ai.ollama_client import OllamaError, OllamaUnavailable
    except ImportError as e:                                 # dépendances IA absentes
        _fail(db, rec, f"cerveau IA non installé : {e}")
        return rec.id
    try:
        images = [get_store().load(p.storage_key) for p in rec.pages]   # en mémoire uniquement
        results = (extractor or _default_extractor())(images)
    except OllamaUnavailable as e:
        _fail(db, rec, f"IA locale indisponible : {e}")
        return rec.id
    except (OllamaError, StorageError) as e:
        _fail(db, rec, f"lecture impossible : {e}")
        return rec.id
    except Exception as e:  # noqa: BLE001  (on ne laisse jamais un dossier bloqué EN_ATTENTE_IA)
        log.exception("Erreur inattendue du cerveau IA")
        _fail(db, rec, f"erreur IA : {type(e).__name__}")
        return rec.id

    if results and all(r.error and not r.fields for r in results):
        _fail(db, rec, "; ".join(f"page {r.index + 1} : {r.error}" for r in results))
        return rec.id

    pages = sorted(rec.pages, key=lambda p: p.page_number)
    bad = []
    for page, res in zip(pages, results):
        page.quality_json = json.dumps(res.quality, ensure_ascii=False) if res.quality else None
        page.page_type = res.page_type
        if res.quality and not res.quality.get("ok", True):
            bad.append((page.page_number, res.quality.get("raisons") or []))
    rec.extraction_model = (s.ai_model_main or "")[:80]
    lus, a_verifier = _write_fields(db, rec, results)
    transition(db, rec, RecordStatus.TRAITE_IA, ACTOR, f"{lus} champ(s) lu(s)")
    transition(db, rec, RecordStatus.A_REVISER, ACTOR, f"{a_verifier} champ(s) à vérifier")
    for n, reasons in bad:
        _notify(db, rec, f"La photo {n} est {' et '.join(reasons) or 'de mauvaise qualité'} : "
                         "pouvez-vous la reprendre ?")
    _notify(db, rec, f"Lecture terminée : {lus} champ(s) lu(s), {a_verifier} à vérifier.")
    db.commit()
    log.info("Dossier %s lu : %d champs, %d à vérifier", rec.id[:8], lus, a_verifier)
    return rec.id


def _run() -> None:
    while True:
        with SessionLocal() as db:
            if process_next(db) is None:
                return


def kick() -> bool:
    """Lance la lecture en arrière-plan si un dossier attend et qu'aucune lecture n'est en cours."""
    global _thread
    if not get_settings().ai_enabled:
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        with SessionLocal() as db:
            if next_record(db) is None:
                return False
        _thread = threading.Thread(target=_run, name="iris-ai", daemon=True)
        _thread.start()
        return True
