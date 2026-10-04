# Nuit du 4 octobre – travail en autonomie

## État au DÉBUT de la nuit (git log -20, git status, lecture du code)

| # | Tâche | État au début | Preuve |
|---|---|---|---|
| 1 | Messages WhatsApp en double (réservation atomique outbox + inbound, verrou, test 2 threads) | FAIT | commit 613666f, tests/test_envoi_unique.py |
| 2 | demo_reset ciblé sur la sage-femme de démo (+ --all, compteurs) ; « (dossier de démonstration) » | À FAIRE | demo_reset effaçait TOUT sauf le personnel |
| 3 | Cases à cocher par OpenCV (ai/checkboxes.py) | FAIT | commit 005cd37 ; 100 % / 100 % sur 8 pages (VLM : 27 % / 60 %) |
| 4 | Page de vérification /verif | FAIT | commit 5847afe, tests/test_verif.py |
| 5 | Résumé lisible après lecture | FAIT (sauf régions) | commit 613666f ; reste : correction vers les 12 régions officielles |
| 6 | Corrections de textes | EN COURS | fait : unités, valeur unique, Lecture 1/2, raison du doute, pluriels, accents, page difficile, simulateur supprimé (8dcd888, b0fabfa) ; reste : attente croissante entre tentatives IA, 1re question envoyée directement en saisie guidée |
| 6 bis | Emojis / ton chaleureux (constantes dans app/i18n.py) | À FAIRE | |
| 7 | Évaluation finale (specimen --limit 24, puis reel) | À FAIRE | |
| 8 | README à jour + DEMO.md | À FAIRE | |

## État à la FIN de la nuit

| # | Tâche | État | Commit(s) |
|---|---|---|---|
| 1 | Messages WhatsApp en double | FAIT (vérifié : tests/test_envoi_unique.py verts) | 613666f |
| 2 | demo_reset ciblé + --all + compteurs ; « (dossier de démonstration) » | FAIT | 6e3c15c |
| 3 | Cases à cocher par OpenCV | FAIT | 005cd37 |
| 4 | Page /verif | FAIT | 5847afe |
| 5 | Résumé lisible + 12 régions officielles | FAIT | 613666f, fd6ef2a |
| 6 | Corrections de textes (attente croissante IA, 1re question de saisie guidée directe) | FAIT | 125d877 (+ 8dcd888, b0fabfa) |
| 6 bis | Emojis / ton chaleureux (constantes dans app/i18n.py) | FAIT | 1465f0c |
| 7 | Évaluation finale (specimen 24 pages + reel 5 photos) | FAIT | fe68280 (+ rapports) |
| 8 | README à jour + DEMO.md | FAIT | f09b0c1 |

Tests : **179 verts** (`pytest -q`, sans GPU ni réseau).

## Choix faits (sans pouvoir te demander)

