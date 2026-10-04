"""Contrôles de plausibilité : type, plages du template, cohérences croisées.

Entrée : {clé: valeur stockable} (dates ISO, TA {"sys","dia"}). Sortie :
{clé: [drapeaux]}. Un drapeau ne corrige rien : il fait baisser la confiance
(le champ passe à A_REVISER) et sera expliqué à la sage-femme au bloc 4.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from app.templates import get_template
from app.templates.base import FieldDef

T = get_template()

# poids de naissance plausible (g) selon l'âge gestationnel (SA) : bornes larges (~p1/p99)
_BW_TABLE = ((24, 400, 1100), (28, 600, 1700), (32, 1000, 2600), (36, 1700, 3800), (40, 2200, 5000),
             (42, 2300, 5200))


def birth_weight_range(ga: float) -> tuple[float, float]:
    pts = _BW_TABLE
    if ga <= pts[0][0]:
        return pts[0][1], pts[0][2]
    for (g0, lo0, hi0), (g1, lo1, hi1) in zip(pts, pts[1:]):
        if ga <= g1:
            r = (ga - g0) / (g1 - g0)
            return lo0 + r * (lo1 - lo0), hi0 + r * (hi1 - hi0)
    return pts[-1][1], pts[-1][2]


def _d(v: Any) -> date | None:
    try:
        return date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check_field(f: FieldDef, v: Any) -> list[str]:
    flags = []
    if v is None:
        return flags
    if f.type in ("int", "float"):
        n = _num(v)
        if n is None:
            return ["type_invalide"]
        if f.plausible and not (f.plausible[0] <= n <= f.plausible[1]):
            flags.append("hors_plage")
    elif f.type == "bp":
        if not isinstance(v, dict) or not {"sys", "dia"} <= set(v):
            return ["type_invalide"]
        if v["sys"] <= v["dia"]:
            flags.append("ta_sys_inferieure_dia")
        lo, hi = f.plausible or (40, 250)
        if not (lo <= v["dia"] and v["sys"] <= hi):
            flags.append("hors_plage")
    elif f.type == "date":
        if _d(v) is None:
            flags.append("date_invalide")
        elif not (date(1990, 1, 1) <= _d(v) <= date(2035, 12, 31)):
            flags.append("hors_plage")
    return flags


def validate(values: dict[str, Any]) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = defaultdict(list)
    for k, v in values.items():
        f = T.fields.get(k)
        if f:
            flags[k] += check_field(f, v)

    def flag(keys, name):
        for k in keys:
            if k in values:
                flags[k].append(name)

    # antécédents obstétricaux
    g, p, ev = (_num(values.get(f"antecedents_obstetricaux.{k}")) for k in ("gestite", "parite", "enfants_vivants"))
    if g is not None and p is not None and not (g >= p >= 0):
        flag(["antecedents_obstetricaux.gestite", "antecedents_obstetricaux.parite"], "gestite_parite_incoherentes")
    if ev is not None and p is not None and ev > p + 1:
        flag(["antecedents_obstetricaux.enfants_vivants", "antecedents_obstetricaux.parite"],
             "enfants_vivants_superieurs_parite")

    # DPA ≈ DDR + 280 j
    ddr, dpa = _d(values.get("grossesse_actuelle.ddr")), _d(values.get("grossesse_actuelle.dpa"))
    if ddr and dpa and abs((dpa - ddr).days - 280) > 10:
        flag(["grossesse_actuelle.ddr", "grossesse_actuelle.dpa"], "dpa_incoherente_avec_ddr")

    # âge gestationnel de chaque visite vs DDR et date de visite (± 2 semaines)
    if ddr:
        for k, v in values.items():
            m = re.fullmatch(r"grossesse_actuelle\.visites\.(\w+)\.age_probable_sa", k)
            ga = _num(v)
            if not m or ga is None:
                continue
            visit = _d(values.get(f"grossesse_actuelle.visites.{m.group(1)}.venue_le"))
            if visit and abs((visit - ddr).days / 7 - ga) > 2:
                flag([k], "age_gestationnel_incoherent_ddr")
        acc = _d(values.get("accouchement.date"))
        ga = _num(values.get("accouchement.age_gestationnel_sa"))
        if acc and ga is not None and abs((acc - ddr).days / 7 - ga) > 2:
            flag(["accouchement.age_gestationnel_sa"], "age_gestationnel_incoherent_ddr")

    # poids de naissance vs âge gestationnel
    bw, ga = _num(values.get("accouchement.poids_naissance_g")), _num(values.get("accouchement.age_gestationnel_sa"))
    if bw is not None and ga is not None:
        lo, hi = birth_weight_range(ga)
        if not (lo <= bw <= hi):
            flag(["accouchement.poids_naissance_g", "accouchement.age_gestationnel_sa"], "poids_incoherent_avec_age")
    return {k: sorted(set(v)) for k, v in flags.items() if v}
