"""Signature des webhooks Meta + authentification du personnel par clé API."""
import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Staff


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Vérifie X-Hub-Signature-256 = 'sha256=' + HMAC_SHA256(app_secret, body brut)."""
    s = get_settings()
    if s.whatsapp_skip_signature:
        return True
    if not s.whatsapp_app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(s.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key() -> str:
    return "dk_" + secrets.token_urlsafe(32)


def require_staff(x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> Staff:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clé API requise (en-tête X-API-Key)")
    staff = db.scalar(select(Staff).where(Staff.api_key_hash == hash_api_key(x_api_key), Staff.active.is_(True)))
    if not staff:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clé API invalide")
    return staff
