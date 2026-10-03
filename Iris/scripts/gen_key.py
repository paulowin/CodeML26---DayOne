"""Génère une clé Fernet pour STORAGE_ENCRYPTION_KEY."""
from cryptography.fernet import Fernet

print(Fernet.generate_key().decode())
