# Iris – contexte du projet (à lire avant toute modification)

Le projet s'appelle **Iris**. « DayOne » est le nom du défi du hackathon.

Hackathon 48 h, défi **DayOne – The Offline Midwife** (CodeML 2026). Consigne complète :
`docs/consignes-fr-en.pdf`. Équipe francophone : répondre en français.

## Objectif
Agent WhatsApp : la sage-femme photographie son registre maternel papier → extraction
IA locale en JSON structuré (valeur + statut + confiance par champ) → vérification
conversationnelle → liaison des visites d'une même patiente. Le flux papier ne change pas.

## Contraintes non négociables
- **Aucun service tiers d'IA/OCR** (OpenAI, Google Vision...). IA 100 % locale (Ollama...).
- **Aucun identifiant direct stocké** (nom, conjoint, téléphone, adresse, n° national).
  Liste blanche : `app/registry_schema.py::sanitize_extraction`.
- Statuts de champ : CONNU, INCONNU, NON_FOURNI, ILLISIBLE, NON_APPLICABLE, A_REVISER
  (+ confiance 0..1). L'agent ne cache jamais ses doutes.
- Stockage local chiffré ; images d'origine jamais modifiées, accès par rôle.
- Identifiants internes = UUID aléatoires, jamais dérivés d'infos personnelles.

## Données du défi (`data-defi/`, non versionné, ne JAMAIS modifier)
- `data-defi/Paper Registry/` : 129 images = **80 pages spécimen uniques** (+ 44 doublons exacts :
  même sha256, nom suffixé `__xxxx`) + **5 vraies photos** `1-1.jpg`..`1-5.jpg` (vrai carnet rose
  du ministère de la Santé du Maroc, écriture bleue, photos inclinées : 1-1 couverture,
  1-2 identification + antécédents familiaux/femme, 1-3 antécédents obstétricaux,
  1-4 grossesse actuelle T1, 1-5 grossesse actuelle T2→9e mois).
- `dossiers_specimen_10_patientes.pdf` = les 80 pages, 10 patientes fictives × 8 pages, ordre fixe :
  1 couverture, 2 identification + antécédents (+ obstétricaux), 3 grossesse actuelle (tableau de
  visites T1V1..T1V3, T2V1..T2V3, 7e/8e/9e mois), 4 accouchement, 5 post-partum précoce mère,
  6 post-partum précoce nouveau-né, 7 post-partum tardif mère, 8 post-partum tardif nouveau-né.
  PNG `dossiers_specimen_10_patientes-NN` = page NN du PDF.
- Dans le PDF, l'écriture « manuscrite » est du VRAI TEXTE en polices manuscrites (Caveat,
  NanumPen, Gaegu, ReenieBeanie, ShadowsIntoLight) ; l'imprimé est en Helvetica ; les coches
  sont des tracés vectoriels colorés sur des cases 8×8 → vérité terrain extraite
  automatiquement avec pdfplumber. Pièges : chaque page est tournée de ±0,5° (on redresse) ;
  NanumPen n'a pas les accents (`\x00`, blanc sur l'image → `�` = joker à l'évaluation) ;
  le nom de la patiente est aussi IMPRIMÉ dans l'en-tête des pages post-partum mère.
- `maternal_registry_synthetic.csv` (200 lignes) n'est PAS lié aux images : c'est le format
  tabulaire cible (variables clés). Sert à nommer les variables (`csv_column`), aux plages
  plausibles et, plus tard, à un export au même format.

## Barème (100 pts)
Extraction 30 · Incertitude 20 · Flux conversationnel 20 · Hors ligne 15 ·
Liaison + confidentialité 10 · Code/doc 5.
Démo attendue : capture hors ligne → retour réseau → révision d'un champ incertain →
décision de correspondance patiente.

## Configuration WhatsApp réelle (validée le 3 oct., fonctionne de bout en bout)
- App Meta « Iris » (App ID 1427853809299823), **publiée (mode Live)** : sinon les vrais
  messages ne sont pas livrés au webhook (seuls les tests du tableau de bord passent).
- Compte WhatsApp Business (WABA) 1148474560940306 ; numéro de test +1 555 630 9263 ;
  Phone Number ID 1471664049353406 (≠ le numéro !).
