"""Crée un compte personnel et affiche sa clé API (une seule fois).

Usage :
  python -m scripts.create_staff --label "Superviseur" --role SUPERVISEUR
  python -m scripts.create_staff --label "SF Aicha" --role SAGE_FEMME --midwife-wa-id 2126XXXXXXXX
"""
import argparse

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Midwife, Role, Staff
from app.security import hash_api_key, new_api_key


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--role", required=True, choices=[r.value for r in Role])
    p.add_argument("--midwife-wa-id", help="numéro WhatsApp de la sage-femme (rôle SAGE_FEMME)")
    a = p.parse_args()
    init_db()
    with SessionLocal() as db:
        midwife_id = None
        if a.midwife_wa_id:
            mw = db.scalar(select(Midwife).where(Midwife.wa_id == a.midwife_wa_id))
            if not mw:
                mw = Midwife(wa_id=a.midwife_wa_id)
                db.add(mw)
                db.flush()
            midwife_id = mw.id
        key = new_api_key()
        db.add(Staff(label=a.label, role=Role(a.role), api_key_hash=hash_api_key(key), midwife_id=midwife_id))
        db.commit()
    print(f"Compte créé. Clé API (à conserver, non récupérable) :\n{key}")


if __name__ == "__main__":
    main()
