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

## Matin — zéro erreur silencieuse

### Cases à cocher (24 pages spécimen, `scripts/eval_cases.py`)
| | précision | rappel | à réviser / champs cases | erreurs silencieuses |
|---|---|---|---|---|
| avant (VLM 3b) | 100 % | 71,0 % | 23 / 225 | 6 |
| après (OpenCV, coches noires + « rien coché » = à vérifier) | 100 % | **96,4 %** | 88 / 225 | **0** |

### Test réel WhatsApp — page « Grossesse actuelle », patiente 9 (dossier 2d70ffd6)
Diagnostic (image reçue 1131×1600 px, 196 Ko vs page PDF 1654×2339 px) : l'OCR lisait bien le texte
(151 lignes contre 171), mais la photo compressée perdait les chiffres des en-têtes (« Visite » au lieu de
« Visite 1 », « Bème mois ») -> la grille du tableau n'était pas trouvée (0 cellule au lieu de 93).

Correctifs :
- en-têtes de tableau : 2e passe tolérante (chiffre perdu accepté, l'ordre fixe la colonne ; « Visites »
  refusé) utilisée SEULEMENT si la passe stricte échoue -> aucun changement sur les scans nets ;
- photo basse résolution (ligne < 20 px) : cellules chiffrées (poids, TA, HU, BCF…) relues agrandies x3
  (cubique + netteté, chiffres seulement) ; désaccord -> à vérifier ;
- « 74 . » (séparateur suivi de rien) -> drapeau `decimale_manquante`, raison « un chiffre semble manquer » ;
- DDR / DPA / date de dépassement cohérentes entre elles (DPA = DDR + 280 j ± 3, DDT = DPA + 7 à 14 j) ->
  CONNU 0,9 (sauf désaccord, 2e avis contraire ou autre drapeau) ;
- aide : « 📎 Pour une meilleure lecture, envoyez la photo comme document » (déjà acceptée par `ingest`).

Mesure vs vérité terrain de la page 67 (pipeline complet + 2e avis) :

| | valeurs lues | dont visites | exactitude | champs couverts justes | erreurs silencieuses | durée |
|---|---|---|---|---|---|---|
| avant | 6 | 0 | 4,2 % | 66,7 % | 0 | 30 s |
| après | 68 | 62 | **66,3 %** | **92,6 %** | **0** (1 avant la règle « 74 . ») | 50 s |

Reste à faire : relancer l'éval spécimen complète des 24 pages avec tous les correctifs du matin.

## Lots de l'après-midi (avant le gel)

### Lot 1 – Robustesse sur image inconnue
Choix (temps) : échantillon de 24 images au lieu de 85 — les 5 réelles, les 16 pages des patientes
1 et 9 (tous les types de page), et 3 images piégées (noire, floue, sans rapport). Pipeline complet
(worker réel, OCR + 2e avis Ollama, base SQLite temporaire), une image à la fois, `OMP_NUM_THREADS=4`.
Ajout : **budget global de 75 s par page** -> au-delà, « ⏳ La lecture prend trop de temps… nous allons
le saisir ensemble » + saisie guidée (pas de relance : elle serait aussi lente).

| image | type reconnu | champs | durée | plantage | comportement |
|---|---|---|---|---|---|
| 1-1.jpg | couverture | 7 | 27 s | non | résumé |
| 1-2.jpg | identification_antecedents | 6 | 18 s | non | résumé |
| 1-3.jpg | identification_antecedents | 7 | 25 s | non | résumé |
| 1-4.jpg | — | 0 | 9 s | non | 🟠 « De quelle page s'agit-il ? » |
| 1-5.jpg | — | 0 | 9 s | non | 🟠 « De quelle page s'agit-il ? » |
| spécimen p01.png | couverture | 7 | 36 s | non | résumé |
| spécimen p02.png | identification_antecedents | 28 | 51 s | non | résumé |
| spécimen p03.png | grossesse_actuelle | 109 | 73 s | non | résumé |
| spécimen p04.png | accouchement | 16 | 48 s | non | résumé |
| spécimen p05.png | pp_precoce_mere | 24 | 50 s | non | résumé |
| spécimen p06.png | pp_precoce_nne | 21 | 49 s | non | résumé |
| spécimen p07.png | pp_tardif_mere | 24 | 58 s | non | résumé |
| spécimen p08.png | pp_tardif_nne | 21 | 50 s | non | résumé |
| spécimen p65.png | couverture | 6 | 36 s | non | résumé |
| spécimen p66.png | identification_antecedents | 25 | 40 s | non | résumé |
| spécimen p67.png | grossesse_actuelle | 94 | 62 s | non | résumé |
| spécimen p68.png | accouchement | 16 | 48 s | non | résumé |
| spécimen p69.png | pp_precoce_mere | 26 | 54 s | non | résumé |
| spécimen p70.png | pp_precoce_nne | 21 | 51 s | non | résumé |
| spécimen p71.png | pp_tardif_mere | 25 | 66 s | non | résumé |
| spécimen p72.png | pp_tardif_nne | 21 | 56 s | non | résumé |
| synthetique_noire.jpg | — | 0 | 10 s | non | 📷 reprendre la photo + 🟠 « De quelle page s'agit-il ? » |
| synthetique_floue.jpg | — | 0 | 9 s | non | 📷 reprendre la photo + 🟠 « De quelle page s'agit-il ? » |
| synthetique_sans_rapport.jpg | — | 0 | 10 s | non | 📷 reprendre la photo + 🟠 « De quelle page s'agit-il ? » |

