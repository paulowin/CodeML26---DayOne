"""Seuils des alertes cliniques (app/services/alerts.py) — UN SEUL fichier, chaque seuil avec sa source.

AIDE À LA DÉCISION, jamais un diagnostic : une alerte signale une valeur à évaluer par la
sage-femme selon le protocole national. Les alertes ne sont calculées que sur des valeurs
CONFIRMÉES par la sage-femme (statut CONNU, source SAGE_FEMME), jamais sur une lecture à vérifier.
"""

# --- Tension artérielle (mmHg)
# OMS, « WHO recommendations for prevention and treatment of pre-eclampsia and eclampsia » (2011) :
# hypertension gravidique = TAS ≥ 140 ou TAD ≥ 90 ; hypertension sévère = TAS ≥ 160 ou TAD ≥ 110.
TA_HTA_SYS, TA_HTA_DIA = 140, 90
TA_SEVERE_SYS, TA_SEVERE_DIA = 160, 110

# --- Pré-éclampsie : hypertension + protéinurie APRÈS 20 semaines d'aménorrhée (OMS 2011, même source)
PREECLAMPSIE_SA_MIN = 20

# --- TA en hausse : TAS strictement croissante sur N visites consécutives (règle de vigilance simple,
# pas un critère OMS : une tendance à surveiller avant d'atteindre le seuil)
TA_HAUSSE_VISITES = 3

# --- Hémoglobine (g/dL)
# OMS, « Haemoglobin concentrations for the diagnosis of anaemia and assessment of severity »
# (VMNIS, 2011) : femme enceinte : anémie si Hb < 11 ; anémie sévère si Hb < 7.
HB_ANEMIE = 11.0
HB_ANEMIE_SEVERE = 7.0

# --- Bruits du cœur fœtal (battements / min)
# OMS, « Intrapartum care for a positive childbirth experience » (2018) ; FIGO (2015) :
# rythme de base normal 110 à 160 bpm.
BCF_MIN, BCF_MAX = 110, 160

# --- Dépassement de terme (semaines d'aménorrhée)
# OMS : grossesse prolongée à 42 SA révolues ; recommandation OMS (2018) de proposer le déclenchement
# à partir de 41 SA -> alerte au-delà de 41 SA si aucun accouchement n'est enregistré.
TERME_DEPASSE_SA = 41
