# Iris – The Offline Midwife

> Projet de l'équipe Iris pour le défi **DayOne** (hackathon CodeML 2026).

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
| `app/state_machine.py` | Machine à états des dossiers (transitions, gardes, doublons) |
| `app/services/sync.py` | Synchronisation vers le serveur central simulé |
| `app/services/processing.py` | Reprise des échecs de lecture IA |
| `app/routers/admin.py` | Bascule du réseau central + tableau de bord (ADMIN/SUPERVISEUR) |
| `app/models.py` | Schéma BDD + énumérations d'états |
| `app/registry_schema.py` | Schéma des champs du registre + liste blanche anti-identifiants |
| `app/storage.py` | Stockage chiffré (Fernet) des images d'origine |
| `app/whatsapp.py` | Client Graph API + constructeurs de messages (texte, boutons, liste) |

## Cycle de vie des enregistrements (bloc 2)

Chaque dossier (un registre photographié) suit une machine à états stricte
(`app/state_machine.py`). Tout changement d'état passe par `transition()`, qui
refuse les passages non prévus (`InvalidTransition`) et trace chaque étape dans
`record_events` (avant, après, acteur, note).

```
            (création)
                │
                ▼
            CAPTURE ──────────────────────────────────────────┐
                │ FIN / fermeture auto (≥ 1 page)              │
                ▼                                              │
  ┌──────► EN_ATTENTE_IA ──────────► ECHEC_TRAITEMENT          │
  │             │                    │   (< 3 essais : retour  │
  │             ▼                    │    en file)             │
  │         TRAITE_IA                │ (≥ 3 essais)            │
  │             │                    ▼                         │
  │             ▼              REVISION_MANUELLE_REQUISE ──┐   │
  └─photo── A_REVISER ─────────────► │                     │   │
   reprise      │ la sage-femme      │                     │   │
                ▼ valide             ▼                     ▼   ▼
              VALIDE ◄───────────────┘                   ANNULE
                │ └────────► DOUBLON_SUSPECT ──────────────► ▲
                ▼                    │                       │
          PATIENTE_LIEE ◄────────────┘
                │
                ▼
           ENREGISTRE ──► ECHEC_SYNCHRO (réseau central coupé)
                │               │ réessai à chaque cycle
                ▼               ▼
           SYNCHRONISE ◄────────┘          (SYNCHRONISE et ANNULE sont finaux)
```

| Depuis | Vers (autorisé) | Garde |
|---|---|---|
| *(création)* | CAPTURE | |
| CAPTURE | EN_ATTENTE_IA, ANNULE | au moins 1 page pour EN_ATTENTE_IA |
| EN_ATTENTE_IA | TRAITE_IA, ECHEC_TRAITEMENT, ANNULE | |
| ECHEC_TRAITEMENT | EN_ATTENTE_IA, REVISION_MANUELLE_REQUISE | révision manuelle seulement après 3 tentatives IA |
| TRAITE_IA | A_REVISER | l'IA ne valide jamais seule |
| A_REVISER | VALIDE, EN_ATTENTE_IA (photo reprise), REVISION_MANUELLE_REQUISE, ANNULE | |
| REVISION_MANUELLE_REQUISE | VALIDE, ANNULE | |
| VALIDE | PATIENTE_LIEE, DOUBLON_SUSPECT | |
| DOUBLON_SUSPECT | PATIENTE_LIEE, ANNULE | |
| PATIENTE_LIEE | ENREGISTRE | |
| ENREGISTRE | SYNCHRONISE, ECHEC_SYNCHRO | |
| ECHEC_SYNCHRO | SYNCHRONISE | |
| SYNCHRONISE, ANNULE | — (finaux) | |

Gardes transverses :
- **→ VALIDE** : l'acteur doit être la sage-femme (`midwife:<id>`) et aucun champ
  courant ne doit rester `A_REVISER` ou `ILLISIBLE`.
- **→ PATIENTE_LIEE** : une patiente doit être rattachée (`patient_id`). « Je ne sais
  pas » laisse le dossier VALIDE avec `link_pending = True` : pas de création automatique.
- Les états d'échec (`ECHEC_*`, `DOUBLON_SUSPECT`, `REVISION_MANUELLE_REQUISE`)
  renseignent `failure_reason`, qui est vidé dès que le dossier en sort.
- `find_duplicate()` signale un autre dossier ENREGISTRE/SYNCHRONISE de la même
  patiente avec la même `identification.date_visite`.

Le worker (toutes les 20 s) remet en file les ECHEC_TRAITEMENT (< 3 essais) ou les passe
en révision manuelle en prévenant la sage-femme, puis synchronise les dossiers ENREGISTRE /
ECHEC_SYNCHRO vers le serveur central.

### Démo hors ligne (serveur central simulé)

Le « serveur du ministère » est simulé par la table `central_records`. Il ne reçoit
que des données anonymisées : UUID du dossier et de la patiente, date de capture et
champs courants. Il ne reçoit ni image ni numéro WhatsApp. Le drapeau `reseau_central`
simule la coupure (clé API ADMIN ou SUPERVISEUR requise) :

```bash
# couper le réseau central
curl -X POST http://localhost:8000/api/admin/reseau -H "X-API-Key: dk_..." \
     -H "Content-Type: application/json" -d '{"en_ligne": false}'
# observer : les dossiers ENREGISTRE passent en ECHEC_SYNCHRO
curl -H "X-API-Key: dk_..." http://localhost:8000/api/tableau
# rallumer : au cycle suivant (≤ 20 s), ils passent en SYNCHRONISE
curl -X POST http://localhost:8000/api/admin/reseau -H "X-API-Key: dk_..." \
     -H "Content-Type: application/json" -d '{"en_ligne": true}'
```

> Sous PowerShell, utiliser `curl.exe` et échapper les guillemets du JSON, ou
> `Invoke-RestMethod -Method Post -Headers @{"X-API-Key"="dk_..."} -ContentType "application/json" -Body '{"en_ligne": false}' http://localhost:8000/api/admin/reseau`.

### Changement de schéma

SQLite `create_all` n'ajoute pas les nouvelles colonnes aux tables existantes. Après
une mise à jour du schéma : `python -m scripts.reset_db` (option `--images` pour
effacer aussi les images chiffrées), puis recréer les comptes avec `scripts.create_staff`.

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
