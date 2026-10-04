"""Point d'entrée FastAPI : `uvicorn app.main:app --reload --port 8000`."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routers import admin, privacy, records, verif, webhook
from app.services import ai_worker, ingest, outbox, processing, sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("iris")


def run_maintenance_cycle():
    """Rattrapage : messages entrants non traités, sessions expirées, échecs IA,
    synchronisation centrale, outbox (en dernier : envoie aussi les messages des étapes précédentes)."""
    with SessionLocal() as db:
        ingest.retry_failed_inbound(db)
        ingest.auto_close_stale_sessions(db)
        processing.retry_failed_processing(db)
        ai_worker.kick()                       # lecture IA dans un thread à part (non bloquant)
        sync.sync_pending(db)
        outbox.flush_pending(db)


async def _worker(interval: int):
    while True:
        try:
            await asyncio.to_thread(run_maintenance_cycle)
        except Exception:
            log.exception("Cycle de maintenance échoué")
        await asyncio.sleep(interval)


def check_config():
    """Signale tout de suite les réglages manquants ou suspects du .env."""
    s = get_settings()
    problems = []
    if not s.storage_encryption_key:
        problems.append("STORAGE_ENCRYPTION_KEY vide (python scripts/gen_key.py)")
    if not s.whatsapp_app_secret and not s.whatsapp_skip_signature:
        problems.append("WHATSAPP_APP_SECRET vide : tous les webhooks seront refusés (401)")
    if not s.whatsapp_access_token.startswith("EAA"):
        problems.append("WHATSAPP_ACCESS_TOKEN ne commence pas par 'EAA' : ce n'est pas un jeton Meta")
    if not s.whatsapp_phone_number_id.isdigit():
        problems.append("WHATSAPP_PHONE_NUMBER_ID doit être l'identifiant numérique, pas le numéro (+1...)")
    if s.whatsapp_access_token == s.whatsapp_verify_token:
        problems.append("WHATSAPP_ACCESS_TOKEN identique au VERIFY_TOKEN : ce sont deux valeurs différentes")
    if s.ai_enabled:
        problems += _check_ai(s)
    for p in problems:
        log.error("CONFIG .env : %s", p)
    if not problems:
        log.info("Configuration .env OK")
    return problems


def _check_ai(s) -> list[str]:
    """Ollama joignable et modèles installés (avertissement seulement : les dossiers attendront)."""
    if not 0 < s.ai_seuil_connu <= 1:
        return [f"AI_SEUIL_CONNU={s.ai_seuil_connu} doit être entre 0 et 1"]
    try:
        from ai.ollama_client import OllamaClient, OllamaUnavailable
    except ImportError as e:
        return [f"AI_ENABLED=true mais dépendances IA absentes ({e}) : pip install -r requirements.txt"]
    try:
        models = OllamaClient(s.ollama_url).ping()
    except OllamaUnavailable:
        return [f"Ollama injoignable sur {s.ollama_url} : lancez « ollama serve » (les dossiers attendront)"]
    missing = [m for m in {s.ai_model_main, s.ai_model_verify} if m and m not in models
               and f"{m}:latest" not in models]
    return [f"modèle Ollama absent : {m} (ollama pull {m})" for m in missing]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    check_config()
    s = get_settings()
    task = asyncio.create_task(_worker(s.worker_interval_seconds)) if s.worker_enabled else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Iris – The Offline Midwife (défi DayOne)", version="0.1.0", lifespan=lifespan)
app.include_router(webhook.router)
app.include_router(records.router)
app.include_router(privacy.router)
app.include_router(admin.router)
app.include_router(verif.router)


@app.get("/health")
def health():
    return {"status": "ok"}
