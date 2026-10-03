"""Stockage chiffré (Fernet = AES-128-CBC + HMAC-SHA256) des images d'origine.

- Nom de fichier opaque (UUID) : rien d'identifiant sur le disque.
- Le SHA-256 est calculé sur l'image en clair : intégrité + détection de doublons.
- L'image d'origine n'est jamais modifiée (on stocke les octets reçus tels quels).
"""
import hashlib
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class StorageError(Exception):
    pass


class EncryptedImageStore:
    def __init__(self, root: Path, key: str):
        if not key:
            raise StorageError("STORAGE_ENCRYPTION_KEY manquante (python scripts/gen_key.py)")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def _path(self, storage_key: str) -> Path:
        if not storage_key.replace("-", "").replace(".enc", "").isalnum():
            raise StorageError("clé de stockage invalide")   # anti path-traversal
        return self.root / storage_key

    def save(self, data: bytes) -> tuple[str, str]:
        """Chiffre et écrit. Retourne (storage_key, sha256_hex)."""
        digest = hashlib.sha256(data).hexdigest()
        storage_key = f"{uuid.uuid4()}.enc"
        path = self._path(storage_key)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(self._fernet.encrypt(data))
        tmp.replace(path)                                     # écriture atomique
        return storage_key, digest

    def load(self, storage_key: str) -> bytes:
        try:
            return self._fernet.decrypt(self._path(storage_key).read_bytes())
        except (FileNotFoundError, InvalidToken) as e:
            raise StorageError(f"image illisible : {type(e).__name__}") from e


_store: EncryptedImageStore | None = None


def get_store() -> EncryptedImageStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = EncryptedImageStore(s.storage_dir, s.storage_encryption_key)
    return _store
