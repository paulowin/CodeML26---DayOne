"""Webhook WhatsApp Cloud API.

GET  /webhook : vérification initiale par Meta (hub.challenge).
POST /webhook : réception des messages. Signature HMAC vérifiée sur le corps
brut, persistance idempotente, 200 OK immédiat, traitement en tâche de fond.
"""
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.db import SessionLocal
from app.security import verify_meta_signature
from app.services import ingest, outbox

router = APIRouter(tags=["webhook"])
log = logging.getLogger(__name__)


@router.get("/webhook", response_class=PlainTextResponse)
def verify(hub_mode: str = Query(alias="hub.mode", default=""),
           hub_verify_token: str = Query(alias="hub.verify_token", default=""),
           hub_challenge: str = Query(alias="hub.challenge", default="")):
    if hub_mode == "subscribe" and hub_verify_token == get_settings().whatsapp_verify_token:
        return hub_challenge
    raise HTTPException(403, "Jeton de vérification invalide")


def _process_batch(ids: list[int]):
    with SessionLocal() as db:
        for i in ids:
            ingest.process_inbound(db, i)
        outbox.flush_pending(db)


@router.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Signature invalide")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON invalide")

    items = ingest.parse_webhook(payload)
    if not items:                    # statuts de livraison, etc.
        return {"status": "ok", "new": 0}
    with SessionLocal() as db:
        new_ids = ingest.persist_inbound(db, items)   # persisté AVANT de répondre -> rien de perdu
    if new_ids:
        background.add_task(_process_batch, new_ids)
    return {"status": "ok", "new": len(new_ids)}