- WABA relié à l'app : `POST /v21.0/{WABA_ID}/subscribed_apps` (sinon rien n'arrive).
- Webhook : `https://spotty-salt-salvage.ngrok-free.dev/webhook`, champ « messages » abonné.
- Politique de confidentialité exigée pour publier : `/confidentialite` (servie par l'app).
- Pièges rencontrés : Verify token (inventé) ≠ Access token (EAA…, généré par Meta) ;
  erreur 131005 = jeton sans `whatsapp_business_messaging` sur le WABA (vérifier avec
  `/debug_token` → granular_scopes) → utiliser un jeton du propriétaire du portefeuille
  ou un jeton System User (n'expire pas) ; 131030 = destinataire hors liste « To » ;
  ngrok ≥ 3.20 requis. Le serveur vérifie le .env au démarrage (`check_config`).

## Choix d'architecture (validés avec l'équipe)
- FastAPI + SQLAlchemy 2 ; SQLite par défaut (PostgreSQL via `DATABASE_URL`).
- WhatsApp Cloud API réelle via ngrok ; webhook signé HMAC, idempotent par wamid.
- Identifiants d'états en ASCII (`A_REVISER`, `PATIENTE_LIEE`...), libellés FR dans l'UI.
- Champs extraits stockés en lignes (`ExtractedField`), versionnés via `is_current`.
- Toute réponse WhatsApp passe par l'outbox (`services/outbox.enqueue`), jamais d'envoi direct.
- Contrainte WhatsApp : max 3 boutons → liaison patiente (4 choix) via `list_message`.

## État d'avancement
- [x] **Bloc 1 – Backend** : webhook, BDD, sessions multipages, doublons, outbox,
      worker de rattrapage, images chiffrées, API image à accès restreint, page de
      confidentialité, vérification du .env au démarrage. 15 tests verts. **Testé avec un vrai
      téléphone via WhatsApp Cloud API.**
- [x] **Bloc 2 – Machine à états** : `app/state_machine.py` (table `TRANSITIONS`,
      `transition()` qui lève `InvalidTransition`, gardes : ≥ 1 page avant l'IA, VALIDE
      réservé à `midwife:` sans champ A_REVISER/ILLISIBLE, PATIENTE_LIEE exige `patient_id`,
      révision manuelle après 3 tentatives IA ; `find_duplicate`). `ingest.set_status`
      supprimé. `Record.link_pending` (« Je ne sais pas », bloc 4). Serveur central simulé
      (`CentralRecord`, payload anonymisé) + drapeau `reseau_central` ;
      `services/sync.py` (ECHEC_SYNCHRO puis réessai) ; `services/processing.py` (reprise des
      ECHEC_TRAITEMENT + message WhatsApp). API `POST /api/admin/reseau`, `GET /api/tableau`.
      `scripts/reset_db.py` en cas de changement de schéma. 59 tests verts.
- [x] **Bloc 3a – Vérité terrain & évaluation** : schéma réel du carnet
      `app/templates/carnet_maroc.py` (un carnet = un fichier template ; sections, tableaux à
      clés indexées `grossesse_actuelle.visites.T2V1.poids_kg`, `label_fr` = texte imprimé,
      `csv_column`, `identifiant=True` jamais stocké) ; `registry_schema` en est généré (même
      API). `app/templates/normalize.py` (dates, nombres, TA cmHg→mmHg, SA+j, choix → code).
      `scripts/build_manifest.py` → `eval/manifest.json` ; `scripts/build_ground_truth.py` →
      `eval/ground_truth/specimen_pNN.json` (0 % non rattaché, 1970 cases) + modèles
      `reel_1-X.json` à remplir à la main (voir `eval/ground_truth/README.md`) ;
      `python -m eval.evaluate --pred <dossier>` (exactitude, cases P/R, couverture,
      calibration, NON_FOURNI, erreurs silencieuses, échec bloquant si fuite d'identifiant) ;
      `eval/dummy_predict.py` pour tester l'évaluateur. 72 tests verts.
      Ajustements : `find_duplicate` utilise `state_machine.date_reference(record)` (date de
      consultation post-partum > date d'accouchement > « venue le » la plus récente) et compare
      (type, date) ; comparaison de texte insensible aux accents dans les DEUX sens.
- [x] **Bloc 3b – Cerveau IA local** (`ai/`, détails dans le README « Cerveau IA ») :
      `ollama_client` (schéma JSON, temp. 0, num_ctx 8192, 2 tentatives puis sans format,
      cache `eval/cache/` pour le CLI uniquement), `preprocess` (EXIF, qualité, redressement,
      CLAHE, 3 bandes à 15 % de recouvrement), `classify`, `prompts` (générés depuis le
      template, champs du type de page seulement), `validate` (contrôles croisés),
      `confidence` (plafond 0.85, accord entre bandes, 2e avis, critiques jamais CONNU sur une
      lecture), filtre téléphone/CIN. Normalisation étendue dans `app/templates/normalize.py`
      (pas de doublon `ai/normalize.py`). CLI `python -m ai.extract`, évaluation
      `python -m ai.run_eval` (→ `eval/preds/<run_id>/`, `--calibrate`).
      Backend : `app/services/ai_worker.py` (thread à part, 1 dossier à la fois, pages en
      mémoire, EN_ATTENTE_IA → TRAITE_IA → A_REVISER, Ollama coupé → ECHEC_TRAITEMENT,
      message « photo floue » et « Lecture terminée »), config `AI_*` + `check_config`,
      colonnes `pages.quality_json/page_type`, `extracted_fields.details_json` (candidats,
      drapeaux ; ajoutées automatiquement par `init_db`).
      Constats des tests manuels : RTX 2050 4 Go VRAM, 16 Go RAM ; qwen2.5vl:3b ≈ 25 s/appel,
      qwen2.5vl:7b ≈ 45 s, qwen3-vl:4b ≈ 390 s (exclu). Les modèles lisent bien l'écriture
      claire mais INVENTENT quand on demande un champ absent (DDR = « En milieu surveillé ») ;
      le 7B a halluciné presque tout sur une vraie photo ; le 3B a renvoyé une réponse vide
      (format json) sur une vraie photo → architecture anti-hallucination. Mesuré pendant le
      3b : un objet {raw, etat, confiance} par champ fait dégénérer le 3B (ILLISIBLE partout)
      → format compact ; si toutes les clés sont optionnelles, le 3B répond
      `{"confiance": 0.9}` seul → conteneurs obligatoires ; avec un champ par groupe de
      cases, le 3B coche une option au hasard dans chaque groupe → liste plate des cases
      cochées, jamais CONNU sur une lecture ; num_ctx 4096 ou 8192 : même vitesse (≈ 24 s
      par bande, le temps est dans l'encodage de l'image).
      **Dernière évaluation** (`python -m ai.run_eval --source specimen --limit 8 --calibrate`,
      patiente 1, qwen2.5vl:3b + 2e avis 3b, rapports `eval/reports/3b_*.md`) :
      - passage 1 (avant corrections) : exactitude 25 %, **10 erreurs silencieuses** (toutes des
        cases cochées confirmées à 0.99 par le 2e avis du même modèle), 409 s/page en moyenne
        (couverture 333 s, grossesse 1428 s pour seulement 4 champs : délai dépassé puis plantage
        de grammaire llama.cpp « Unexpected empty grammar stack » sur le tableau), confidentialité OK ;
      - passage 2 (rejoué depuis le cache, 6 pages sans tableau) : exactitude 35 %, **0 erreur
        silencieuse**, champs ≥ 0.8 justes à 100 % (9/9), couverture 79 % ; cases cochées :
        précision 26 %, rappel 60 % (le 3B coche presque toutes les options visibles) ;
        `--calibrate` propose SEUIL_CONNU = 0.61 (13 CONNU, 0 silencieuse) : on garde 0.8 (prudence).
      - Corrections issues de ces mesures : case lue par l'IA jamais CONNU (plafond 0.6) ; libellé
        recopié en tête de valeur retiré ; plafond de sortie par requête (`output_budget`) ;
        500 avec schéma -> repli direct sans schéma ; tableaux découpés en requêtes de 8 lignes.
      - Constats qualitatifs : le 3B lit bien les textes isolés (dates, région, établissement,
        poids, sexe) mais invente des valeurs « typiques » quand il lit mal (pouls 80, T° 36.5,
        TA 110/70, taille 50) -> attrapées en A_REVISER (lectures divergentes) ; dans le tableau
        de visites, il décale les colonnes d'un cran.
      **Pistes** : cases à cocher par vision classique (densité de pixels dans les carrés
      détectés, sans IA générative) ; découpe du tableau par colonnes (une image par visite) ;
      essayer qwen2.5vl:7b en 2e avis sur machine ≥ 6 Go VRAM.
- [x] **Bloc 4 – Conversation & liaison** (README « Flux conversationnel » et « Démo ») :
      `app/services/conversation.py` (état JSON par sage-femme, un dossier à la fois, boutons
      versionnés `<action>|<dossier>|<champ>|<version>` -> réponse périmée ignorée), textes FR/EN
      `app/i18n.py`. Révision : résumé [Vérifier][Reprendre photo][Plus tard], ≤ 10 questions
      (critiques d'abord ; au-delà : source SYSTEME + `champs_a_verifier_superviseur`), candidats
      en liste, correction validée (normalize + validate), nouvelles versions SAGE_FEMME, Voir /
      `CORRIGER n` / Tout confirmer -> VALIDE. Garde VALIDE : ne bloque que les doutes encore
      source IA. Reprendre la photo : `pages.replaced/replaces_page`, A_REVISER -> EN_ATTENTE_IA
      (le worker ignore les pages remplacées). Saisie guidée (REVISION_MANUELLE_REQUISE) : champs
      clés hors tableaux. Liaison : code confirmé ou demandé, candidates de la même sage-femme
      (exact / confusions O0 I1 S5 B8 / 1 erreur), jamais de création automatique, « Je ne sais
      pas » -> `link_pending` + `POST /api/records/{id}/rattacher` (superviseur) + `a_rattacher`
      dans `/api/tableau` ; doublon -> [Mettre à jour][Nouvelle visite][Annuler].
      Démo : `scripts/demo_reset.py`, `scripts/demo_seed.py`. 135 tests verts.
      Limites : la saisie guidée ne couvre pas le tableau des visites ; « Mettre à jour » un
      dossier déjà SYNCHRONISE modifie la copie locale sans le renvoyer au serveur central
      (SYNCHRONISE est un état final du bloc 2).

## Commandes
```bash
uvicorn app.main:app --reload --port 8000
ngrok http 8000
pytest -q
python -m scripts.build_manifest        # inventaire des images -> eval/manifest.json
python -m scripts.build_ground_truth    # vérité terrain spécimen + rapport de rattachement
python -m eval.dummy_predict --noise 0.15 && python -m eval.evaluate --pred eval/preds/dummy
```
