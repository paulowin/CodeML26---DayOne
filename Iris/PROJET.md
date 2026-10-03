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
- [ ] **Bloc 2 – Machine à états** : `app/state_machine.py` avec table des transitions
      autorisées ; remplacer `ingest.set_status` (qui n'applique aucune règle pour l'instant)
      par une fonction qui lève une erreur sur transition interdite. États d'échec :
      ECHEC_TRAITEMENT, ECHEC_SYNCHRO, DOUBLON_SUSPECT, REVISION_MANUELLE_REQUISE, ANNULE.
      Tests : couper le « réseau » à chaque étape.
- [ ] **Bloc 3 – Cerveau IA local** : script indépendant `ai/extract.py` (Ollama +
      modèle vision, ou PaddleOCR + LLM local) prenant des images → JSON
      `{ "section.champ": {value, status, confidence, raw_text, page} }` conforme à
      `registry_schema.SECTIONS`. Le worker prend les dossiers EN_ATTENTE_IA, appelle le
      script, passe `sanitize_extraction`, écrit les `ExtractedField`, puis TRAITE_IA →
      A_REVISER ou VALIDE. Contrôles de plausibilité (`FieldDef.plausible`) → A_REVISER.
      Évaluer sur le jeu de données synthétique (CSV de référence).
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
```
