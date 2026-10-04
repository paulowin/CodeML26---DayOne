"""Remet la démo à zéro : dossiers, patientes, sages-femmes, messages, synchro, images chiffrées.

Les comptes du personnel (clés d'API) et le .env ne sont PAS touchés.

    python -m scripts.demo_reset          # demande confirmation
    python -m scripts.demo_reset --yes
"""
import argparse
from pathlib import Path

from app.config import get_settings
from app.db import Base, SessionLocal, init_db

KEEP_TABLES = {"staff"}


def reset() -> dict[str, int]:
    init_db()
    from app import models  # noqa: F401  (enregistre les tables)
    counts = {}
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):       # enfants d'abord (clés étrangères)
            if table.name in KEEP_TABLES:
                continue
            counts[table.name] = db.execute(table.delete()).rowcount
        db.commit()
    store = Path(get_settings().storage_dir)
    n_img = 0
    if store.exists():
        for f in store.glob("*.enc"):
            f.unlink()
            n_img += 1
    counts["images_chiffrees"] = n_img
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    a = ap.parse_args()
    if not a.yes and input("Effacer toutes les données de démo (hors comptes du personnel) ? [o/N] ").lower() != "o":
        print("Annulé.")
        return
    counts = reset()
    print("Remis à zéro :", ", ".join(f"{k}={v}" for k, v in counts.items() if v))


if __name__ == "__main__":
    main()
