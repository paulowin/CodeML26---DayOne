"""Alertes cliniques simples, AIDE À LA DÉCISION (jamais un diagnostic).

Calculées UNIQUEMENT sur les champs confirmés par la sage-femme (statut CONNU + source SAGE_FEMME) :
une valeur à vérifier (A_REVISER) ou lue par l'IA seule ne déclenche jamais d'alerte.
Seuils et sources : app/templates/seuils_cliniques.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.i18n import t
from app.models import FieldSource, FieldStatus, Record
from app.templates import seuils_cliniques as S
from app.templates.normalize import POSITIF

VISIT_ORDER = ("T1V1", "T1V2", "T1V3", "T2V1", "T2V2", "T2V3", "M7", "M8", "M9")
V = "grossesse_actuelle.visites."


@dataclass
class Alert:
    code: str                         # clé i18n « alert_<code> »
    params: dict = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)   # champs à l'origine de l'alerte


def confirmed_values(rec: Record) -> dict:
    """Valeurs CONNU confirmées par la sage-femme (les seules qui comptent pour une alerte)."""
    out = {}
    for f in rec.fields:
        if f.is_current and f.status == FieldStatus.CONNU and f.source == FieldSource.SAGE_FEMME:
            try:
                out[f"{f.section}.{f.field_key}"] = json.loads(f.value_json) if f.value_json else None
            except ValueError:
                continue
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bp(v):
    return (v["sys"], v["dia"]) if isinstance(v, dict) and "sys" in v and "dia" in v else None


def _positive(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().lower()
    return v == POSITIF or s in ("oui", "pos", "positif", "positive", "+", "++", "+++", "true") \
        or bool(re.fullmatch(r"(pos(itif|itive)?\s*)?\++", s))


def _ta(bp) -> str:
    return f"{bp[0]:.0f}/{bp[1]:.0f}"


def compute(values: dict) -> list[Alert]:
    visits = []
    for col in VISIT_ORDER:
        get = lambda row: values.get(f"{V}{col}.{row}")  # noqa: E731
        visits.append({"col": col, "ta": _bp(get("ta")), "sa": _num(get("age_probable_sa")),
                       "alb": _positive(get("albuminurie")), "oed": _positive(get("oedemes")),
                       "hb": _num(get("hemoglobine")), "bcf": _num(get("bcf"))})
    alerts: list[Alert] = []

    # tension : la visite la plus haute décide entre « HTA sévère » et « HTA gravidique possible »
    hta = [v for v in visits if v["ta"] and (v["ta"][0] >= S.TA_HTA_SYS or v["ta"][1] >= S.TA_HTA_DIA)]
    if hta:
        sev = [v for v in hta if v["ta"][0] >= S.TA_SEVERE_SYS or v["ta"][1] >= S.TA_SEVERE_DIA]
        top, severe = max(sev or hta, key=lambda v: v["ta"]), bool(sev)
        alerts.append(Alert("hta_severe" if severe else "hta", {"ta": _ta(top["ta"])}, [f"{V}{top['col']}.ta"]))

    # pré-éclampsie : TA ≥ 140/90 ET albuminurie positive, après 20 SA (même visite)
    pe = [v for v in hta if v["alb"] and v["sa"] is not None and v["sa"] >= S.PREECLAMPSIE_SA_MIN]
    if pe:
        v = max(pe, key=lambda v: v["ta"])
        oed = any(x["oed"] for x in pe)
        alerts.append(Alert("preeclampsie_oed" if oed else "preeclampsie", {"ta": _ta(v["ta"])},
                            [f"{V}{v['col']}.ta", f"{V}{v['col']}.albuminurie"]))

    # TA en hausse : TAS strictement croissante sur N visites consécutives renseignées
    tas = [v for v in visits if v["ta"]]
    n = S.TA_HAUSSE_VISITES
    for i in range(len(tas) - n, -1, -1):              # la série la plus récente
        seq = tas[i:i + n]
        if all(a["ta"][0] < b["ta"][0] for a, b in zip(seq, seq[1:])):
            alerts.append(Alert("ta_hausse", {"seq": " → ".join(_ta(v["ta"]) for v in seq)},
                                [f"{V}{v['col']}.ta" for v in seq]))
            break

    # anémie : Hb la plus basse
    hbs = [v for v in visits if v["hb"] is not None and v["hb"] < S.HB_ANEMIE]
    if hbs:
        v = min(hbs, key=lambda v: v["hb"])
        alerts.append(Alert("anemie_severe" if v["hb"] < S.HB_ANEMIE_SEVERE else "anemie",
                            {"hb": f"{v['hb']:g}".replace(".", ",")}, [f"{V}{v['col']}.hemoglobine"]))

    # BCF hors 110-160
    bad = [v for v in visits if v["bcf"] is not None and not S.BCF_MIN <= v["bcf"] <= S.BCF_MAX]
    if bad:
        alerts.append(Alert("bcf", {"bcf": ", ".join(f"{v['bcf']:.0f}" for v in bad)},
                            [f"{V}{v['col']}.bcf" for v in bad]))

    # dépassement de terme : > 41 SA sans accouchement enregistré
    sa = [v for v in visits if v["sa"] is not None and v["sa"] > S.TERME_DEPASSE_SA]
    if sa and not any(k.startswith("accouchement.") for k in values):
        v = max(sa, key=lambda v: v["sa"])
        alerts.append(Alert("terme", {"sa": f"{v['sa']:g}"}, [f"{V}{v['col']}.age_probable_sa"]))
    return alerts


def record_alerts(rec: Record) -> list[Alert]:
    return compute(confirmed_values(rec))


def message(alerts: list[Alert], lang: str | None) -> str | None:
    """« ⚠️ Signes d'alerte : … À évaluer selon le protocole. » (None s'il n'y a rien)."""
    if not alerts:
        return None
    return t(lang, "alerts", items=" ; ".join(t(lang, f"alert_{a.code}", **a.params) for a in alerts))
