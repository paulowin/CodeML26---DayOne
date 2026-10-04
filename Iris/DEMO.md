# Démo Iris – scénario de 5 minutes (brouillon)

Démo attendue par le défi : **capture hors ligne → retour réseau → révision d'un champ incertain →
décision de correspondance patiente**. Données fictives uniquement (pages spécimen).

## Préparation (avant de monter sur scène, 2 min)

```bash
ollama serve                                   # 2e avis local
uvicorn app.main:app --port 8000               # terminal 1
ngrok http --url=spotty-salt-salvage.ngrok-free.dev 8000   # terminal 2
python -m scripts.demo_reset --yes             # ne touche qu'à la sage-femme de démo
python -m scripts.demo_seed 15793661803        # 2 patientes + un dossier « à vérifier » (fictif)
```

Ouvrir dans le navigateur du poste : `http://127.0.0.1:8000/verif` (deuxième écran) et
`http://127.0.0.1:8000/api/tableau` (avec la clé superviseur).

## Déroulé

| Temps | Écran | Ce qu'on montre | Ce qu'on dit |
|---|---|---|---|
| 0:00 | Téléphone | Photo d'une page du carnet → « 📷 Page 1 reçue. Envoyez la suivante ou appuyez sur Terminé. » | Le flux papier ne change pas : la sage-femme photographie son registre. |
| 0:30 | Terminal | `POST /api/admin/reseau {"en_ligne": false}` | Le centre de santé perd le réseau central. |
| 0:40 | Téléphone | [Terminé] → « ⏳ Je lis votre registre… (environ 1 minute) » | Tout est lu sur ce PC : OCR local, cases par vision, aucun service tiers. |
| 1:30 | Téléphone | « Voici ce que j'ai lu (page 1 – …) » : ✅ lignes sûres, 🟠 à vérifier, 🔒 « Non enregistré : nom de la patiente » | L'IA ne cache jamais ses doutes ; le nom n'est jamais stocké. |
| 2:00 | Téléphone | Dossier de démo : question « 🟠 TA : 138/89 mmHg ou 198/89 mmHg ? » + aperçu de la zone (identités masquées) → choisir 138/89 | Deux lectures différentes : c'est la sage-femme qui tranche, en un geste. |
| 2:40 | Téléphone | DDR « incohérente avec la DPA » → [Corriger] → taper `31/02/2025` (refusé, format réexpliqué) → `14/04/2025` | Les corrections passent par les mêmes contrôles que l'IA. |
| 3:20 | Téléphone | [✅ Tout est juste] → « ⚠️ Signes d'alerte : HTA sévère, pré-éclampsie possible, TA en hausse, anémie (Hb 10,9)… À évaluer selon le protocole. » → liste « Patiente 1 – code A64125 – 3 visites » / « Patiente 2 – A64128 (code proche) » / Aucune / Je ne sais pas → Patiente 1 | Jamais de création automatique : la correspondance est toujours une décision humaine. |
| 3:40 | Téléphone | Taper `RDV` → « 📅 2 patientes attendues non revues : A64128 (RDV 05/01) ; A64125 (RDV 13/01). » | Le registre devient un outil de suivi : qui n'est pas revenue. |
| 3:50 | Navigateur | `/verif/<dossier>` : bandeau rouge des alertes, image à gauche, champs, sources (ocr / case / sage-femme) | Aide à la décision, jamais un diagnostic. Traçabilité : chaque valeur, sa source et son historique. |
| 4:20 | Terminal + tableau | Dossier ENREGISTRE → ECHEC_SYNCHRO ; `{"en_ligne": true}` → SYNCHRONISE (≤ 20 s) | Hors ligne d'abord : rien n'est perdu, tout part au retour du réseau, sans doublon. |
| 4:50 | Téléphone | « ✅ Dossier validé et relié à la patiente A64125. Merci 🙏 » | Fin. |

## Chiffres à citer (voir NUIT.md, eval/reports/)

- Pages spécimen : exactitude et erreurs silencieuses de l'évaluation finale (NUIT.md).
- Cases à cocher (24 pages) : précision 100 %, rappel 96,4 %, 0 erreur silencieuse (OpenCV) contre 71 % de rappel et 6 erreurs silencieuses pour le VLM.
- Photo WhatsApp réelle (page grossesse) : 6 → 68 valeurs lues, 0 erreur silencieuse.
- Confidentialité : 0 fuite d'identifiant sur toutes les évaluations ; noms, CIN, téléphones
  jamais stockés ni envoyés.

## Plan B

- Ollama ou OCR en panne, ou lecture > 75 s par page → « ⏳ … nous allons le saisir ensemble » : saisie guidée (questions une à une).
- Image du jury non reconnue → « 🟠 De quelle page s'agit-il ? » (liste) → relecture avec ce type, sinon saisie guidée.
- Pas de réseau WhatsApp → montrer `/verif` + `python -m ai.run_eval --files dossiers_specimen_10_patientes-04.png`.
