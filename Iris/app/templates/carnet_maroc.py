"""Carnet « Fiche de surveillance de la grossesse et du post-partum »
(carnet rose du ministère de la Santé du Maroc, reproduit par le PDF spécimen).

`label_fr` = texte imprimé du spécimen ; `aliases` = variantes du vrai carnet.
`csv_column` = colonne correspondante de maternal_registry_synthetic.csv.
Les champs `identifiant=True` ne sont JAMAIS extraits ni stockés : ils ne sont
décrits ici que pour reconnaître (et écarter) leur zone sur la page.
"""
from .base import FieldDef as F, PageType, SectionDef, TableDef, Template, ch


def _id(key: str, label: str, **kw) -> F:
    return F(key, label, "str", identifiant=True, **kw)


# ------------------------------------------------------------------ couverture
COUVERTURE = SectionDef("couverture", "Couverture", (
    F("numero_fiche", "N° de la fiche :"),
    F("region", "Région :"),
    F("province", "Province :", aliases=("Province",)),
    F("etablissement", "Nom de l'établissement sanitaire :"),
    F("type_etablissement", "Type de l'établissement sanitaire :", "enum",
      (ch("DR"), ch("CSC"), ch("CSU"), ch("CSCA"), ch("CSUA"))),
    F("mode_couverture", "Mode de la couverture :", "enum", (ch("Fixe"), ch("Mobile"))),
    _id("nom_parturiente", "Nom/Prénom de la parturiente :"),
    F("grossesse_a_risque", "Grossesse classée à risque :", "bool"),
    F("type_risque", "Si grossesse à risque, préciser le type de risque :", "checkbox_group", (
        ch("Anémie"), ch("Métrorragie"), ch("H.T.A", "hta"), ch("Infection"), ch("Diabète"),
        ch("Pré-éclampsie"), ch("Cardiopathie"), ch("Eclampsie"))),
    F("type_risque_autre", "Autres à préciser :"),
))

# ------------------------------------------------------------------ identification
IDENTIFICATION = SectionDef("identification", "Identification", (
    F("age", "Age :", "int", unit="ans", plausible=(12, 55), csv_column="age (years)"),
    _id("cin", "CIN :"),
    F("niveau_instruction", "Niveau d'instruction :",
      csv_column="education level (0=none/primary,1=secondary,2=higher)"),
    F("profession", "Profession :", context="Niveau d'instruction :"),
    _id("adresse", "Adresse :"),
    _id("telephone", "Téléphone :"),
    _id("nom_mari", "Nom du Mari :"),
    F("profession_partenaire", "Profession :", context="Nom du Mari :"),
    F("consanguinite", "Consanguinité", "bool", csv_column="consanguinity"),
    F("grossesse_desiree", "Grossesse désirée", "bool", csv_column="desired pregnancy"),
))

_ATCD_ROWS = (
    F("hta", "HTA"),
    F("diabete", "Diabète"),
    F("maladies_hereditaires", "Maladies héréditaires"),
    F("malformations", "Malformations"),
    F("allergies", "Allergie(s)"),
    F("autres", "Autres à préciser"),
)
ANTECEDENTS_FAMILIAUX = SectionDef("antecedents_familiaux", "Antécédents héréditaires et familiaux", tables=(
    TableDef("", "Antécédents héréditaires et familiaux",
             (("femme", "Famille de la femme"), ("partenaire", "Mari/famille")), _ATCD_ROWS,
             col_aliases={"partenaire": ("Mari et famille du mari",)}),
))

ANTECEDENTS_FEMME = SectionDef("antecedents_femme", "Antécédents de la femme", tables=(
    TableDef("", "Antécédents de la femme",
             (("medicaux", "Médicaux"), ("chirurgicaux", "Chirurgicaux"), ("gynecologiques", "Gynécologiques"))),
))

