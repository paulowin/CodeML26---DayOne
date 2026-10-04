# Rapport d'évaluation – 2026-10-04 02:48

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\3d_paddle`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 3 | 87.2 % | 99.2 % | 87.9 % | — | 0.0 % | 90.9 % | 2 | 2 | 50.0 % |
| source:specimen | 3 | 87.2 % | 99.2 % | 87.9 % | — | 0.0 % | 90.9 % | 2 | 2 | 50.0 % |
| page:accouchement | 1 | 68.8 % | 100.0 % | 68.8 % | — | 0.0 % | — | 0 | 0 | 20.0 % |
| page:couverture | 1 | 50.0 % | 87.5 % | 57.1 % | — | 0.0 % | — | 0 | 1 | 33.3 % |
| page:grossesse_actuelle | 1 | 92.7 % | 100.0 % | 92.7 % | — | 0.0 % | 90.9 % | 2 | 1 | 75.0 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 8 | 0.0 % | 40.0 % |
| 0.50-0.80 | 19 | 68.4 % | 66.9 % |
| 0.80-0.95 | 103 | 98.1 % | 85.0 % |
| 0.95-1.00 | 2 | 100.0 % | 99.0 % |
| ECE | 132 | 12.9 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `grossesse_actuelle.visites.*.bcf` | 2 | 5 | 60.0 % |
| `accouchement.age_gestationnel_sa` | 1 | 1 | 0.0 % |
| `accouchement.etat_nne` | 1 | 1 | 0.0 % |
| `accouchement.lieu` | 1 | 1 | 0.0 % |
| `accouchement.lieu_structure` | 1 | 1 | 0.0 % |
| `accouchement.mode` | 1 | 1 | 0.0 % |
| `couverture.mode_couverture` | 1 | 1 | 0.0 % |
| `couverture.numero_fiche` | 1 | 1 | 0.0 % |
| `couverture.type_etablissement` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.date_depassement_terme` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.dpa` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.groupage` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.rhesus` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.visites.*.age_probable_sa` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.hu_cm` | 1 | 5 | 80.0 % |

## Erreurs silencieuses (faux avec statut CONNU) : 2

- `dossiers_specimen_10_patientes-01.png` `couverture.numero_fiche` : vérité `2026-823-001` / prédit `2026-823-007` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.M8.hu_cm` : vérité `31.0` / prédit `37.0` (CONNU, 0.85)
