# Rapport d'évaluation – 2026-10-04 02:42

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\3d_easyocr`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 3 | 88.0 % | 97.7 % | 90.0 % | 100.0 % | 75.0 % | 0.0 % | 1 | 2 | 84.6 % |
| source:specimen | 3 | 88.0 % | 97.7 % | 90.0 % | 100.0 % | 75.0 % | 0.0 % | 1 | 2 | 84.6 % |
| page:accouchement | 1 | 81.2 % | 87.5 % | 92.9 % | 100.0 % | 75.0 % | 0.0 % | 1 | 0 | 100.0 % |
| page:couverture | 1 | 87.5 % | 87.5 % | 100.0 % | 100.0 % | 100.0 % | — | 0 | 0 | — |
| page:grossesse_actuelle | 1 | 89.0 % | 100.0 % | 89.0 % | 100.0 % | 50.0 % | — | 0 | 2 | 83.3 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 13 | 23.1 % | 42.5 % |
| 0.50-0.80 | 36 | 97.2 % | 66.9 % |
| 0.80-0.95 | 81 | 97.5 % | 85.0 % |
| 0.95-1.00 | 0 | — | — |
| ECE | 130 | 18.2 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `grossesse_actuelle.visites.*.rendez_vous` | 2 | 5 | 60.0 % |
| `accouchement.mode` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.date_depassement_terme` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.dpa` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.groupage` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.visites.*.albuminurie` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.plaquettes` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.visites.*.poids_kg` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.relance` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.seins` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.ta` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.venue_le` | 1 | 6 | 83.3 % |

## Erreurs silencieuses (faux avec statut CONNU) : 2

- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.M8.seins` : vérité `Normaux` / prédit `Nbrmaux` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T1V2.relance` : vérité `Oui` / prédit `Ou;` (CONNU, 0.85)