# ------------------------------------------------------------------ antécédents obstétricaux
_PREV_DELIVERY_ROWS = (
    F("date", "Date", "date", aliases=("Date de l'accouchement",)),
    F("modalite", "Modalité d'extraction", aliases=("Modalités de l'extraction",)),
    F("indication_cesarienne", "Si césarienne : indication", aliases=("Si césarienne, préciser l'indication",)),
    F("complication", "Complication (type)", aliases=("Si complication de l'accouchement, préciser le type",)),
    F("poids_nne_g", "Poids nouveau-né(s)", "int", unit="g", plausible=(400, 6000),
      aliases=("Poids du (des) nouveau-né(s)",)),
    F("complication_nne", "Compl. nouveau-né (type)", aliases=("Si complication du nouveau né, préciser le type",)),
)
ANTECEDENTS_OBSTETRICAUX = SectionDef("antecedents_obstetricaux", "Antécédents obstétricaux", (
    F("gestite", "Gestation :", "int", plausible=(1, 20), csv_column="gravidity (number)", critique=True),
    F("parite", "Parité :", "int", plausible=(0, 20), csv_column="parity (number)", critique=True),
    F("enfants_vivants", "Nombre d'enfants vivants :", "int", plausible=(0, 20),
      csv_column="living children (number)", critique=True),
    F("vat", "VAT :", "checkbox_group", tuple(ch(str(i), f"dose_{i}") for i in range(1, 6))),
    F("vaccin_rubeole", "Vaccinée contre la rubéole", "bool"),
    F("vaccin_rubeole_date", "Le", "date", context="Vaccinée contre la rubéole"),
    F("vaccin_hepatite_b", "Vaccinée contre l'hépatite B", "bool"),
    F("vaccin_hepatite_b_date", "Le", "date", context="Vaccinée contre l'hépatite B"),
    F("frottis", "Frottis cervical / IVA (moins de 3 ans) :"),
), tables=(
    TableDef("anomalies", "Anomalies des grossesses antérieures",
             (("nombre", "Nombre"), ("date", "Date"), ("lieu", "Lieu"), ("age_gestationnel_sa", "Age gestationnel (SA)")),
             (F("avortement", "Avortement", csv_column="abortions (number)"),
              F("premature", "Accouchement prématuré"),
              F("mort_foetale", "Mort fœtale in utéro", aliases=("Mort foetale in utéro",)),
              F("autres", "Autres à préciser :")),
             instance="row",
             col_types={"nombre": ("int", None, (0, 20)), "date": ("str", None, None),
                        "lieu": ("str", None, None), "age_gestationnel_sa": ("float", "SA", (4, 44))}),
    TableDef("accouchements", "Déroulement des accouchements antérieurs",
             tuple((str(i), f"Accouch. {i}") for i in range(1, 6)), _PREV_DELIVERY_ROWS,
             col_aliases={str(i): (f"Accouchement {i}",) for i in range(1, 6)}),
))

# ------------------------------------------------------------------ grossesse actuelle
VISIT_COLS = (("T1V1", "Visite 1"), ("T1V2", "Visite 2"), ("T1V3", "Visite 3"),
              ("T2V1", "Visite 1"), ("T2V2", "Visite 2"), ("T2V3", "Visite 3"),
              ("M7", "7ème mois"), ("M8", "8ème mois"), ("M9", "9ème mois"))
