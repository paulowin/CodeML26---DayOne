# Cases à cocher : VLM (avant) vs vision classique OpenCV (après)

Pages spécimen : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]

| | précision | rappel | VP | FP | FN | à réviser / champs cases | erreurs silencieuses |
|---|---|---|---|---|---|---|---|
| avant (VLM 3b) | 100.0 % | 71.0 % | 98 | 0 | 40 | 23 / 225 | 6 |
| après (OpenCV) | 100.0 % | 96.4 % | 133 | 0 | 5 | 88 / 225 | 0 |

| page | type | localisation | cases | durée |
|---|---|---|---|---|
| 1 | couverture | homographie | 16 | 28 s |
| 2 | identification_antecedents | homographie | 9 | 22 s |
| 3 | grossesse_actuelle | homographie | 6 | 23 s |
| 4 | accouchement | homographie | 24 | 18 s |
| 5 | pp_precoce_mere | homographie | 40 | 19 s |
| 6 | pp_precoce_nne | homographie | 31 | 19 s |
| 7 | pp_tardif_mere | homographie | 40 | 18 s |
| 8 | pp_tardif_nne | homographie | 31 | 21 s |
| 9 | couverture | homographie | 16 | 22 s |
| 10 | identification_antecedents | homographie | 9 | 28 s |
| 11 | grossesse_actuelle | homographie | 6 | 32 s |
| 12 | accouchement | homographie | 24 | 25 s |
| 13 | pp_precoce_mere | homographie | 40 | 26 s |
| 14 | pp_precoce_nne | homographie | 31 | 28 s |
| 15 | pp_tardif_mere | homographie | 40 | 26 s |
| 16 | pp_tardif_nne | homographie | 31 | 23 s |
| 17 | couverture | homographie | 16 | 23 s |
| 18 | identification_antecedents | homographie | 9 | 28 s |
| 19 | grossesse_actuelle | homographie | 6 | 30 s |
| 20 | accouchement | homographie | 24 | 24 s |
| 21 | pp_precoce_mere | homographie | 40 | 24 s |
| 22 | pp_precoce_nne | homographie | 31 | 30 s |
| 23 | pp_tardif_mere | homographie | 40 | 26 s |
| 24 | pp_tardif_nne | homographie | 31 | 27 s |

Images de debug : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\cases_cv` (vert = cochée, rouge = vide, orange = incertaine).
