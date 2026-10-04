# Rapport d'évaluation – 2026-10-04 03:23

Prédictions : `C:\Users\paule\Documents\CodeML26---DayOne\Iris\eval\preds\final_specimen24_easyocr_v2`

## Confidentialité

OK : aucun identifiant retrouvé dans les prédictions.

## Métriques

| groupe | images | exactitude | couverture | precision_surs | exactitude_sur_couverts | cases_precision | cases_rappel | vides_non_fourni | valeurs_inventees | erreurs_silencieuses | erreurs_signalees |
|---|---|---|---|---|---|---|---|---|---|---|---|
| global:tout | 24 | 74.4 % | 92.2 % | 98.6 % | 80.6 % | 100.0 % | 71.0 % | 0.0 % | 18 | 6 | 85.7 % |
| source:specimen | 24 | 74.4 % | 92.2 % | 98.6 % | 80.6 % | 100.0 % | 71.0 % | 0.0 % | 18 | 6 | 85.7 % |
| page:accouchement | 3 | 83.7 % | 93.9 % | 100.0 % | 89.1 % | 100.0 % | 78.6 % | 0.0 % | 2 | 0 | 40.0 % |
| page:couverture | 3 | 58.3 % | 95.8 % | 91.7 % | 60.9 % | 100.0 % | 50.0 % | — | 0 | 1 | 66.7 % |
| page:grossesse_actuelle | 3 | 81.5 % | 96.5 % | 99.4 % | 84.5 % | 100.0 % | 83.3 % | — | 0 | 1 | 96.1 % |
| page:identification_antecedents | 3 | 52.8 % | 66.7 % | 95.7 % | 79.2 % | 100.0 % | 90.9 % | — | 0 | 2 | 86.7 % |
| page:pp_precoce_mere | 3 | 71.4 % | 95.7 % | 100.0 % | 74.6 % | 100.0 % | 68.3 % | 0.0 % | 7 | 0 | 88.2 % |
| page:pp_precoce_nne | 3 | 74.6 % | 98.4 % | 97.6 % | 75.8 % | 100.0 % | 73.3 % | — | 0 | 1 | 80.0 % |
| page:pp_tardif_mere | 3 | 68.7 % | 92.5 % | 100.0 % | 74.2 % | 100.0 % | 67.6 % | 0.0 % | 9 | 0 | 87.5 % |
| page:pp_tardif_nne | 3 | 81.0 % | 100.0 % | 97.7 % | 81.0 % | 100.0 % | 66.7 % | — | 0 | 1 | 75.0 % |

## Calibration (exactitude par tranche de confiance)

| tranche | n | exactitude | confiance moyenne |
|---|---|---|---|
| 0.00-0.50 | 134 | 23.9 % | 37.3 % |
| 0.50-0.80 | 151 | 81.5 % | 63.7 % |
| 0.80-0.95 | 438 | 97.7 % | 84.9 % |
| 0.95-1.00 | 0 | — | — |
| ECE | 723 | 14.0 % | — |

## Top 15 des champs les plus ratés

| champ | erreurs | n | exactitude |
|---|---|---|---|
| `grossesse_actuelle.visites.*.rendez_vous` | 7 | 17 | 58.8 % |
| `grossesse_actuelle.visites.*.ta` | 7 | 19 | 63.2 % |
| `grossesse_actuelle.visites.*.poids_kg` | 6 | 19 | 68.4 % |
| `grossesse_actuelle.visites.*.venue_le` | 6 | 19 | 68.4 % |
| `grossesse_actuelle.visites.*.age_probable_sa` | 4 | 19 | 78.9 % |
| `antecedents_femme.gynecologiques` | 3 | 3 | 0.0 % |
| `grossesse_actuelle.dpa` | 3 | 3 | 0.0 % |
| `grossesse_actuelle.visites.*.bcf` | 3 | 15 | 80.0 % |
| `identification.profession_partenaire` | 3 | 3 | 0.0 % |
| `pp_tardif_mere.ta` | 3 | 3 | 0.0 % |
| `pp_tardif_nne.decision` | 3 | 3 | 0.0 % |
| `accouchement.poids_naissance_g` | 2 | 3 | 33.3 % |
| `antecedents_obstetricaux.vaccin_rubeole_date` | 2 | 3 | 33.3 % |
| `couverture.numero_fiche` | 2 | 3 | 33.3 % |
| `grossesse_actuelle.date_depassement_terme` | 2 | 3 | 33.3 % |

## Erreurs silencieuses (faux avec statut CONNU) : 6

- `dossiers_specimen_10_patientes-06.png` `pp_precoce_nne.decision` : vérité `Poursuivre l'allaitement exclusif` / prédit `Poursuire lallaitement exclusif` (CONNU, 0.83)
- `dossiers_specimen_10_patientes-08.png` `pp_tardif_nne.prochaine_visite` : vérité `17/05/2026` / prédit `2026-05-13` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-10__1U_S1pqftP.png` `identification.profession_partenaire` : vérité `Chauffeur` / prédit `Chuffeur` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-11.png` `grossesse_actuelle.visites.T1V1.rendez_vous` : vérité `02/11/2025` / prédit `2025-01-02` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-17__1JAXyAcTm1.png` `couverture.province` : vérité `Al Haouz` / prédit `AI Haouz` (CONNU, 0.85)
- `dossiers_specimen_10_patientes-18__1baIjVKeMw.png` `antecedents_femme.medicaux` : vérité `Asthme l�ger` / prédit `Asthme ger` (CONNU, 0.85)
