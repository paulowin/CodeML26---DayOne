"""Client minimal WhatsApp Cloud API (Graph API) + constructeurs de messages.

Remarque transport : les photos transitent par l'infrastructure WhatsApp (canal
imposé par le défi) ; elles sont téléchargées immédiatement puis traitées 100 %
en local. Aucun service d'IA / OCR tiers n'est appelé.
"""
import httpx

from app.config import get_settings


class WhatsAppError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    @property
    def permanent(self) -> bool:
        """Erreur définitive (mauvais jeton, numéro invalide...) : inutile de réessayer
        indéfiniment. Les 429 (quota) et 5xx (panne Meta) restent temporaires."""
        return self.status_code is not None and 400 <= self.status_code < 500 and self.status_code != 429


class WhatsAppClient:
    def __init__(self, timeout: float = 30.0):
        s = get_settings()
        self.base = f"{s.whatsapp_graph_url}/{s.whatsapp_api_version}"
        self.phone_number_id = s.whatsapp_phone_number_id
        self.max_bytes = s.max_image_bytes
        self._headers = {"Authorization": f"Bearer {s.whatsapp_access_token}"}
        self._timeout = timeout

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """1) GET /{media_id} -> URL signée ; 2) GET URL (avec le token) -> octets."""
        with httpx.Client(timeout=self._timeout) as c:
            meta = c.get(f"{self.base}/{media_id}", headers=self._headers)
            if meta.status_code != 200:
                raise WhatsAppError(f"media meta {meta.status_code}: {meta.text[:200]}")
            info = meta.json()
            if int(info.get("file_size", 0)) > self.max_bytes:
                raise WhatsAppError("image trop volumineuse")
            blob = c.get(info["url"], headers=self._headers)
            if blob.status_code != 200:
                raise WhatsAppError(f"media download {blob.status_code}")
            return blob.content, info.get("mime_type", "image/jpeg")

    def upload_media(self, data: bytes, mime: str = "image/jpeg") -> str:
        """POST /{phone_number_id}/media -> id du média (pour un message image)."""
        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self.base}/{self.phone_number_id}/media", headers=self._headers,
                       data={"messaging_product": "whatsapp", "type": mime},
                       files={"file": ("apercu.jpg", data, mime)})
        if r.status_code >= 300:
            raise WhatsAppError(f"upload {r.status_code}: {r.text[:300]}", r.status_code)
        return r.json()["id"]

    def send(self, payload: dict) -> str:
        """Envoie un message ; retourne le wamid. Lève WhatsAppError si échec."""
        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self.base}/{self.phone_number_id}/messages", headers=self._headers, json=payload)
        if r.status_code >= 300:
            raise WhatsAppError(f"send {r.status_code}: {r.text[:300]}", r.status_code)
        return r.json()["messages"][0]["id"]


def get_client() -> "WhatsAppClient":
    """Client WhatsApp Cloud API (seul transport)."""
    return WhatsAppClient()


# ------------------------------------------------------------------ constructeurs de payloads
def text_message(to: str, body: str) -> dict:
    return {"messaging_product": "whatsapp", "to": to, "type": "text",
            "text": {"preview_url": False, "body": body[:4096]}}


def preview_message(to: str, caption: str, record_id: str, page_number: int, zone) -> dict:
    """Message image dont l'image n'est fabriquée qu'à l'envoi (outbox) : seule la référence
    (dossier, page, zone) est persistée, jamais l'image déchiffrée."""
    return {"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"caption": caption[:1024]},
            "_preview": {"record_id": record_id, "page_number": page_number, "zone": list(zone)}}


def buttons_message(to: str, body: str, buttons: list[tuple[str, str]]) -> dict:
    """Boutons de réponse : MAX 3 boutons, titre <= 20 caractères."""
    if not 1 <= len(buttons) <= 3:
        raise ValueError("WhatsApp autorise 1 à 3 boutons")
    return {"messaging_product": "whatsapp", "to": to, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": body[:1024]},
                            "action": {"buttons": [{"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                                                   for bid, title in buttons]}}}


def list_message(to: str, body: str, button_label: str, rows: list[tuple[str, str, str]],
                 section_title: str = "Choix") -> dict:
    """Liste interactive : jusqu'à 10 lignes (titre <= 24 car.).
    Nécessaire pour la liaison patiente (4 options > limite des 3 boutons)."""
    if not 1 <= len(rows) <= 10:
        raise ValueError("WhatsApp autorise 1 à 10 lignes")
    return {"messaging_product": "whatsapp", "to": to, "type": "interactive",
            "interactive": {"type": "list", "body": {"text": body[:1024]},
                            "action": {"button": button_label[:20], "sections": [{
                                "title": section_title[:24],
                                "rows": [{"id": rid, "title": t[:24], "description": d[:72]} for rid, t, d in rows]}]}}}
