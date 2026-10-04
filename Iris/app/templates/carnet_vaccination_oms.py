"""Carnet international de vaccination (modèle OMS, ex. Côte d'Ivoire) — page « AUTRES VACCINATIONS ».

Un fichier modèle = un carnet : ses sections et ses types de page sont INCLUS dans le modèle actif
(carnet_maroc.TEMPLATE), si bien que liste blanche, 2e avis, /verif et conversation s'appliquent
tels quels. Lecture dédiée : ai/vaccination.py (encre bleue seule, colonnes par lignes verticales).

Tableau imprimé à 4 colonnes : date | vaccin | dose | signature du médecin — le N° DE LOT est écrit
dans la colonne signature (tampon et signature ignorés). Une entrée peut couvrir 2 lignes imprimées :
on regroupe par LIGNE D'ÉCRITURE. Une date au crayon gris = rappel probable (toujours à vérifier).
"""
from .base import FieldDef as F, PageType, SectionDef

MAX_ENTREES = 12

VACCINS = (
    "Méningite ACYW", "Méningite A", "Typhoïde", "VAT", "Hépatite B", "Hépatite A", "Dultavax", "ROR",
    "Fièvre jaune", "Polio", "Rage", "Tétanos", "DTC", "DTCoq", "BCG", "Grippe", "Covid-19", "Pneumocoque",
    "HPV", "Varicelle", "Choléra", "Typhim Vi", "Menveo", "Stamaril", "Revaxis", "Twinrix", "Engerix B",
)

# Toutes les cellules sont « critiques » : CONNU seulement si le 2e avis Ollama lit la même chose.
_ENTRY = (
    ("date", "Date", "date"),
    ("vaccin", "Vaccin", "str"),
    ("dose", "Dose", "str"),
    ("lot", "N° de lot", "str"),
    ("rappel", "Date de rappel ?", "date"),
)
VACCINATIONS = SectionDef("vaccinations", "Autres vaccinations", tuple(
    F(f"E{i}.{k}", f"{label} (ligne {i})", typ, critique=True,
      vocabulaire=tuple((v, ()) for v in VACCINS) if k == "vaccin" else ())
    for i in range(1, MAX_ENTREES + 1) for k, label, typ in _ENTRY))

# Couverture : identifiants directs uniquement -> rien n'est jamais stocké (liste blanche)
VACCINATION_COUVERTURE = SectionDef("vaccination_couverture", "Certificat de vaccination – couverture", (
    F("nom", "Nom", identifiant=True),
    F("numero_certificat", "N° de certificat", identifiant=True),
    F("passeport", "Passeport", identifiant=True),
    F("date_naissance", "Date de naissance", identifiant=True),
    F("signature", "Signature", identifiant=True),
))

SECTIONS = (VACCINATIONS, VACCINATION_COUVERTURE)
PAGE_TYPES = (
    PageType("vaccinations", ("AUTRES VACCINATIONS", "OTHER VACCINATIONS"), ("vaccinations",),
             ("vaccinations", "vaccine", "dose", "signature du medecin", "lot"), "Autres vaccinations"),
    PageType("vaccination_couverture", ("CERTIFICAT INTERNATIONAL DE VACCINATION",
                                        "INTERNATIONAL CERTIFICATE OF VACCINATION"),
             ("vaccination_couverture",), ("certificat", "passeport", "passport"), "Certificat de vaccination"),
)