24 images : 0 plantage, durée max 73 s, moyenne 39 s ; 24/24 avec au moins un message.

Ollama a renvoyé des réponses vides / erreurs 500 pendant le test (2e avis impossible sur certaines
bandes) : aucune page ne plante, ces champs restent « à vérifier ». Limite notée : l'image « sans
rapport » reçoit « photo floue » (raison approximative) puis « De quelle page s'agit-il ? ».

### Lot 2 – Dates
JJ/MM/AAAA déjà forcé et testé (02/11/2025 = 2 novembre). Nouveau : DPA = DDR + 280 j ± 3 suffit à
passer DDR et DPA en CONNU (0,9) ; la date de dépassement s'ajoute si DPA + 7 à 14 j.

### Lot 3 – Alertes cliniques
Fait avant ce plan (commit 1bc0909, tag lot-3) : voir README « Alertes cliniques ».

### Lot 4 – Commande RDV
« RDV » -> « 📅 2 patientes attendues non revues : A64128 (RDV 05/01) ; A64125 (RDV 13/01). »
(dernier rendez-vous CONNU d'une patiente, dépassé, sans « Venue le » postérieure.)

### Lot vaccination (carnet OMS, remplace le lot 1 bis)
- `data-perso/` ajouté au `.gitignore` AVANT tout ; photos lues en mémoire, jamais copiées ni versionnées
  (le test utilise une page synthétique).
- Modèle `app/templates/carnet_vaccination_oms.py` (inclus dans le modèle actif : liste blanche, 2e avis,
  /verif, conversation inchangés) ; lecteur `ai/vaccination.py` : encre bleue seule (teinte HSV 200–280°,
  mesuré : sous lumière jaune l'encre vaut ~(35, 32, 47) en RGB, un seuil « B > R » ne gardait que 0,5 %
  des pixels), colonnes par en-têtes (+ lignes verticales imprimées si trouvées ; en-tête « signature »
  sous le tampon : extrapolé), entrées = lignes d'écriture, OCR contraint de la cellule agrandie,
  vaccin rapproché du vocabulaire, date au crayon gris -> « rappel ? » toujours à vérifier.
  Toutes les cellules sont critiques : CONNU seulement si le 2e avis Ollama lit la même chose.
- Page synthétique : 2 entrées, date / vaccin / dose / lot / rappel lus justes, tout « à vérifier » sans 2e avis.
- **3 vraies photos** : 2/3 reconnues (« AUTRES VACCINATIONS »), 2 entrées découpées par page ; l'écriture
  cursive est **mal lue par EasyOCR** (dates et vaccins méconnaissables) -> 14 champs, **tous à vérifier**
  (confiance 0,05 à 0,5), **0 erreur silencieuse**. La 3e photo n'est pas reconnue : « Vaccinations » a été
  ajouté à la liste « De quelle page s'agit-il ? ». 55 à 110 s par photo (2880×2160, lue à mi-résolution).
  Conclusion honnête : la structure est là, la reconnaissance de l'écriture manuscrite cursive ne l'est pas
  (piste : modèle d'écriture manuscrite dédié, ou saisie guidée par entrée).


## Branche `arabe-detection` (NON fusionnée dans main)

- Langues EasyOCR du lecteur principal : `["fr", "en"]` (inchangé). 2e lecteur `["ar", "en"]`
  (`ai/arabic.py`) chargé **à la demande** : à la première zone de champ dont la lecture française est
  peu sûre (confiance < 0,5, champs texte / choix). Le modèle `arabic.pth` est téléchargé une seule fois
  au premier usage (ensuite tout est local).
- Détection, pas lecture : zone arabe OU 2e avis Ollama en caractères U+0600–U+06FF -> champ A_REVISER,
  valeur vide, raison « écrit en arabe », question « 🟠 Ce champ semble écrit en arabe, pouvez-vous me
  le donner ? » [Corriger] [Illisible] [Vide]. Une lecture arabe n'est jamais CONNU. Identifiants (même
  écrits en arabe) : toujours retirés par la liste blanche. Réglage : `AI_DETECT_ARABE`.
- Coût mesuré : chargement du lecteur 2,5 s (une fois par processus ; 18,8 s au 1er usage avec le
  téléchargement), ~0,9 s par zone vérifiée, **plafond 5 s de détection par page** (chargement exclu).
  Vraies photos 1-2 et 1-3 : +0,6 s / -3 s (bruit), aucun faux positif.
- Test : case synthétique contenant « الرباط » détectée, « Casablanca » non (test sauté si le modèle
  arabe n'est pas installé). Limite : pas de photo réelle écrite en arabe pour mesurer le rappel.
