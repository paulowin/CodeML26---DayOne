# Rapport d'évaluation – 2026-10-03 23:56

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\3b_v2_tableaux`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 2 | 19.9 % | 24.8 % | 80.0 % | 30.0 % | 60.0 % | 0.0 % | 6 | 0 | 100.0 % |
| source:specimen | 2 | 19.9 % | 24.8 % | 80.0 % | 30.0 % | 60.0 % | 0.0 % | 6 | 0 | 100.0 % |
| page:grossesse_actuelle | 1 | 3.7 % | 5.5 % | 66.7 % | 0.0 % | 0.0 % | — | 0 | 0 | 100.0 % |
| page:identification_antecedents | 1 | 75.0 % | 90.6 % | 82.8 % | 37.5 % | 100.0 % | 0.0 % | 6 | 0 | 100.0 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 5 | 0.0 % | 40.0 % |
| 0.50-0.80 | 7 | 71.4 % | 55.7 % |
| 0.80-0.95 | 19 | 100.0 % | 85.0 % |
| 0.95-1.00 | 4 | 100.0 % | 95.0 % |
| ECE | 35 | 17.6 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `antecedents_obstetricaux.enfants_vivants` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.gestite` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.parite` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.vaccin_hepatite_b` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.vat` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.groupage` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.rhesus` | 1 | 1 | 0.0 % |

## Erreurs silencieuses (faux avec statut CONNU) : 0