- **Recalage des cases** : homographie sur les libellés imprimés lus par l'OCR (variante
  « ancrage sur les libellés » de ta consigne) plutôt qu'ORB : pas d'image modèle à embarquer
  (les PNG du spécimen contiennent des noms fictifs et data-defi/ n'est pas versionné).
  Positions des cases extraites une fois du PDF -> `app/templates/carnet_maroc_cases.json`
  (aucune valeur manuscrite). Repli : petits carrés par contours + libellé OCR le plus proche.
- **demo_reset** : par défaut, sages-femmes de démo = numéros passés en argument, sinon celles
  qui ont un dossier `demo_seed` ; la ligne « sage-femme » est gardée (état de conversation remis
  à zéro) car un compte du personnel peut y être rattaché. `--all` = ancien comportement.
- **get_client()** gardé : depuis b0fabfa il renvoie toujours `WhatsAppClient` (le simulateur et
  `app.simulator` sont supprimés) ; c'est la fabrique utilisée partout.
- **Attente entre tentatives IA** : 1 min, 2 min, 4 min (`processing.retry_delay`).
- **Emojis** : une table `EMOJI_PREFIX` dans app/i18n.py décide de l'emoji de chaque message ;
  résumé lisible : ✅ par ligne sûre, ⚪ pour une case non cochée ; 🙏 seulement en fin de dossier ;
  boutons sans emoji sauf « ✅ Tout est juste ». ✉️ et 📡 sont définis mais pas encore utilisés
  côté sage-femme (la synchro centrale est invisible pour elle).
- **Fautes d'OCR** (« Qui », « Nprlaux ») : corrigées vers le vocabulaire du carnet MAIS confiance
  plafonnée à 0,6 -> elles deviennent des questions, plus des erreurs silencieuses.
- **Mode par défaut** : `AI_MODE=ocr`, `AI_OCR_ENGINE=easyocr` (comparaison 3d), `--mode vlm` reste.
- **Seuil CONNU** gardé à 0.8 : `--calibrate` propose 0.86, mais seulement parce qu'aucun champ ne
  dépasse 0.95 (aucune confiance OCR n'atteint ce niveau) ; ce serait « zéro CONNU ».

## Chiffres d'évaluation

Spécimen (vérité terrain extraite du PDF). Avant = VLM qwen2.5vl:3b (bloc 3b, 8 pages de la
patiente 1). Après = OCR EasyOCR + géométrie + cases OpenCV + 2e avis Ollama sur les champs
critiques (24 pages = patientes 1 à 3), `OMP_NUM_THREADS=4`, une page à la fois.

| | Exactitude | Couverture | Erreurs silencieuses | Précision des champs sûrs | Cases P / R | Temps / page |
|---|---|---|---|---|---|---|
| Avant : VLM, 1er passage (8 p.) | 25,0 % | 46,4 % | 10 | 73,7 % | 27,4 % / 60,5 % | 409 s |
| Avant : VLM après corrections (8 p.) | 26,6 % | 48,8 % | 0 | 100 % | 26,8 % / 60,5 % | ~350–400 s* |
| Après : OCR + OpenCV (24 p.) | 73,2 % | 92,2 % | 11 | 97,4 % | 100 % / 71,0 % | 26,9 s |
| **Après + correction des fautes d'OCR (24 p.)** | **74,4 %** | **92,2 %** | **6** | **98,6 %** | **100 % / 71,0 %** | **23,6 s** |

\* rejoué en partie depuis le cache : le temps mesuré (136 s) n'est pas représentatif.
Cases seules, 8 pages de la patiente 1 : VLM 27,4 % / 60,5 % -> OpenCV 100 % / 100 %
(`eval/reports/cases_avant_apres.md`). Confidentialité : 0 fuite sur toutes les évaluations.

Les 6 erreurs silencieuses restantes : texte libre mal lu par l'OCR (« Chuffeur », « AI Haouz »,
« Asthme ger », « Poursuire lallaitement ») et 2 dates (17/05 -> 13/05, 02/11/2025 -> 2025-01-02).
Pistes : vocabulaire des provinces/professions, contrôle « date de RDV postérieure à la visite ».

Vraies photos (5, `--source reel`) : **pas d'exactitude calculable** (la vérité terrain
`eval/ground_truth/reel_1-X.json` n'a pas encore été remplie). 1-1, 1-2, 1-3 reconnues (2 à 5 champs
CONNU chacune) ; **1-4 et 1-5 (grossesse, écriture cursive) non reconnues** -> type « inconnu »,
aucun champ : le dossier passera en saisie guidée. 10 s/page. C'est la limite principale.

## À tester demain matin sur WhatsApp

1. Redémarrer le serveur (nouveau code), puis `python -m scripts.demo_reset 15793661803` et
   `python -m scripts.demo_seed 15793661803` -> message « ✅ Lecture terminée … » précédé de
   « Voici ce que j'ai lu (page 1 – Grossesse actuelle) » (lignes ✅, « 🔒 Non enregistré : nom du soignant »).
2. [✅ Tout est juste] -> questions avec aperçu de la zone (📷, identités masquées) et « Pourquoi je demande ».
3. Question TA : « 🟠 TA : 106/77 mmHg ou 166/77 mmHg ? » (liste « Lecture 1 / Lecture 2 »).
4. Écrire « bonjour » au milieu -> « 👋 Bonjour ! Un dossier attend votre vérification (… questions). »
5. Fin -> liste des patientes -> « ✅ Dossier validé et relié à la patiente A64125. Merci 🙏 ».
6. Envoyer une vraie photo + [Terminé] -> « ⏳ Je lis votre registre… (environ 1 minute) » ; vérifier
   qu'il n'y a plus de réponse en double ; ouvrir le lien `/verif/<id>` écrit dans le terminal.
7. Renvoyer la même photo -> « 📷 Cette photo a déjà été reçue (dossier …, page 1), je ne l'ajoute pas. »
8. Écrire `RESUME`, `EN`, `CONTINUE`, `FR`, `AIDE`.

Attention : la 1re lecture charge EasyOCR (~10 s de plus) ; garder Ollama lancé pour le 2e avis.