_VISIT_ROWS = (
    F("rendez_vous", "Rendez-vous", "date", aliases=("Rendez vous",)),
    F("venue_le", "Venue le", "date"),
    F("relance", "Visites de relance"),
    F("age_probable_sa", "Age probable", "float", unit="SA", plausible=(4, 44),
      csv_column="gestational age at enrollment (weeks)", aliases=("Age probable de la grossesse",)),
    F("poids_kg", "Poids (kg)", "float", unit="kg", plausible=(30, 150), aliases=("Poids",)),
    F("ta", "TA", "bp", unit="mmHg", plausible=(40, 250),
      csv_column=("mean systolic bp (mmhg)", "mean diastolic bp (mmhg)"), critique=True),
    F("anomalies_squelette", "Anomalies squelette", aliases=("Anomalies du squelette (à préciser)",)),
    F("conjonctives", "État des conjonctives", aliases=("Etat des conjonctives",)),
    F("seins", "Examen des seins"),
    F("oedemes", "Œdèmes", aliases=("Oedèmes",)),
    F("mouvements_actifs", "Mouvements actifs"),
    F("hu_cm", "HU (cm)", "float", unit="cm", plausible=(5, 45), aliases=("HU",)),
    F("bcf", "BCF", "int", unit="bpm", plausible=(80, 200)),
    F("speculum", "Examen au spéculum", aliases=("Examen au speculum",)),
    F("tv_col", "TV : état du col", aliases=("Etat du col",)),
    F("tv_presentation", "TV : présentation", aliases=("Présentation",)),
    F("tv_bassin", "TV : bassin", aliases=("Bassin",)),
    F("glucosurie", "Glucosurie"),
    F("albuminurie", "Albuminurie", csv_column="proteinuria"),
    F("rubeole", "Rubéole"),
    F("toxoplasmose", "Toxoplasmose"),
    F("syphilis", "Syphilis (TPHA/VDRL)", csv_column="syphilis test result", aliases=("Syphilis(TPHA/VDRL)",),
      critique=True),
    F("ag_hbs", "Ag HBs", critique=True),
    F("vih", "Sérologie VIH", csv_column="hiv test result", critique=True),
    F("hemoglobine", "Hémoglobine", "float", unit="g/dL", plausible=(4, 20), csv_column="hemoglobin (g/dl)",
      critique=True),
    F("plaquettes", "Plaquettes", "float", unit="/mm3", plausible=(10_000, 1_000_000)),
    # écrite en g/L sur le carnet, stockée en mg/dL comme le CSV (0,93 g/L -> 93 mg/dL)
    F("glycemie", "Bilan glycémique", "float", unit="mg/dL", plausible=(30, 400),
      csv_column="first fasting glucose (mg/dl)", critique=True),
    F("rai", "RAI (si Rh négatif)", aliases=("RAI (si Rhésus négatif)",)),
    F("bio_autres", "Autres", context="EXAMEN BIOLOGIQUE"),
    F("fer", "Fer"),
    F("traitement_autres", "Autres à préciser", context="TRAITEMENT"),
    F("examen_fait_par", "Examen fait par", identifiant=True, aliases=("EXAMEN FAIT PAR",)),
)
GROSSESSE_ACTUELLE = SectionDef("grossesse_actuelle", "Grossesse actuelle", (
    F("ddr", "DDR :", "date", critique=True),
    F("taille_cm", "Taille :", "float", unit="cm", plausible=(120, 200)),
    F("groupage", "Groupage :", "enum", (ch("A"), ch("B"), ch("O"), ch("AB"))),
    F("rhesus", "Rhésus", "enum", (ch("Rh+", "positif", "Rhésus (+)"), ch("Rh-", "negatif", "Rhésus (-)"))),
    F("dpa", "DATE PRÉVUE D'ACCOUCHEMENT :", "date", critique=True),
    F("date_depassement_terme", "DATE DE DÉPASSEMENT DE TERME :", "date"),
), tables=(
    TableDef("visites", "Prestations / Visites", VISIT_COLS, _VISIT_ROWS),
))

# ------------------------------------------------------------------ accouchement
ACCOUCHEMENT = SectionDef("accouchement", "Déroulement de l'accouchement", (
    _id("nom_patiente", "Patiente :"),
    F("lieu", "Lieu", "enum", (ch("En milieu surveillé"), ch("A domicile"))),
    F("lieu_structure", "En milieu surveillé", "enum",
      (ch("Maison d'accouchement"), ch("Maternité"), ch("Clinique privée"))),
    F("lieu_autre_milieu", "Autres :", context="En milieu surveillé"),
    F("domicile_assiste", "Assisté par un personnel qualifié", "bool"),
    F("lieu_autre_domicile", "Autres :", context="A domicile"),
    F("date", "Date de l'accouchement :", "date", critique=True),
    F("mode", "Mode de l'accouchement :", "enum", (
        ch("Voie basse non instrumentale"), ch("Voie basse instrumentale"),
        ch("Césarienne : Programmée", "cesarienne_programmee", "Programmée"),
        ch("Urgence", "cesarienne_urgence")), csv_column="type of delivery (0=vaginal,1=cesarean)"),
    F("instrument", "Voie basse instrumentale", "checkbox_group", (ch("Forceps"), ch("Ventouse"))),
    F("episiotomie", "Avec épisiotomie", "bool"),
    F("indication_cesarienne", "Préciser l'indication :"),
    F("complications", "Présence de complications", "bool"),
    F("complications_moment", "Présence de complications", "checkbox_group",
      (ch("Au moment de l'accouchement"), ch("Suites de couches"))),
    F("complications_type", "Type de complications :", "checkbox_group", (
        ch("Pré-éclampsie"), ch("Eclampsie"), ch("Hémorragie"), ch("Infection"), ch("Autres"))),
    F("complications_autre", "Si autres à préciser :"),
    F("etat_nne", "Etat du nouveau-né :", "enum", (ch("Vivant"), ch("Mort-né"), ch("Décès < 24 heures", "deces_24h"))),
    F("sexe", "Sexe :", "enum", (ch("F", "F", "Féminin", "Fille"), ch("M", "M", "Masculin", "Garçon")),
      csv_column="newborn sex (0=female,1=male)", ecrit=True),
    F("poids_naissance_g", "Poids à la naissance :", "int", unit="g", plausible=(400, 6000),
      csv_column="child birth weight (g)", critique=True),
    F("perimetre_cranien_cm", "Périmètre crânien à la naissance :", "float", unit="cm", plausible=(20, 45),
      csv_column="head circumference (cm)"),
    F("anomalie", "Anomalie à préciser :"),
    F("age_gestationnel_sa", "Âge gestationnel :", "float", unit="SA", plausible=(20, 45),
      csv_column="gestational age at birth (weeks)"),
))


