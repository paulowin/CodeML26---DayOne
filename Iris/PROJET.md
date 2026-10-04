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
      À reprendre : `state_machine.find_duplicate` lit `identification.date_visite`, qui
      n'existe plus dans le schéma réel (→ date de visite = `visites.<COL>.venue_le` ou
      `date_consultation`, bloc 3b/4).
- [ ] **Bloc 3b – Cerveau IA local** : script indépendant `ai/extract.py` (Ollama +
      modèle vision, ou PaddleOCR + LLM local) prenant des images → JSON
      `{"image": ..., "fields": {"section.champ": {value, status, confidence, raw_text, page}}}`
      conforme au template (évaluable directement par `eval.evaluate`). Le worker prend les dossiers EN_ATTENTE_IA, appelle le
      script, passe `sanitize_extraction`, écrit les `ExtractedField`, puis TRAITE_IA →
      A_REVISER (l'IA ne valide jamais seule : seule la sage-femme fait passer en VALIDE) ;
      en cas d'erreur → ECHEC_TRAITEMENT et `ai_attempts += 1`. Contrôles de plausibilité (`FieldDef.plausible`) → A_REVISER.
      Évaluer avec `eval.evaluate` (spécimen puis photos réelles).
- [ ] **Bloc 4 – Conversation & liaison** : `Midwife.conversation_state` (JSON) ;
      point d'entrée : `ingest._handle_text` (branche `else`). Confirmer / Corriger /
      Reprendre la photo pour chaque champ A_REVISER/ILLISIBLE ; saisie manuelle si IA
      indisponible ; liaison par code : [Patiente 1] [Patiente 2] [Aucune, créer]
      [Je ne sais pas], jamais de création automatique ; re-photographie d'un registre
      existant → montrer le dossier et laisser choisir.

## Commandes
```bash
uvicorn app.main:app --reload --port 8000
ngrok http 8000
pytest -q
python -m scripts.build_manifest        # inventaire des images -> eval/manifest.json
python -m scripts.build_ground_truth    # vérité terrain spécimen + rapport de rattachement
python -m eval.dummy_predict --noise 0.15 && python -m eval.evaluate --pred eval/preds/dummy
```
