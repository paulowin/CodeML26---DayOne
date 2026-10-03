"""Point d'entrée FastAPI : `uvicorn app.main:app --reload --port 8000`."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routers import records, webhook
from app.services import ingest, outbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dayone")


def run_maintenance_cycle():
    """Rattrapage : messages entrants non traités, sessions expirées, outbox."""
    with SessionLocal() as db:
        ingest.retry_failed_inbound(db)
        ingest.auto_close_stale_sessions(db)
        outbox.flush_pending(db)


async def _worker(interval: int):
    while True:
        try:
            await asyncio.to_thread(run_maintenance_cycle)
        except Exception:
            log.exception("Cycle de maintenance échoué")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    s = get_settings()
    task = asyncio.create_task(_worker(s.worker_interval_seconds)) if s.worker_enabled else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="DayOne – The Offline Midwife", version="0.1.0", lifespan=lifespan)
app.include_router(webhook.router)
app.include_router(records.router)


@app.get("/health")
def health():
    return {"status": "ok"}
