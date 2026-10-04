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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
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
UNKNOWN = "inconnu"
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _default_extractor() -> Callable[[list[bytes]], list]:
    s = get_settings()
    if s.ai_mode == "ocr":                                   # OCR classique + 2e avis Ollama (étape 3d)
        from ai.ocr_classique import extract_pages_ocr
        from ai.ollama_client import OllamaClient

        def run(images: list[bytes], page_types=None):
            client = OllamaClient(s.ollama_url, timeout=s.ai_timeout_seconds, num_ctx=s.ai_num_ctx,
                                  num_predict=s.ai_num_predict) if s.ai_model_verify else None
            return extract_pages_ocr(images, engine=s.ai_ocr_engine, client=client,
                                     verify_model=s.ai_model_verify or None, page_types=page_types)
        return run
    from ai.extract import extract_pages                    # import paresseux (opencv, numpy)
    return extract_pages


def excluded_identifiers(page_type: str | None, removed_keys: list[str]) -> list[str]:
    """Identifiants NON enregistrés pour cette page : ceux que la page contient par construction
    (jamais demandés à l'IA) + ceux que la liste blanche a rejetés. Clés seulement."""
    from app.templates import get_template
    t = get_template()
    keys = set()
    if page_type and page_type in {p.key for p in t.page_types}:
        for sec in t.page_type(page_type).sections:
            keys |= {k.split(".")[-1] for k, f in t.section_fields([sec]).items() if f.identifiant}
    keys |= {k.split(".")[-1] for k in removed_keys}      # filtré à l'affichage (types connus seulement)
    return sorted(keys)


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


def _too_slow(db: Session, rec: Record, budget: int) -> None:
    """Lecture trop longue : on ne fait pas attendre la sage-femme -> saisie guidée, expliquée."""
    log.warning("Lecture du dossier %s : budget de %d s dépassé -> saisie guidée", rec.id[:8], budget)
    from app.state_machine import MAX_AI_ATTEMPTS
    rec.ai_attempts = max(rec.ai_attempts or 0, MAX_AI_ATTEMPTS)     # relancer serait aussi lent
    transition(db, rec, RecordStatus.ECHEC_TRAITEMENT, ACTOR, reason=f"lecture > {budget} s, pas de relance")
    transition(db, rec, RecordStatus.REVISION_MANUELLE_REQUISE, ACTOR, reason="budget de lecture dépassé")
    from app.i18n import t
    mw = db.get(Midwife, rec.midwife_id)
    _notify(db, rec, t(mw.language if mw else "fr", "too_slow", rid=rec.id[:8]))
    from app.services import conversation
    conversation.on_manual_required(db, rec)
    db.commit()


def _write_fields(db: Session, rec: Record, results, pages) -> tuple[int, int]:
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
            page_number=pages[d["page"] - 1].page_number if d.get("page") and d["page"] <= len(pages) else None,
            is_current=True,
            details_json=json.dumps({"candidates": d.get("candidates") or [], "flags": d.get("flags") or [],
                                     "zone": d.get("zone")}, ensure_ascii=False)))
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
        active = sorted((p for p in rec.pages if not p.replaced), key=lambda p: p.page_number)
        images = [get_store().load(p.storage_key) for p in active]       # en mémoire uniquement
        hints = [p.page_type if p.page_type_force else None for p in active]
        run = extractor or _default_extractor()
        budget = s.ai_budget_page_seconds * max(1, len(images))
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="iris-lecture")
        fut = pool.submit(lambda: run(images, page_types=hints) if any(hints) else run(images))
        pool.shutdown(wait=False)
        try:
            results = fut.result(timeout=budget)
        except FutureTimeout:
            _too_slow(db, rec, budget)
            return rec.id
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

    # vraie panne (pas une page non reconnue : celle-là, on demande son type à la sage-femme)
    if results and all(r.error and not r.fields and r.page_type != UNKNOWN for r in results):
        _fail(db, rec, "; ".join(f"page {r.index + 1} : {r.error}" for r in results))
        return rec.id

    pages = active
    bad = []
    unknown, forced_empty = [], []
    for page, res in zip(pages, results):
        page.quality_json = json.dumps(res.quality, ensure_ascii=False) if res.quality else None
        if res.page_type == UNKNOWN or not res.fields:
            (forced_empty if page.page_type_force else unknown).append(page)
        if not page.page_type_force:
            page.page_type = None if res.page_type == UNKNOWN else res.page_type
        page.identifiers_excluded = json.dumps(excluded_identifiers(res.page_type, res.removed_keys))
        if res.quality and not res.quality.get("ok", True):
            bad.append((page.page_number, res.quality.get("raisons") or []))
    rec.extraction_model = (s.ai_model_main or "")[:80]
    lus, a_verifier = _write_fields(db, rec, results, pages)
    transition(db, rec, RecordStatus.TRAITE_IA, ACTOR, f"{lus} champ(s) lu(s)")
    transition(db, rec, RecordStatus.A_REVISER, ACTOR, f"{a_verifier} champ(s) à vérifier")
    for n, reasons in bad:
        from app.i18n import t
        mw = db.get(Midwife, rec.midwife_id)
        _notify(db, rec, t(mw.language if mw else "fr", "bad_photo", n=n,
                           reasons=" et ".join(reasons) or "de mauvaise qualité"))
    from app.services import conversation
    unknown = [p for p in unknown if not p.page_type]        # vraiment non reconnues
    if unknown:
        # 🟠 « Je ne reconnais pas cette page » : la sage-femme choisit le type, on relit
        conversation.ask_page_type(db, rec, unknown[0])
    elif forced_empty and len(forced_empty) == len(pages) and lus == 0:
        # même avec le type imposé, rien de lisible : saisie guidée des champs prioritaires
        transition(db, rec, RecordStatus.REVISION_MANUELLE_REQUISE, ACTOR,
                   reason="page illisible même avec le type indiqué par la sage-femme")
        conversation.on_manual_required(db, rec)
    else:
        conversation.on_record_ready(db, rec)                # résumé + [Vérifier] (bloc 4)
    db.commit()
    log.info("Dossier %s lu : %d champs, %d à vérifier", rec.id[:8], lus, a_verifier)
    log.info("Vérifier l'extraction : http://127.0.0.1:8000/verif/%s", rec.id)
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
