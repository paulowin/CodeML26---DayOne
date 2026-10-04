# Rapport d'évaluation – 2026-10-03 23:39

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\3b_v2_sans_tableaux`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 6 | 35.1 % | 79.3 % | 44.3 % | 26.4 % | 60.5 % | 0.0 % | 4 | 0 | 100.0 % |
| source:specimen | 6 | 35.1 % | 79.3 % | 44.3 % | 26.4 % | 60.5 % | 0.0 % | 4 | 0 | 100.0 % |
| page:accouchement | 1 | 25.0 % | 37.5 % | 66.7 % | — | 0.0 % | 0.0 % | 0 | 0 | 100.0 % |
| page:couverture | 1 | 62.5 % | 100.0 % | 62.5 % | 16.7 % | 50.0 % | — | 0 | 0 | 100.0 % |
| page:pp_precoce_mere | 1 | 21.7 % | 91.3 % | 23.8 % | 26.5 % | 69.2 % | 0.0 % | 1 | 0 | 100.0 % |
| page:pp_precoce_nne | 1 | 47.6 % | 85.7 % | 55.6 % | 30.0 % | 60.0 % | — | 0 | 0 | 100.0 % |
| page:pp_tardif_mere | 1 | 22.7 % | 95.5 % | 23.8 % | 26.5 % | 75.0 % | 0.0 % | 2 | 0 | 100.0 % |
| page:pp_tardif_nne | 1 | 47.6 % | 66.7 % | 71.4 % | 33.3 % | 50.0 % | 0.0 % | 1 | 0 | 100.0 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 14 | 35.7 % | 40.0 % |
| 0.50-0.80 | 65 | 38.5 % | 54.3 % |
| 0.80-0.95 | 5 | 100.0 % | 85.0 % |
| 0.95-1.00 | 4 | 100.0 % | 96.0 % |
| ECE | 88 | 13.4 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `accouchement.anomalie` | 1 | 1 | 0.0 % |
| `accouchement.date` | 1 | 1 | 0.0 % |
| `couverture.grossesse_a_risque` | 1 | 1 | 0.0 % |
| `couverture.type_etablissement` | 1 | 1 | 0.0 % |
| `couverture.type_risque` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.cesarienne` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.complication` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.complications_type` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.date_consultation` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.lochies` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.mollets` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.moment` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.perinee` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.pf_methode` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.pf_prescription` | 1 | 1 | 0.0 % |

## Erreurs silencieuses (faux avec statut CONNU) : 0


## Calibration du SEUIL_CONNU

| seuil | CONNU | erreurs silencieuses |
|---|---|---|
| 0.50 | 29 | 8 |
| 0.55 | 29 | 8 |
| 0.60 | 29 | 8 |
| 0.65 | 13 | 0 |
| 0.70 | 13 | 0 |
| 0.75 | 13 | 0 |
| 0.80 | 9 | 0 |
| 0.85 | 9 | 0 |
| 0.90 | 4 | 0 |
| 0.95 | 4 | 0 |

Seuil proposé : **0.61**
