# Vérité terrain

- `specimen_pNN.json` : **générés** par `python -m scripts.build_ground_truth` à partir du PDF
  spécimen (ne pas modifier à la main, relancer le script).
- `reel_1-X.json` : **modèles à remplir à la main** par l'équipe, un par vraie photo
  (`data-defi/Paper Registry/1-X.jpg`). Le script ne les écrase jamais.
- `reel_identifiants.local.json` : identifiants lus sur les vraies photos (CIN, adresse,
  nom...). **Ignoré par git, ne jamais le committer.** Il sert uniquement à vérifier que
  l'IA ne sort jamais ces valeurs.

## Remplir un modèle `reel_1-X.json`

Ouvrir la photo à côté du JSON, puis pour chaque clé de `"fields"` :

| Ce qui est sur le papier | Ce qu'il faut écrire | Statut attendu de l'IA |
|---|---|---|
| Pas encore relu | `null` (valeur par défaut) | champ ignoré par l'évaluateur |
| Case vide, rien d'écrit | `""` | `NON_FOURNI` |
| Tiret (`-`, `—`, `/`) | `"—"` | `NON_FOURNI` |
| « RAS », « nég », « Néant »... | le texte **tel qu'écrit** : `"RAS"`, `"nég"` | `CONNU` |
| Valeur lisible | le texte tel qu'écrit, ex. `"11/7"`, `"16SA+3j"`, `"64 kg"` | `CONNU` |
| Illisible même pour un humain | `"#ILLISIBLE"` | `ILLISIBLE` ou `A_REVISER` |

- **Ne pas convertir** : l'évaluateur normalise lui-même (dates en jj/mm/aaaa, TA en cmHg
  `11/7` -> 110/70 mmHg, unités retirées, casse et accents ignorés).
- **Cases à cocher** (champs listés dans `"champs_cases"`) :
  - type `bool` (une seule case) : `true` si cochée, `false` sinon ;
  - type `enum` (un seul choix) : le code de l'option cochée, ex. `"fixe"`, `"positif"` ;
    `""` si aucune case cochée ;
  - type `checkbox_group` (plusieurs choix) : la liste des codes cochés, ex. `["dose_1", "dose_2"]`,
    `[]` si rien n'est coché.
  - Les codes sont dans `app/templates/carnet_maroc.py` (`ch("Libellé", "code")`, sinon le code
    est le libellé en minuscules sans accents, ex. « Clinique privée » -> `clinique_privee`).
  - Recopier aussi les cases cochées dans `"checked"` : `"clé"` pour un bool, `"clé:code"` sinon.
- **Valeur entourée** (ex. « Rhésus (+) » entouré au lieu d'être coché) : la traiter comme cochée.
- Une valeur écrite **hors de sa case** (débordement sur la ligne voisine) : l'attribuer au champ
  que la sage-femme visait.
- Quand le fichier est complet, passer `"a_remplir"` à `false`.

## Identifiants des photos réelles

Remplir `reel_identifiants.local.json` (même structure : `{"reel_1-2.json": {"identification.cin": "..."}}`)
avec ce qui est lisible. Ces valeurs ne doivent **jamais** apparaître dans un fichier versionné
ni dans une prédiction : `eval.evaluate` échoue (code 2) si c'est le cas.
