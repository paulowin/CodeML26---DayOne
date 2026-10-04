import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# --- environnement de test AVANT tout import de l'app ---
_TMP = Path(tempfile.mkdtemp(prefix="dayone_test_"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "STORAGE_DIR": str(_TMP / "images"),
    "STORAGE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "WHATSAPP_APP_SECRET": "test-secret",
    "WHATSAPP_VERIFY_TOKEN": "verify-me",
    "WHATSAPP_ACCESS_TOKEN": "x",
    "WHATSAPP_PHONE_NUMBER_ID": "123",
    "WORKER_ENABLED": "false",
    "AI_ENABLED": "false",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.whatsapp import WhatsAppClient, WhatsAppError  # noqa: E402

MIDWIFE = "212600000001"


class FakeWhatsApp:
    """Remplace l'API Meta : médias en mémoire, messages envoyés capturés."""

    def __init__(self):
        self.media: dict[str, bytes] = {}
        self.sent: list[dict] = []
        self.uploads: list[bytes] = []
        self.online = True
        self._n = 0

    def download_media(self, _self_client, media_id):
        if not self.online:
            raise WhatsAppError("réseau coupé")
        return self.media[media_id], "image/jpeg"

    def upload_media(self, _self_client, data, mime="image/jpeg"):
        if not self.online:
            raise WhatsAppError("réseau coupé")
        self.uploads.append(data)
        return f"media.{len(self.uploads)}"

    def send(self, _self_client, payload):
        if not self.online:
            raise WhatsAppError("réseau coupé")
        self._n += 1
        self.sent.append(payload)
        return f"wamid.out.{self._n}"


@pytest.fixture
def fake_wa(monkeypatch):
    fake = FakeWhatsApp()
    monkeypatch.setattr(WhatsAppClient, "download_media", lambda s, m: fake.download_media(s, m))
    monkeypatch.setattr(WhatsAppClient, "send", lambda s, p: fake.send(s, p))
    monkeypatch.setattr(WhatsAppClient, "upload_media", lambda s, d, m="image/jpeg": fake.upload_media(s, d, m))
    return fake


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()


def post_webhook(client, payload: dict, signed: bool = True):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Hub-Signature-256"] = sign(body)
    return client.post("/webhook", content=body, headers=headers)


def wa_payload(*messages: dict) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": "123"},
            "contacts": [{"wa_id": MIDWIFE, "profile": {"name": "NE PAS STOCKER"}}],
            "messages": list(messages)}}]}]}


def image_msg(wamid: str, media_id: str, ts: int, caption: str | None = None) -> dict:
    img = {"id": media_id, "mime_type": "image/jpeg"}
    if caption:
        img["caption"] = caption
    return {"from": MIDWIFE, "id": wamid, "timestamp": str(ts), "type": "image", "image": img}


def text_msg(wamid: str, body: str, ts: int) -> dict:
    return {"from": MIDWIFE, "id": wamid, "timestamp": str(ts), "type": "text", "text": {"body": body}}


def button_msg(wamid: str, button_id: str, ts: int) -> dict:
    return {"from": MIDWIFE, "id": wamid, "timestamp": str(ts), "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "x"}}}


def body_of(payload: dict) -> str:
    """Texte d'un message sortant, qu'il soit simple ou interactif (boutons / liste)."""
    if payload.get("type") == "interactive":
        return payload["interactive"]["body"]["text"]
    return payload["text"]["body"]