# ------------------------------------------------------------------ post-partum
def _mere(key: str, label: str, moment: tuple[str, str]) -> SectionDef:
    return SectionDef(key, label, (
        _id("nom_patiente", "MÈRE —"),
        F("moment", "Moment de la consultation", "enum", (ch(moment[0], "dans_les_delais"), ch(moment[1], "apres"))),
        F("date_consultation", "Date de la consultation :", "date"),
        F("etat_general", "Etat général :"),
        F("temperature_c", "T°", "float", unit="°C", plausible=(34, 43)),
        F("ta", "TA", "bp", unit="mmHg", plausible=(40, 250), critique=True),
        F("pouls", "Pouls", "int", unit="bpm", plausible=(30, 200)),
        F("poids_kg", "Poids", "float", unit="kg", plausible=(30, 150)),
        F("conjonctives", "Etat des conjonctives :", "enum", (ch("Normales"), ch("Décolorées"))),
        F("globe_uterin", "Présence du globe utérin", "bool"),
        F("lochies", "Etat des lochies :", "checkbox_group", (
            ch("Fade"), ch("fétide"), ch("claires"), ch("sanglantes"), ch("Jaunâtres"))),
        F("perinee", "Etat du périnée :", "checkbox_group", (
            ch("Normal"), ch("Épisiotomie"), ch("Réparée"), ch("Déchirure"))),
        F("sphincters", "Etat des sphincters (anal et urétral) :", "enum", (ch("Normal"), ch("Anormal"))),
        F("cesarienne", "Césarienne :", "bool"),
        F("cicatrice", "Etat de la cicatrice :"),
        F("seins", "Etat des seins :", "checkbox_group", (ch("Normal"), ch("lymphangite"), ch("mastite et abcès"))),
        F("mollets", "Etat des mollets :", "checkbox_group", (
            ch("Normal"), ch("Rouges"), ch("Chauds"), ch("Douloureux à la dorsiflexion"))),
        F("complication", "Présence de complication :", "bool"),
        F("complications_type", "Présence de complication :", "checkbox_group", (
            ch("Hémorragie"), ch("Complications mammaires"), ch("Infection"), ch("Anémie"),
            ch("Eclampsie"), ch("Autres"), ch("Phlébite"))),
        F("prise_medicaments", "Notion de prise de médicaments :", "bool"),
        F("medicaments", "Notion de prise de médicaments :"),
        F("traitement", "Traitement prescrit :", "checkbox_group", (ch("Fer"), ch("Vitamine A"))),
        F("traitement_autre", "Autres à préciser :"),
        F("prochain_rdv", "Prochain rendez-vous le", "date"),
        F("pf_desire", "Désire utiliser une méthode", "bool"),
        F("pf_methode", "Si oui, laquelle :", "checkbox_group", (ch("pilule"), ch("DIU"))),
        F("pf_autre", "Autre à préciser :"),
        F("pf_prescription", "Prescription faite", "bool"),
        F("pf_referee", "Référée :", "bool"),
        F("pf_pourquoi", "Si la mère ne désire pas une méthode contraceptive : Pourquoi ?"),
    ))


