# Rapport d'évaluation – 2026-10-03 23:37

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\3b_qwen25vl3b_specimen8`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 8 | 25.0 % | 46.4 % | 53.8 % | 27.4 % | 60.5 % | 0.0 % | 7 | 10 | 81.5 % |
| source:specimen | 8 | 25.0 % | 46.4 % | 53.8 % | 27.4 % | 60.5 % | 0.0 % | 7 | 10 | 81.5 % |
| page:accouchement | 1 | 25.0 % | 37.5 % | 66.7 % | — | 0.0 % | 0.0 % | 0 | 0 | 100.0 % |
| page:couverture | 1 | 62.5 % | 100.0 % | 62.5 % | 16.7 % | 50.0 % | 0.0 % | 1 | 1 | 66.7 % |
| page:grossesse_actuelle | 1 | 3.7 % | 3.7 % | 100.0 % | — | 0.0 % | — | 0 | 0 | — |
| page:identification_antecedents | 1 | 62.5 % | 78.1 % | 80.0 % | 37.5 % | 100.0 % | 0.0 % | 2 | 2 | 60.0 % |
| page:pp_precoce_mere | 1 | 21.7 % | 91.3 % | 23.8 % | 26.5 % | 69.2 % | 0.0 % | 1 | 4 | 75.0 % |
| page:pp_precoce_nne | 1 | 47.6 % | 85.7 % | 55.6 % | 30.0 % | 60.0 % | — | 0 | 1 | 87.5 % |
| page:pp_tardif_mere | 1 | 22.7 % | 95.5 % | 23.8 % | 26.5 % | 75.0 % | 0.0 % | 2 | 1 | 93.8 % |
| page:pp_tardif_nne | 1 | 47.6 % | 66.7 % | 71.4 % | 33.3 % | 50.0 % | 0.0 % | 1 | 1 | 75.0 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 24 | 50.0 % | 40.0 % |
| 0.50-0.80 | 55 | 41.8 % | 52.2 % |
| 0.80-0.95 | 5 | 100.0 % | 85.0 % |
| 0.95-1.00 | 33 | 69.7 % | 97.5 % |
| ECE | 117 | 15.4 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `accouchement.anomalie` | 1 | 1 | 0.0 % |
| `accouchement.date` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.enfants_vivants` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.frottis` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.parite` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.vaccin_hepatite_b` | 1 | 1 | 0.0 % |
| `antecedents_obstetricaux.vat` | 1 | 1 | 0.0 % |
| `couverture.grossesse_a_risque` | 1 | 1 | 0.0 % |
| `couverture.type_etablissement` | 1 | 1 | 0.0 % |
| `couverture.type_risque` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.cesarienne` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.complication` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.complications_type` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.date_consultation` | 1 | 1 | 0.0 % |
| `pp_precoce_mere.lochies` | 1 | 1 | 0.0 % |

## Erreurs silencieuses (faux avec statut CONNU) : 10

- `dossiers_specimen_10_patientes-01.png` `couverture.grossesse_a_risque` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-02.png` `antecedents_obstetricaux.vaccin_hepatite_b` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-02.png` `antecedents_obstetricaux.vat` : vérité `['dose_1']` / prédit `['dose_1', 'dose_2', 'dose_3', 'dose_4', 'dose_5']` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-05.png` `pp_precoce_mere.cesarienne` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-05.png` `pp_precoce_mere.complication` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-05.png` `pp_precoce_mere.prise_medicaments` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-05.png` `pp_precoce_mere.seins` : vérité `['normal']` / prédit `['lymphangite', 'mastite_et_abces', 'normal']` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-06.png` `pp_precoce_nne.transfert` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-07__1O_M-H0E7z.png` `pp_tardif_mere.cesarienne` : vérité `False` / prédit `True` (CONNU, 0.99)
- `dossiers_specimen_10_patientes-08.png` `pp_tardif_nne.vitamine_d` : vérité `False` / prédit `True` (CONNU, 0.99)

## Calibration du SEUIL_CONNU

| seuil | CONNU | erreurs silencieuses |
|---|---|---|
| 0.50 | 42 | 10 |
| 0.55 | 42 | 10 |
| 0.60 | 42 | 10 |
| 0.65 | 42 | 10 |
| 0.70 | 42 | 10 |
| 0.75 | 42 | 10 |
| 0.80 | 38 | 10 |
| 0.85 | 38 | 10 |
| 0.90 | 33 | 10 |
| 0.95 | 33 | 10 |

Seuil proposé : **0.50**
