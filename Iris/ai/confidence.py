"""Confiance finale et statut d'un champ.

confiance = confiance déclarée par le modèle (plafonnée à 0.85 : un VLM
s'auto-évalue mal) + bonus d'ACCORD entre lectures indépendantes (bandes qui
se recouvrent, 2e avis), puis plafonds : désaccord -> ≤ 0.5, échec de
validation -> ≤ 0.4.

Statut : TIRET -> NON_APPLICABLE ; VIDE -> NON_FOURNI ; ILLISIBLE -> ILLISIBLE ;
confiance ≥ seuil -> CONNU ; sinon A_REVISER. Un champ CRITIQUE n'est jamais
CONNU sur une seule lecture.
"""
from __future__ import annotations

from dataclasses import dataclass

DECLARED_CAP = 0.85
DEFAULT_DECLARED = 0.6
AGREE_BONUS = 0.10          # deux bandes lisent la même chose
VERIFY_BONUS = 0.15         # le 2e avis confirme
DISAGREE_CAP = 0.5
INVALID_CAP = 0.4
MAX_CONF = 0.99
CHECKBOX_CAP = 0.6          # cases lues par le VLM : jamais CONNU (hallucinations mesurées)


@dataclass
class Evidence:
    declared: float | None
    n_agree: int = 1                  # lectures principales concordantes (bandes)
    disagreement: bool = False        # lectures principales OU 2e avis divergents
    verified: bool | None = None      # None : pas de 2e avis ; True : confirmé ; False : contredit
    validation_failed: bool = False


def score(e: Evidence) -> float:
    c = DEFAULT_DECLARED if e.declared is None else max(0.0, min(float(e.declared), DECLARED_CAP))
    if e.n_agree >= 2:
        c += AGREE_BONUS
    if e.verified is True:
        c += VERIFY_BONUS
    if e.disagreement or e.verified is False:
        c = min(c, DISAGREE_CAP)
    if e.validation_failed:
        c = min(c, INVALID_CAP)
    return round(max(0.0, min(c, MAX_CONF)), 3)


def readings_count(e: Evidence) -> int:
    return e.n_agree + (1 if e.verified else 0)


def status(implied: str | None, conf: float, seuil: float, critical: bool, e: Evidence) -> str:
    """`implied` = statut imposé par l'écriture (NON_APPLICABLE, NON_FOURNI, ILLISIBLE) ou None."""
    if implied:
        return implied
    if e.disagreement or e.verified is False:
        return "A_REVISER"
    if conf >= seuil and (not critical or readings_count(e) >= 2):
        return "CONNU"
    return "A_REVISER"