def _nne(key: str, label: str) -> SectionDef:
    return SectionDef(key, label, (
        F("date_consultation", "Date de la consultation :", "date"),
        F("age", "Age"),
        F("temperature_c", "Température", "float", unit="°C", plausible=(32, 43)),
        F("poids_g", "Poids", "int", unit="g", plausible=(400, 9000)),
        F("taille_cm", "Taille", "float", unit="cm", plausible=(25, 80)),
        F("perimetre_cranien_cm", "Périmètre crânien", "float", unit="cm", plausible=(20, 50)),
        F("premature", "Nouveau-né prématuré", "bool"),
        F("hypotrophe", "Nouveau-né hypotrophe", "bool"),
        F("allaitement", "Allaitement :", "enum", (
            ch("exclusivement au sein", "exclusif"), ch("Artificiel"), ch("mixte")),
          csv_column="breastfeeding initiated"),
        F("signes_graves", "Signes d'une affection grave :", "checkbox_group", (
            ch("Convulsions"), ch("Refus de téter"), ch("Hématémèses"), ch("Mélaenas"), ch("Diarrhée"),
            ch("Ictère"), ch("Tirage sous costal"), ch("Toux"), ch("Rythme respiratoire anormal"),
            ch("Fièvre"), ch("Hypothermie"))),
        F("signes_graves_autre", "Autres à préciser :", context="Signes d'une affection grave :"),
        F("traumatismes", "Contusions, lésions traumatiques et malformations :", "checkbox_group", (
            ch("Bosse sérosanguine ou céphalohématome", "bosse_cephalohematome"),
            ch("Luxation congénitale de la hanche", "luxation_hanche"),
            ch("Diminution ou absence de la mobilité d'un membre", "mobilite_membre"))),
        F("traumatismes_autre", "Autres à préciser :", context="Contusions, lésions traumatiques et malformations :"),
        F("evaluation_allaitement", "Evaluation de l'allaitement maternel :", "enum",
          (ch("Normal"), ch("A problèmes"))),
        F("vaccins", "Vaccins administrés ce jour :", "checkbox_group", (ch("BCG"), ch("HB"))),
        F("vitamine_d", "Supplémentation en vitamine D", "bool"),
        F("complications", "Présence de complications et de malformation :", "checkbox_group", (
            ch("Ictère"), ch("Infection"), ch("Conjonctivite"), ch("Traumatisme"), ch("Malformation"), ch("Autres"))),
        _id("vu_par", "Vu par :"),
        F("decision", "Décision prise :"),
        F("traitement", "Traitement prescrit :"),
        F("transfert", "Transfert", "bool", csv_column="referral to higher care"),
        F("etablissement_reference", "Préciser l'établissement de référence :"),
        F("prochaine_visite", "Revenir pour une visite de suivi nécessaire le", "date"),
    ))


PP_PRECOCE_MERE = _mere("pp_precoce_mere", "Post-partum précoce – mère",
                        ("Entre le 7ème et 8ème jour après l'accouchement", "Après le 8ème jour de l'accouchement"))
PP_PRECOCE_NNE = _nne("pp_precoce_nne", "Post-partum précoce – nouveau-né")
PP_TARDIF_MERE = _mere("pp_tardif_mere", "Post-partum tardif – mère",
                       ("Entre le 40ème et 50ème jour après l'accouchement", "Après le 50ème jour de l'accouchement"))
PP_TARDIF_NNE = _nne("pp_tardif_nne", "Post-partum tardif – nouveau-né")

# Résumé lisible : champs cliniques montrés en premier (motifs fnmatch, dans cet ordre)
PRIORITE = (
    "couverture.numero_fiche", "couverture.region", "couverture.province", "couverture.etablissement",
    "couverture.type_etablissement", "couverture.mode_couverture", "couverture.grossesse_a_risque",
    "couverture.type_risque",
    "identification.age", "identification.consanguinite", "identification.grossesse_desiree",
    "antecedents_obstetricaux.gestite", "antecedents_obstetricaux.parite", "antecedents_obstetricaux.enfants_vivants",
    "antecedents_femme.*", "antecedents_familiaux.femme.*",
    "grossesse_actuelle.ddr", "grossesse_actuelle.dpa", "grossesse_actuelle.groupage", "grossesse_actuelle.rhesus",
    "grossesse_actuelle.visites.*.venue_le", "grossesse_actuelle.visites.*.ta",
    "grossesse_actuelle.visites.*.age_probable_sa", "grossesse_actuelle.visites.*.poids_kg",
    "grossesse_actuelle.visites.*.hemoglobine", "grossesse_actuelle.visites.*.glycemie",
    "grossesse_actuelle.visites.*.vih", "grossesse_actuelle.visites.*.syphilis", "grossesse_actuelle.visites.*.ag_hbs",
    "grossesse_actuelle.visites.*.bcf", "grossesse_actuelle.visites.*.hu_cm",
    "accouchement.date", "accouchement.lieu", "accouchement.mode", "accouchement.etat_nne", "accouchement.sexe",
    "accouchement.poids_naissance_g", "accouchement.age_gestationnel_sa", "accouchement.complications",
    "pp_*.date_consultation", "pp_*.ta", "pp_*.temperature_c", "pp_*.pouls", "pp_*.poids*",
    "pp_*.complication*", "pp_*.allaitement", "pp_*.signes_graves", "pp_*.transfert",
)

