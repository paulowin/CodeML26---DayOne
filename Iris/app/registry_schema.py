"""Schéma de champs du registre maternel (source de vérité partagée par
le backend, le cerveau IA (bloc 3) et le flux conversationnel (bloc 4)).

Généré depuis le template du carnet (`app/templates/carnet_maroc.py`) :
on part du formulaire imprimé, pas de l'OCR. Chaque champ a un type, des
valeurs permises et éventuellement une plage plausible. Les identifiants
directs (nom, téléphone, adresse, CIN, « Vu par »...) sont décrits dans le
template (`identifiant=True`) mais exclus de `FIELD_INDEX` et filtrés par
`sanitize_extraction`.
"""
from typing import Any

from app.templates import get_template
from app.templates.base import FieldDef, SectionDef  # noqa: F401  (réexport)

TEMPLATE = get_template()
SECTIONS: tuple[SectionDef, ...] = TEMPLATE.sections

# ------------------------------------------------------------------ anonymisation
# Clés qui ne doivent JAMAIS être stockées, même si un modèle IA les renvoie.
FORBIDDEN_KEY_FRAGMENTS = (
    "nom", "name", "prenom", "conjoint", "mari", "epoux", "husband",
    "telephone", "phone", "tel", "adresse", "address",
    "cin", "nni", "national", "passeport", "passport", "cni",
)
FORBIDDEN_KEY_SEQUENCES = ("vu_par", "fait_par", "nom_prenom")


def is_forbidden_key(key: str) -> bool:
    k = key.lower().replace("-", "_").replace(".", "_")
    parts = set(k.split("_"))
    return any(frag in parts for frag in FORBIDDEN_KEY_FRAGMENTS) or any(s in k for s in FORBIDDEN_KEY_SEQUENCES)


# Index plat : "section.champ" (ou clé indexée "section.table.col.ligne") -> FieldDef.
# Les champs identifiants n'y figurent pas : ils ne sont jamais stockés.
FIELD_INDEX: dict[str, FieldDef] = {k: f for k, f in TEMPLATE.stored_fields.items()}
IDENTIFIER_KEYS: frozenset[str] = frozenset(TEMPLATE.identifier_fields)

_bad = [k for k in FIELD_INDEX if is_forbidden_key(k.split(".")[-1])]
assert not _bad, f"clés du template refusées par is_forbidden_key : {_bad}"


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
