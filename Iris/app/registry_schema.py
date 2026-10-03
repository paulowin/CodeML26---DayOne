"""Schéma de champs du registre maternel (source de vérité partagée par
le backend, le cerveau IA (bloc 3) et le flux conversationnel (bloc 4)).

On part du schéma, pas de l'OCR : chaque champ a un type, des valeurs
permises et éventuellement une plage plausible. Les identifiants directs
(nom, téléphone, adresse, n° national...) NE FONT PAS partie du schéma et
sont filtrés par `sanitize_extraction`.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldDef:
    key: str
    label_fr: str
    type: str                              # int | float | str | bool | date | enum | list
    choices: tuple[str, ...] = ()
    unit: str | None = None
    plausible: tuple[float, float] | None = None
    longitudinal: bool = False             # varie d'une visite à l'autre


@dataclass(frozen=True)
class SectionDef:
    key: str
    label_fr: str
    fields: tuple[FieldDef, ...] = field(default_factory=tuple)


POS_NEG = ("POSITIF", "NEGATIF", "NON_FAIT")
OUI_NON = ("OUI", "NON")

SECTIONS: tuple[SectionDef, ...] = (
    SectionDef("identification", "Identification (non nominative)", (
        FieldDef("code_patiente", "Code patiente (attribué par la sage-femme)", "str"),
        FieldDef("date_visite", "Date de la visite", "date", longitudinal=True),
    )),
    SectionDef("profil", "Profil", (
        FieldDef("age", "Âge", "int", unit="ans", plausible=(10, 60)),
        FieldDef("village_zone", "Village / zone", "str"),
        FieldDef("consanguinite", "Consanguinité", "enum", OUI_NON),
        FieldDef("grossesse_desiree", "Grossesse désirée", "enum", OUI_NON),
    )),
    SectionDef("antecedents_medicaux", "Antécédents médicaux et familiaux", (
        FieldDef("hypertension", "Hypertension", "enum", OUI_NON),
        FieldDef("diabete", "Diabète", "enum", OUI_NON),
        FieldDef("maladies_hereditaires", "Maladies héréditaires", "str"),
        FieldDef("malformations", "Malformations", "str"),
        FieldDef("allergies", "Allergies", "str"),
    )),
    SectionDef("antecedents_obstetricaux", "Antécédents obstétricaux", (
        FieldDef("gestite", "Gestité", "int", plausible=(0, 20)),
        FieldDef("parite", "Parité", "int", plausible=(0, 20)),
        FieldDef("enfants_vivants", "Enfants vivants", "int", plausible=(0, 20)),
        FieldDef("avortements", "Avortements", "int", plausible=(0, 20)),
        FieldDef("prematures", "Accouchements prématurés", "int", plausible=(0, 20)),
        FieldDef("morts_foetales", "Morts fœtales", "int", plausible=(0, 20)),
        # liste d'objets {date, mode, indication_cesarienne, complications, poids_g}
        FieldDef("accouchements_anterieurs", "Accouchements antérieurs", "list"),
    )),
    SectionDef("grossesse_en_cours", "Grossesse en cours", (
        FieldDef("ddr", "Date des dernières règles / datation", "date"),
        FieldDef("dpa", "Date prévue d'accouchement", "date"),
        FieldDef("age_gestationnel_sa", "Âge gestationnel", "float", unit="SA", plausible=(0, 45), longitudinal=True),
        FieldDef("poids_kg", "Poids", "float", unit="kg", plausible=(30, 200), longitudinal=True),
        FieldDef("ta_systolique", "Tension systolique", "int", unit="mmHg", plausible=(60, 250), longitudinal=True),
        FieldDef("ta_diastolique", "Tension diastolique", "int", unit="mmHg", plausible=(30, 150), longitudinal=True),
        FieldDef("temperature_c", "Température", "float", unit="°C", plausible=(34, 43), longitudinal=True),
        FieldDef("examen_clinique", "Examen clinique", "str", longitudinal=True),
        FieldDef("mouvements_foetaux", "Mouvements fœtaux", "enum", ("PRESENTS", "ABSENTS"), longitudinal=True),
        FieldDef("bcf_bpm", "Bruits du cœur fœtal", "int", unit="bpm", plausible=(60, 220), longitudinal=True),
        FieldDef("vih", "VIH", "enum", POS_NEG, longitudinal=True),
        FieldDef("syphilis", "Syphilis", "enum", POS_NEG, longitudinal=True),
        FieldDef("hepatite_c", "Hépatite C", "enum", POS_NEG, longitudinal=True),
        FieldDef("traitement", "Traitement", "str", longitudinal=True),
        FieldDef("prochaine_visite", "Prochaine visite", "date", longitudinal=True),
    )),
    SectionDef("accouchement", "Accouchement", (
        FieldDef("lieu", "Lieu", "str"),
        FieldDef("date", "Date", "date"),
        FieldDef("mode", "Mode", "enum", ("VOIE_BASSE", "CESARIENNE", "INSTRUMENTAL")),
        FieldDef("complications", "Complications", "str"),
        FieldDef("etat_nouveau_ne", "État du nouveau-né", "str"),
        FieldDef("sexe", "Sexe", "enum", ("F", "M", "INDETERMINE")),
        FieldDef("poids_naissance_g", "Poids de naissance", "int", unit="g", plausible=(300, 6500)),
        FieldDef("perimetre_cranien_cm", "Périmètre crânien", "float", unit="cm", plausible=(20, 45)),
        FieldDef("anomalies", "Anomalies", "str"),
    )),
    SectionDef("postpartum", "Postpartum (mère)", (
        FieldDef("etat_maternel", "État maternel", "str", longitudinal=True),
        FieldDef("ta_systolique", "Tension systolique", "int", unit="mmHg", plausible=(60, 250), longitudinal=True),
        FieldDef("ta_diastolique", "Tension diastolique", "int", unit="mmHg", plausible=(30, 150), longitudinal=True),
        FieldDef("temperature_c", "Température", "float", unit="°C", plausible=(34, 43), longitudinal=True),
        FieldDef("complications", "Complications", "str", longitudinal=True),
        FieldDef("medicaments", "Médicaments", "str", longitudinal=True),
        FieldDef("planification_familiale", "Planification familiale", "str"),
    )),
    SectionDef("nouveau_ne", "Nouveau-né (suivi)", (
        FieldDef("poids_g", "Poids", "int", unit="g", plausible=(300, 8000), longitudinal=True),
        FieldDef("temperature_c", "Température", "float", unit="°C", plausible=(32, 43), longitudinal=True),
        FieldDef("allaitement", "Allaitement", "enum", ("EXCLUSIF", "MIXTE", "ARTIFICIEL", "AUCUN"), longitudinal=True),
        FieldDef("signes_danger", "Signes de danger", "str", longitudinal=True),
        FieldDef("vaccination", "Vaccination", "str", longitudinal=True),
        FieldDef("reference", "Référence", "str", longitudinal=True),
    )),
)

# Index plat : "section.champ" -> FieldDef
FIELD_INDEX: dict[str, FieldDef] = {f"{s.key}.{f.key}": f for s in SECTIONS for f in s.fields}

# ------------------------------------------------------------------ anonymisation
# Clés qui ne doivent JAMAIS être stockées, même si un modèle IA les renvoie.
FORBIDDEN_KEY_FRAGMENTS = (
    "nom", "name", "prenom", "conjoint", "mari", "epoux", "husband",
    "telephone", "phone", "tel", "adresse", "address",
    "cin", "nni", "national", "passeport", "passport", "cni",
)


def is_forbidden_key(key: str) -> bool:
    k = key.lower().replace("-", "_")
    parts = set(k.replace(".", "_").split("_"))
    return any(frag in parts for frag in FORBIDDEN_KEY_FRAGMENTS)


def sanitize_extraction(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Ne garde que les clés connues du schéma. Retourne (champs_gardés, clés_rejetées).

    Liste blanche stricte : tout champ hors schéma est jeté (dont les identifiants).
    """
    kept, rejected = {}, []
    for key, val in fields.items():
        if key in FIELD_INDEX and not is_forbidden_key(key.split(".")[-1]):
            kept[key] = val
        else:
            rejected.append(key)
    return kept, rejected
