# Rapport d'évaluation – 2026-10-04 02:36

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\3d_essai_easy`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 2 | 48.8 % | 68.0 % | 71.8 % | — | 0.0 % | 0.0 % | 25 | 8 | 45.8 % |
| source:specimen | 2 | 48.8 % | 68.0 % | 71.8 % | — | 0.0 % | 0.0 % | 25 | 8 | 45.8 % |
| page:accouchement | 1 | 68.8 % | 93.8 % | 73.3 % | — | 0.0 % | 0.0 % | 1 | 0 | 0.0 % |
| page:grossesse_actuelle | 1 | 45.9 % | 64.2 % | 71.4 % | — | 0.0 % | 0.0 % | 24 | 8 | 55.0 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 10 | 10.0 % | 41.0 % |
| 0.50-0.80 | 9 | 66.7 % | 66.2 % |
| 0.80-0.95 | 66 | 81.8 % | 84.9 % |
| 0.95-1.00 | 0 | — | — |
| ECE | 85 | 6.1 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `grossesse_actuelle.visites.*.seins` | 2 | 6 | 66.7 % |
| `accouchement.etat_nne` | 1 | 1 | 0.0 % |
| `accouchement.lieu` | 1 | 1 | 0.0 % |
| `accouchement.lieu_structure` | 1 | 1 | 0.0 % |
| `accouchement.mode` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.date_depassement_terme` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.dpa` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.groupage` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.rhesus` | 1 | 1 | 0.0 % |
| `grossesse_actuelle.visites.*.age_probable_sa` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.albuminurie` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.anomalies_squelette` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.bcf` | 1 | 5 | 80.0 % |
| `grossesse_actuelle.visites.*.conjonctives` | 1 | 6 | 83.3 % |
| `grossesse_actuelle.visites.*.glucosurie` | 1 | 6 | 83.3 % |

## Erreurs silencieuses (faux avec statut CONNU) : 8

- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.M8.seins` : vérité `Normaux` / prédit `Nbrmaux` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.age_probable_sa` : vérité `27.0` / prédit `22.0` (CONNU, 0.81)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.anomalies_squelette` : vérité `RAS` / prédit `RAS RAS` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.conjonctives` : vérité `Normales` / prédit `Normales Normales` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.mouvements_actifs` : vérité `Oui` / prédit `Oui Oui` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.oedemes` : vérité `Non` / prédit `Non Non` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.relance` : vérité `Non` / prédit `Non Non` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-03.png` `grossesse_actuelle.visites.T2V3.seins` : vérité `Normaux` / prédit `Normaux Normaux` (CONNU, 0.85)
