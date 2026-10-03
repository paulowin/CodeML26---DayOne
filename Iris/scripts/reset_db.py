"""Supprime la base SQLite locale (à faire quand le schéma change : create_all
n'ajoute pas les nouvelles colonnes aux tables existantes). Ne touche pas au .env.

Usage :
  python -m scripts.reset_db            # demande confirmation
  python -m scripts.reset_db --images   # supprime aussi les images chiffrées
"""
import argparse
import shutil
from pathlib import Path

from app.config import get_settings


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--images", action="store_true", help="supprimer aussi les images chiffrées")
    a = p.parse_args()
    s = get_settings()
    if not s.database_url.startswith("sqlite:///"):
        raise SystemExit("DATABASE_URL n'est pas SQLite : remise à zéro manuelle requise.")
    db_path = Path(s.database_url.removeprefix("sqlite:///"))
    targets = [Path(f"{db_path}{suffix}") for suffix in ("", "-wal", "-shm")]
    targets = [t for t in targets if t.exists()]
    images = Path(s.storage_dir) if a.images and Path(s.storage_dir).exists() else None

    if not targets and not images:
        print("Rien à supprimer.")
        return
    print("Seront supprimés :")
    for t in targets:
        print(f"  {t}")
    if images:
        print(f"  {images}/ (images chiffrées)")
    if input("Confirmer ? Tapez « oui » : ").strip().lower() != "oui":
        print("Annulé.")
        return
    for t in targets:
        t.unlink()
    if images:
        shutil.rmtree(images)
    print("Base supprimée. Elle sera recréée au prochain démarrage du serveur "
          "(pensez à recréer les comptes : python -m scripts.create_staff).")


if __name__ == "__main__":
    main()