TEMPLATE = Template(
    key="carnet_maroc",
    label_fr="Fiche de surveillance de la grossesse et du post-partum (Maroc)",
    sections=(COUVERTURE, IDENTIFICATION, ANTECEDENTS_FAMILIAUX, ANTECEDENTS_FEMME, ANTECEDENTS_OBSTETRICAUX,
              GROSSESSE_ACTUELLE, ACCOUCHEMENT, PP_PRECOCE_MERE, PP_PRECOCE_NNE, PP_TARDIF_MERE, PP_TARDIF_NNE),
    priority=PRIORITE,
    page_types=(
        PageType("couverture", ("FICHE DE SURVEILLANCE DE LA GROSSESSE",), ("couverture",),
                 ("fiche de surveillance", "nom de l'etablissement", "type de l'etablissement",
                  "grossesse classee a risque", "mode de la couverture"), "Couverture", ((0.42, 0.66),)),
        PageType("identification_antecedents", ("IDENTIFICATION ET ANTÉCÉDENTS",),
                 ("identification", "antecedents_familiaux", "antecedents_femme", "antecedents_obstetricaux"),
                 ("identification", "consanguinite", "antecedents hereditaires", "antecedents de la femme",
                  "antecedents obstetricaux", "accouchements anterieurs", "vaccinee contre"),
                 "Identification et antécédents", ((0.06, 0.29),)),
        PageType("grossesse_actuelle", ("GROSSESSE ACTUELLE",), ("grossesse_actuelle",),
                 ("grossesse actuelle", "date prevue d'accouchement", "depassement de terme", "trimestre",
                  "prestations", "examen clinique", "examen biologique"), "Grossesse actuelle", ((0.82, 0.91),)),
        PageType("accouchement", ("DÉROULEMENT DE L'ACCOUCHEMENT",), ("accouchement",),
                 ("deroulement de l'accouchement", "mode de l'accouchement", "en milieu surveille",
                  "poids a la naissance", "voie basse"), "Accouchement", ((0.04, 0.17),)),
        PageType("pp_precoce_mere", ("POST-PARTUM PRÉCOCE", "Etat des lochies"), ("pp_precoce_mere",),
                 ("lochies", "perinee", "8eme jour", "planification familiale"), "Post-partum précoce – mère", ((0.03, 0.12),)),
        PageType("pp_precoce_nne", ("POST-PARTUM PRÉCOCE", "NOUVEAU-NÉ"), ("pp_precoce_nne",),
                 ("affection grave", "vitamine d", "allaitement maternel", "refus de teter"),
                 "Post-partum précoce – nouveau-né", ((0.66, 0.75),)),
        PageType("pp_tardif_mere", ("POST-PARTUM TARDIF", "Etat des lochies"), ("pp_tardif_mere",),
                 ("lochies", "perinee", "50eme jour", "planification familiale"), "Post-partum tardif – mère", ((0.03, 0.12),)),
        PageType("pp_tardif_nne", ("POST-PARTUM TARDIF", "NOUVEAU-NÉ"), ("pp_tardif_nne",),
                 ("affection grave", "vitamine d", "allaitement maternel", "refus de teter"),
                 "Post-partum tardif – nouveau-né", ((0.66, 0.75),)),
    ),
)

# Ordre des pages du PDF spécimen (8 pages par patiente)
SPECIMEN_PAGE_ORDER = ("couverture", "identification_antecedents", "grossesse_actuelle", "accouchement",
                       "pp_precoce_mere", "pp_precoce_nne", "pp_tardif_mere", "pp_tardif_nne")
