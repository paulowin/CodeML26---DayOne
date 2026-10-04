# Cases à cocher : VLM (avant) vs vision classique OpenCV (après)

Pages spécimen : [1, 2, 3, 4, 5, 6, 7, 8]

| | précision | rappel | VP | FP | FN | à réviser / champs cases |
|---|---|---|---|---|---|---|
| avant (VLM 3b) | 27.4 % | 60.5 % | 26 | 69 | 17 | 30 / 75 |
| après (OpenCV) | 100.0 % | 100.0 % | 43 | 0 | 0 | 0 / 75 |

| page | type | localisation | cases | durée |
|---|---|---|---|---|
| 1 | couverture | homographie | 16 | 22 s |
| 2 | identification_antecedents | homographie | 9 | 21 s |
| 3 | grossesse_actuelle | homographie | 6 | 25 s |
| 4 | accouchement | homographie | 24 | 19 s |
| 5 | pp_precoce_mere | homographie | 40 | 16 s |
| 6 | pp_precoce_nne | homographie | 31 | 16 s |
| 7 | pp_tardif_mere | homographie | 40 | 15 s |
| 8 | pp_tardif_nne | homographie | 31 | 16 s |

Images de debug : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\cases_cv` (vert = cochée, rouge = vide, orange = incertaine).
