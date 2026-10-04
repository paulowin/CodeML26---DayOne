"""Templates de carnets papier : un carnet = un fichier (ex. `carnet_maroc.py`).

Pour ajouter un carnet : créer `app/templates/<nom>.py` exposant `TEMPLATE`,
puis l'enregistrer dans `TEMPLATES`.
"""
from . import carnet_maroc
from .base import Template

TEMPLATES: dict[str, Template] = {carnet_maroc.TEMPLATE.key: carnet_maroc.TEMPLATE}
DEFAULT_TEMPLATE = carnet_maroc.TEMPLATE.key


def get_template(key: str | None = None) -> Template:
    return TEMPLATES[key or DEFAULT_TEMPLATE]
