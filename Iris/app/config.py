"""Configuration centralisée (lue depuis .env)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Base de données (SQLite par défaut, PostgreSQL via DATABASE_URL) ---
    database_url: str = "sqlite:///./data/dayone.db"

    # Contact affiché sur la page /confidentialite (optionnel)
    contact_email: str = ""

    # --- WhatsApp Cloud API (mode "reel") ---
    whatsapp_verify_token: str = "change-me"          # jeton choisi par nous, saisi dans Meta
    whatsapp_app_secret: str = ""                     # App Secret Meta -> signature X-Hub-Signature-256
    whatsapp_access_token: str = ""                   # token (system user) pour Graph API
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    whatsapp_graph_url: str = "https://graph.facebook.com"
    # Désactiver la vérification de signature UNIQUEMENT en dev local
    whatsapp_skip_signature: bool = False

    # --- Stockage chiffré des images ---
    storage_dir: Path = Path("./data/images")
    # Clé Fernet (base64 32 octets). Générer : python scripts/gen_key.py
    storage_encryption_key: str = ""

    # --- Sessions multipages ---
    # Délai max (s) entre deux photos d'un même registre (horodatage WhatsApp, pas réception)
    session_window_seconds: int = 900
    max_image_bytes: int = 15 * 1024 * 1024

    # --- Worker de rattrapage (messages non traités, outbox) ---
    worker_interval_seconds: int = 20
    worker_enabled: bool = True

    # --- Cerveau IA local (Ollama, aucun service externe) ---
    ai_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    ai_model_main: str = "qwen2.5vl:3b"
    ai_model_verify: str = "qwen2.5vl:3b"      # 2e avis (« qwen2.5vl:7b » si la VRAM le permet ; vide = désactivé)
    ai_seuil_connu: float = 0.8                # confiance minimale pour le statut CONNU
    ai_timeout_seconds: int = 600
    ai_num_ctx: int = 8192                     # contexte Ollama (4096 si la VRAM sature)
    ai_num_predict: int = 2048                 # plafond de tokens générés par appel (anti-boucle)


@lru_cache
def get_settings() -> Settings:
    return Settings()
