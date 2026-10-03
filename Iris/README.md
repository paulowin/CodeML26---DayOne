# DayOne – The Offline Midwife

Agent WhatsApp qui transforme la photo d'un registre maternel papier en dossier
numérique structuré, vérifié par la sage-femme et relié de visite en visite.
**Tout tourne en local** : aucune donnée n'est envoyée à un service d'IA/OCR tiers.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows : copy .env.example .env
python scripts/gen_key.py            # -> coller dans STORAGE_ENCRYPTION_KEY du .env
```

Remplir ensuite les valeurs `WHATSAPP_*` du `.env` (voir ci-dessous).

## Lancer

```bash
uvicorn app.main:app --reload --port 8000     # terminal 1
ngrok http 8000                               # terminal 2 (ou --url=<domaine-fixe>)
pytest -q                                     # tests
```

## Configuration WhatsApp (une fois)

1. developers.facebook.com → créer une app → ajouter le produit **WhatsApp**.
2. **API Setup** : noter `Phone Number ID`, le jeton d'accès, le numéro de test ;
   ajouter les numéros de l'équipe comme destinataires autorisés (max 5).
3. Paramètres de l'app → Général : noter l'**App Secret**.
4. **WhatsApp → Configuration → Webhook** :
   - URL de rappel : `https://<ton-domaine-ngrok>/webhook`
   - Jeton de vérification : la valeur de `WHATSAPP_VERIFY_TOKEN`
   - S'abonner au champ **messages**.
5. Envoyer une photo au numéro de test depuis son téléphone.

> ⚠️ Le jeton temporaire expire après 24 h : créer un jeton permanent (System User)
> pour le hackathon. Réserver le domaine ngrok gratuit fixe pour ne pas
> reconfigurer Meta à chaque redémarrage.

## Comptes d'accès aux images

```bash
python -m scripts.create_staff --label "Superviseur" --role SUPERVISEUR
python -m scripts.create_staff --label "SF Aicha" --role SAGE_FEMME --midwife-wa-id 2126XXXXXXXX
curl -H "X-API-Key: dk_..." http://localhost:8000/api/records/<id>
curl -H "X-API-Key: dk_..." http://localhost:8000/api/records/<id>/pages/1/image -o page1.jpg
```

## Architecture (bloc 1)

```
Téléphone → Meta → ngrok → POST /webhook
   1. vérifie la signature HMAC (X-Hub-Signature-256)
   2. persiste le message (idempotent par wamid)  → 200 OK immédiat
   3. tâche de fond : télécharge la photo, la chiffre, l'ajoute au dossier ouvert
   4. réponse mise dans l'outbox puis envoyée
Worker (toutes les 20 s) : rejoue les messages en échec, ferme les sessions
expirées, renvoie l'outbox → aucun message perdu si le réseau tombe.
```

| Fichier | Rôle |
|---|---|
| `app/main.py` | App FastAPI + worker de rattrapage |
| `app/routers/webhook.py` | Webhook Meta (vérification + réception) |
| `app/routers/records.py` | API personnel : dossier + image, accès par rôle, journalisé |
| `app/services/ingest.py` | Parsing, sessions multipages, doublons, commandes FIN/ANNULER |
| `app/services/outbox.py` | File d'envoi persistante |
| `app/models.py` | Schéma BDD + énumérations d'états |
| `app/registry_schema.py` | Schéma des champs du registre + liste blanche anti-identifiants |
| `app/storage.py` | Stockage chiffré (Fernet) des images d'origine |
| `app/whatsapp.py` | Client Graph API + constructeurs de messages (texte, boutons, liste) |

## Choix de conception

- **Confidentialité** : aucune colonne nom/téléphone/adresse de patiente ; liste
  blanche stricte des champs ; payload brut, nom de profil et légendes jamais stockés.
- **Images** : chiffrées (Fernet), nom de fichier opaque, SHA-256 pour intégrité et
  doublons, jamais modifiées, accès par rôle avec journal.
- **Hors ligne** : l'horodatage WhatsApp (heure de prise) sert à regrouper les pages,
  pas l'heure de réception ; file entrante + outbox persistantes.
- **Champs en lignes** (`extracted_fields`) : valeur + statut + confiance + source +
  historique des corrections pour chaque champ.

## Limites connues

- Les photos transitent par l'infrastructure WhatsApp (canal imposé par le défi) ;
  le traitement IA est 100 % local.
- La base SQLite n'est pas chiffrée (les images le sont) ; piste : SQLCipher ou
  chiffrement disque.
- Une image chiffrée peut rester orpheline si le traitement plante juste après l'écriture.
