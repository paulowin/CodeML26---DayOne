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

Au démarrage, `init_db` ajoute automatiquement les colonnes **nullables** manquantes
(mini-migration). Pour tout autre changement (colonne obligatoire, type modifié) :
`python -m scripts.reset_db` (option `--images` pour effacer aussi les images chiffrées),
puis recréer les comptes avec `scripts.create_staff`.

## Cerveau IA (bloc 3)

100 % local : [Ollama](https://ollama.com) + un modèle vision-langage. Aucune image ni
aucun texte ne quitte la machine.

```bash
ollama pull qwen2.5vl:3b                      # modèle principal (≈ 3,6 Go)
python -m ai.extract photo.jpg --out res.json # une ou plusieurs pages, en CLI
python -m ai.run_eval --source specimen --limit 8 --calibrate   # évaluation + seuil proposé
```

**Modèles** (RTX 2050 4 Go, 16 Go RAM) : `qwen2.5vl:3b` ≈ 25 s/appel (retenu) ;
`qwen2.5vl:7b` ≈ 45 s mais a halluciné presque tout sur une vraie photo ; `qwen3-vl:4b`
≈ 390 s (exclu). Réglages : `AI_MODEL_MAIN`, `AI_MODEL_VERIFY` (2e avis), `AI_SEUIL_CONNU`,
`AI_NUM_CTX`, `AI_NUM_PREDICT` (plafond de sortie : sans lui, le 3B a bouclé plus de 15 min sur une bande ; une sortie tronquée est réparée en gardant les paires complètes), `OLLAMA_URL`, `AI_ENABLED`.

**Pipeline** (`ai/`, indépendant de la base) :

1. `preprocess` : orientation EXIF, contrôle qualité (flou = variance du Laplacien,
   luminosité, résolution), redressement, contraste (CLAHE), 3 bandes horizontales
   qui se recouvrent de 15 %, ≤ 1280 px. Tout reste en mémoire.
2. `classify` : type de page (mots-clés sur les titres recopiés par le modèle, sinon
   choix fermé du modèle).
3. `prompts` : pour chaque bande, un prompt généré depuis le template avec **uniquement**
   les champs de ce type de page (libellé imprimé, type, choix), jamais les identifiants.
4. `normalize` (dans `app/templates/normalize.py`, partagé avec l'évaluateur) : RAS,
   nég/pos, tiret -> NON_APPLICABLE, vide -> NON_FOURNI, dates -> ISO, « 16SA+3j »,
   TA « 11/7 » (cmHg) -> 110/70 mmHg, glycémie g/L -> mg/dL, « 1G », « 00 »...
5. `validate` : plages du template, gestité ≥ parité, enfants vivants ≤ parité + 1,
   TA sys > dia, DPA ≈ DDR + 280 j, âge gestationnel cohérent avec DDR et date de visite,
   poids de naissance cohérent avec l'âge gestationnel.
6. `confidence` : voir ci-dessous ; 2e avis (`AI_MODEL_VERIFY`) sur les champs
   critiques, les cases cochées et les champs douteux.
7. Confidentialité : liste blanche du schéma + suppression de tout texte qui ressemble
   à un téléphone (`0[5-7]` + 8 chiffres) ou à une CIN.

**Anti-hallucination** (constat : les modèles inventent quand on demande un champ absent,
ex. DDR = « En milieu surveillé ») :
- on ne demande que les champs du type de page, et toutes les clés sont optionnelles :
  le modèle n'inclut que ce qu'il voit dans la bande, et une clé omise ne produit **rien** ;
- une « valeur » égale à un libellé imprimé de la page est rejetée (`libelle_recopie`) ;
- toute clé inventée par le modèle est ignorée ;
- cases à cocher : une seule liste des cases vraiment cochées, sans un champ par groupe
  (le 3B coche alors une option au hasard dans chaque groupe). Une case lue par l'IA n'est
  **jamais CONNU** (confiance plafonnée à 0.6) : mesuré, le 3B confirme ses propres cases
  inventées au 2e avis ;
- tableaux découpés en requêtes de 8 lignes ; plafond de tokens par requête ; un schéma qui
  fait planter llama.cpp (erreur 500) est abandonné pour un essai sans schéma ;
- format compact (`"champs": {clé: texte}`) : un objet `{raw, etat, confiance}` par
  champ fait dégénérer le 3B (« ILLISIBLE, 0.5 » partout).

**Confiance et statut** : confiance déclarée par le modèle (plafonnée à 0.85), + 0.10 si
deux bandes lisent la même chose, + 0.15 si le 2e avis confirme ; désaccord -> ≤ 0.5 avec
`candidates` (« J'ai lu 11/7 ou 17/7 ? », bloc 4) ; échec de validation -> ≤ 0.4.
Tiret -> NON_APPLICABLE, vide -> NON_FOURNI, illisible -> ILLISIBLE, confiance ≥
`AI_SEUIL_CONNU` -> CONNU, sinon A_REVISER. Les champs **critiques** (VIH, syphilis, Ag HBs,
TA, Hb, glycémie, poids de naissance, date d'accouchement, gestité, parité, enfants vivants,
DDR, DPA) ne sont jamais CONNU sur une seule lecture.

**Backend** : `app/services/ai_worker.py`, déclenché par le cycle de maintenance, lit
un dossier EN_ATTENTE_IA à la fois dans un thread à part (pages déchiffrées en mémoire),
écrit les `ExtractedField` (source IA, page, candidats et drapeaux dans `details_json`),
puis EN_ATTENTE_IA -> TRAITE_IA -> A_REVISER (la sage-femme confirme toujours).
Ollama coupé -> ECHEC_TRAITEMENT (reprise automatique, 3 tentatives). Photo floue ou
sombre -> message « pouvez-vous la reprendre ? ». Fin -> « Lecture terminée : X champs
lus, Y à vérifier ».

**Évaluation** : `python -m ai.run_eval` écrit `eval/preds/<run_id>/`, puis lance
`eval.evaluate` (rapport `eval/reports/<run_id>.md`). Le résumé affiche d'abord
l'exactitude globale, les erreurs silencieuses (faux + CONNU), le temps moyen par page et
le top 15 des champs ratés. Le cache `eval/cache/` (réponses du modèle) permet de
réévaluer sans relancer le modèle (`--no-cache` pour l'ignorer) ; le worker ne l'utilise jamais.

## Flux conversationnel (bloc 4)

`app/services/conversation.py` ; textes FR/EN dans `app/i18n.py` (commande `EN` / `FR`).
Un seul dossier en conversation à la fois par sage-femme (état JSON dans
`Midwife.conversation_state`) ; les autres attendent leur tour. Chaque bouton porte
`<action>|<dossier>|<champ>|<version>` : une réponse périmée (arrivée en retard après une
coupure) reçoit « Cette question n'est plus d'actualité. » et ne change rien.

Exemple d'échange (démo) :

```
Iris : Lecture terminée (dossier 3f2a9c1b) : 150 champ(s) lu(s), 5 à vérifier.
       [Vérifier] [Reprendre photo] [Plus tard]
SF   : Vérifier
Iris : Question 1/5 – Grossesse actuelle · DDR
       J'ai lu : « 26/04/2025 ». Je ne suis pas sûre de cette lecture.
       [Confirmer] [Corriger] [Illisible]
SF   : Corriger
Iris : Tapez la bonne valeur pour : Grossesse actuelle · DDR
       Format : une date jj/mm/aaaa, ex. 03/02/2026
SF   : 27/04/2025
Iris : Question 2/5 – Grossesse actuelle · 2ème trimestre, Visite 2 · TA
       Les deux lectures ne sont pas d'accord. Laquelle est écrite sur le registre ?
       (liste) 106/77 mmHg · 166/77 mmHg · Autre valeur · Illisible sur le papier · Reprendre la photo
...
Iris : Les 145 autres champs lus vous conviennent ?   [Tout confirmer] [Voir]
SF   : Tout confirmer
Iris : Dossier 3f2a9c1b validé ✅
Iris : Code A64125. À quelle patiente rattacher ce dossier ?
       (liste) Patiente 1 – code A64125 – 3 visite(s), dernière 01/12
               Patiente 2 – code A64128 – 1 visite(s), dernière 15/12
               Aucune, créer · Je ne sais pas
SF   : Patiente 1
Iris : Dossier 3f2a9c1b enregistré pour la patiente code A64125 ✅
```

- Questions : champs A_REVISER/ILLISIBLE de l'IA, critiques d'abord, 10 au maximum (le reste
  est confié au superviseur : `champs_a_verifier_superviseur` dans `/api/tableau`).
- Chaque réponse crée une **nouvelle version** du champ (source SAGE_FEMME), l'ancienne est
  gardée (`is_current=False`). Une correction passe par la normalisation + les validations ;
  si elle est invalide, le format attendu est réexpliqué (« TA au format 12/7 ou 120/70 »).
- Commandes : `OK`, `CORRIGER <n>` (après « Voir »), `PLUS TARD` / `STOP`, `REPRENDRE`,
  `AIDE`, `EN` / `FR`. « Reprendre la photo » : la photo suivante remplace la page
  (l'ancienne est conservée, marquée remplacée) et le dossier repart en lecture IA.
- Saisie guidée (`REVISION_MANUELLE_REQUISE`) : champs clés (colonne du CSV ou critiques,
  hors tableaux), « passer » = vide, puis VALIDE.

Liaison patiente (après VALIDE) :

```
code = n° de fiche confirmé  ──(absent)──> « Quel est le code de la patiente ? »
   │
   ▼  patientes de CETTE sage-femme : code exact, puis proche (1 erreur, O/0 I/1 S/5 B/8), max 2
┌──────────────┬───────────────────────────────┬────────────────────────────────┐
│ Patiente n   │ Aucune, créer                  │ Je ne sais pas                 │
│   │          │   └─> nouvelle Patient (UUID)  │   └─> reste VALIDE, link_pending│
│   ▼          │                                │       superviseur : POST        │
│ doublon ? ── oui ─> DOUBLON_SUSPECT            │       /api/records/{id}/rattacher│
│   │            [Mettre à jour] [Nouvelle visite] [Annuler]                       │
│   non                                                                           │
│   ▼                                                                             │
│ PATIENTE_LIEE -> ENREGISTRE -> (synchro bloc 2) SYNCHRONISE                     │
└─────────────────────────────────────────────────────────────────────────────────┘
```
Jamais de création automatique, même si le code est identique ; aucune donnée nominative
dans les messages (code de registre, nombre de visites, date de la dernière).

## Démo

```bash
python -m scripts.demo_reset --yes          # efface dossiers/patientes/messages (garde les comptes et le .env)
python -m scripts.demo_seed 2126XXXXXXXX    # numéro WhatsApp de la sage-femme (sans +)
```

`demo_seed` crée 2 patientes (A64125 : 3 visites synchronisées ; A64128 : 1 visite) et un
dossier A_REVISER construit depuis la vérité terrain de la page spécimen 3 (données
fictives), avec 5 champs douteux dont une TA à 2 lectures : la démo ne dépend pas des
minutes de lecture IA. Scénario : couper le réseau central (`/api/admin/reseau`) → vérifier
sur le téléphone (corriger la DDR, choisir la TA, déclarer l'hémoglobine illisible) → Tout
confirmer → choisir « Patiente 1 » (A64128 est aussi proposée, code proche) → dossier
ENREGISTRE en ECHEC_SYNCHRO → rallumer le réseau → SYNCHRONISE.

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
