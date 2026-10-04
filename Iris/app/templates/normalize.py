"""Normalisation des valeurs saisies à la main, selon le type du champ.

Partagée par la vérité terrain, l'évaluateur, le cerveau IA (`ai/`) et le backend :
- `normalize_value` : forme CANONIQUE pour comparer (dates jj/mm/aaaa, nombres
  sans unité, TA {"sys","dia"} en mmHg, choix -> code, RAS/NÉGATIF/POSITIF) ;
- `interpret` : valeur à STOCKER + statut implicite (tiret -> NON_APPLICABLE,
  vide -> NON_FOURNI, illisible -> ILLISIBLE) + drapeaux ; dates en ISO.

Conventions d'écriture du carnet : « 11/7 » = TA en cmHg (110/70 mmHg),
« 16SA+3j » = 16 semaines 3 jours, glycémie en g/L (stockée en mg/dL),
« 1G » = gestité 1, « 00 » = 0.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .base import FieldDef, norm_label

MISSING_GLYPH = "�"   # glyphe absent de la police manuscrite (accent non rendu sur l'image)
DASH_MARKS = {"-", "--", "—", "–", "/", "//", "-/-", "_", "__"}
EMPTY_MARKS = {"", "...", "…"} | DASH_MARKS
ILLEGIBLE_MARK = "#ILLISIBLE"
CROSSED_MARK = "#BARRE"

RAS = "RAS"
NEGATIF, POSITIF = "NEGATIF", "POSITIF"
_RAS_RE = re.compile(r"^(r\s*\.?\s*a\s*\.?\s*s\s*\.?|neant|aucun|aucune|rien)$")
_NEG_RE = re.compile(r"^(neg|negatif|negative|negatifs?|nég)\s*\.?$")
_POS_RE = re.compile(r"^(pos|positif|positive)?\s*\.?\s*\+{0,3}$")
# champs où « Aucun » est une vraie réponse, pas « rien à signaler »
NO_RAS_KEYS = {"niveau_instruction", "profession", "profession_partenaire"}


def clean_text(s: Any) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\x00", MISSING_GLYPH)
    return re.sub(r"\s+", " ", s).strip()


def fold(s: str) -> str:
    """Casse + accents + espaces : pour comparer des textes libres."""
    s = clean_text(s).lower().replace("œ", "oe").replace(MISSING_GLYPH, "\x01")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().replace("\x01", MISSING_GLYPH)
    s = re.sub(r"[\s.,;:'’\"]+", " ", s)
    return s.strip()


def _bare(raw: Any) -> str:
    return clean_text(raw).replace(MISSING_GLYPH, "").strip()


def is_empty(raw: Any) -> bool:
    """Rien d'écrit : None, tiret, ou uniquement des glyphes non rendus (tiret absent de la police)."""
    if raw is None or raw == []:
        return True
    return isinstance(raw, str) and _bare(raw) in EMPTY_MARKS


def is_dash(raw: Any) -> bool:
    return isinstance(raw, str) and (_bare(raw) in DASH_MARKS or (clean_text(raw) and not _bare(raw)))


# ---------------------------------------------------------------- parseurs
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_number(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = clean_text(raw).lower().replace(" ", "")
    m = _NUM.search(s)
    if not m:
        return None
    v = float(m.group().replace(",", "."))
    if re.search(r"\dk(?![a-z])", s):           # « 186k » plaquettes
        v *= 1000
    return v


def parse_ga(raw: Any) -> float | None:
    """Âge gestationnel : '38 SA', '16SA+3j', '16 SA 3j', '31,5' -> semaines (1 décimale)."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return round(float(raw), 1)
    s = clean_text(raw).lower().replace(" ", "")
    m = re.match(r"(\d+(?:[.,]\d+)?)(?:sa|s)?(?:\+?(\d)j)?", s)
    if not m:
        return None
    w = float(m.group(1).replace(",", "."))
    if m.group(2):
        w += int(m.group(2)) / 7
    return round(w, 1)


def parse_date(raw: Any) -> str | None:
    """'3/2/26', '03-02-2026', '/19/05/2025/', '2026-02-03' -> '03/02/2026'.
    Date partielle ('12/05', '2023') : renvoyée telle quelle (voir `is_full_date`)."""
    s = clean_text(raw).strip(" /.-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.match(r"^(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})$", s)
        if not m:
            m2 = re.match(r"^(\d{1,2})\s*[/.\-]\s*(\d{1,2})$", s)
            return f"{int(m2.group(1)):02d}/{int(m2.group(2)):02d}" if m2 else (s or None)
        d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}/{int(mo):02d}/{y}"


def is_full_date(d: Any) -> bool:
    if not isinstance(d, str) or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", d):
        return False
    try:
        to_date(d)
        return True
    except ValueError:
        return False


def to_date(d: str) -> date:
    day, month, year = (int(x) for x in d.split("/"))
    return date(year, month, day)


def to_iso(d: str) -> str:
    return to_date(d).isoformat()


def parse_bp(raw: Any) -> dict | None:
    """'104/74', '11/7' (cmHg) -> {'sys': 110, 'dia': 70} ; dict déjà structuré accepté."""
    if isinstance(raw, dict):
        try:
            sys_, dia = float(raw["sys"]), float(raw["dia"])
        except (KeyError, TypeError, ValueError):
            return None
    else:
        nums = _NUM.findall(clean_text(raw).replace(",", "."))
        if len(nums) < 2:
            return None
        sys_, dia = abs(float(nums[0])), abs(float(nums[1]))
    if sys_ < 30 and dia < 20:                  # écrit en cmHg sur le carnet
        sys_, dia = sys_ * 10, dia * 10
    return {"sys": int(round(sys_)), "dia": int(round(dia))}


def parse_choice(f: FieldDef, raw: Any) -> str | None:
    if raw in f.choice_codes:
        return raw
    c = f.choice_by_label(clean_text(raw))
    if c:
        return c.code
    n = norm_label(clean_text(raw))
    for c in f.choices:
        if n == c.code or n.replace(" ", "_") == c.code:
            return c.code
    return clean_text(raw) or None


def parse_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, list):
        return bool(raw)
    n = fold(str(raw))
    if n in ("oui", "o", "yes", "true", "1", "x", "+", "coche"):
        return True
    if n in ("non", "n", "no", "false", "0"):
        return False
    return None


def canonical_text(f: FieldDef, raw: Any) -> str:
    """Texte libre : RAS / NEGATIF / POSITIF unifiés, le reste nettoyé."""
    t = clean_text(raw)
    n = fold(t)
    if f.key.split(".")[-1] not in NO_RAS_KEYS and _RAS_RE.match(n):
        return RAS
    if _NEG_RE.match(n):
        return NEGATIF
    if n and _POS_RE.match(n) and ("pos" in n or "+" in n):
        return POSITIF
    return t


def _scale_units(f: FieldDef, raw: Any, v: float) -> float:
    s = clean_text(raw).lower() if isinstance(raw, str) else ""
    if f.unit == "mg/dL" and (v < 5 or ("g/l" in s and "mg" not in s)):
        return v * 100                           # glycémie g/L -> mg/dL
    if f.unit == "g" and (v < 10 or re.search(r"\dkg|\d\s*kg", s)):
        return v * 1000                          # poids écrit en kg
    return v


# ---------------------------------------------------------------- entrée principale
def normalize_value(f: FieldDef, raw: Any) -> Any:
    """Valeur brute (texte manuscrit ou sortie IA) -> valeur canonique ; None si vide/illisible."""
    if is_empty(raw) or raw in (ILLEGIBLE_MARK, CROSSED_MARK):
        return None
    t = f.type
    if t == "bp":
        return parse_bp(raw)
    if t in ("int", "float"):
        v = parse_ga(raw) if f.unit == "SA" else parse_number(raw)
        if v is None:
            return None
        v = _scale_units(f, raw, v)
        return int(round(v)) if t == "int" else round(v, 2)
    if t == "date":
        return parse_date(raw)
    if t == "enum":
        return parse_choice(f, raw)
    if t == "bool":
        return parse_bool(raw)
    if t == "checkbox_group":
        items = raw if isinstance(raw, (list, tuple, set)) else re.split(r"[,;]", str(raw))
        return sorted({parse_choice(f, x) for x in items if not is_empty(x)} - {None})
    return canonical_text(f, raw)


@dataclass
class Interpretation:
    value: Any                       # valeur à stocker (dates ISO) ou None
    status: str | None               # statut imposé par l'écriture (None : décidé par la confiance)
    flags: list[str] = field(default_factory=list)


def interpret(f: FieldDef, raw: Any, etat: str | None = None) -> Interpretation:
    """Lecture brute + état visuel -> valeur stockable + statut implicite + drapeaux."""
    etat = (etat or "").upper()
    if etat == "TIRET":
        return Interpretation(None, "NON_APPLICABLE")
    if etat == "VIDE":
        return Interpretation(None, "NON_FOURNI")
    if etat == "BARRE" or raw == CROSSED_MARK:
        return Interpretation(None, "NON_APPLICABLE", ["barre"])
    if etat == "ILLISIBLE" or raw == ILLEGIBLE_MARK:
        return Interpretation(None, "ILLISIBLE")
    if f.type in ("bool", "checkbox_group") and isinstance(raw, (list, bool)):
        return Interpretation(normalize_value(f, raw), None)
    if raw is None or (isinstance(raw, str) and not _bare(raw) and not is_dash(raw)):
        return Interpretation(None, "NON_FOURNI")
    if is_dash(raw):
        return Interpretation(None, "NON_APPLICABLE")
    v = normalize_value(f, raw)
    flags = []
    if v is None:
        return Interpretation(None, None, ["type_invalide"])
    if f.type == "date":
        if is_full_date(v):
            v = to_iso(v)
        else:
            flags.append("date_partielle")
    elif f.type == "enum" and v not in f.choice_codes:
        flags.append("choix_inconnu")
    return Interpretation(v, None, flags)


# ---------------------------------------------------------------- comparaison
def values_equal(f: FieldDef, truth: Any, pred: Any) -> bool:
    """Comparaison tolérante (après normalisation) : nombres ±1 %, textes sans casse/accents
    (dans les deux sens), glyphe manquant = joker d'un caractère."""
    a, b = normalize_value(f, truth), normalize_value(f, pred)
    if a is None or b is None:
        return a is None and b is None
    if f.type == "bp":
        return abs(a["sys"] - b["sys"]) <= max(2, a["sys"] * 0.01) and abs(a["dia"] - b["dia"]) <= max(2, a["dia"] * 0.01)
    if f.type in ("int", "float"):
        return abs(a - b) <= max(abs(a) * 0.01, 1e-9 if f.type == "float" else 0.5)
    if f.type == "checkbox_group":
        return set(a) == set(b)
    if isinstance(a, str) and isinstance(b, str):
        return text_equal(a, b)
    return a == b


_JOKER = "\x01"


def _accent_pattern(s: str) -> str:
    """Regex : chaque lettre accentuée, glyphe absent ou « ? » devient un joker optionnel."""
    marked = []
    for c in clean_text(s).lower().replace("œ", "oe"):
        base = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
        marked.append(_JOKER if c in (MISSING_GLYPH, "?") or base != c else c)
    t = re.sub(r"[\s.,;:'’\"]+", " ", "".join(marked)).strip()
    return "^" + "".join(".?" if c == _JOKER else re.escape(c) for c in t) + "$"


def text_equal(a: str, b: str) -> bool:
    """Textes égaux à la casse, la ponctuation et aux ACCENTS près, dans les deux sens :
    police sans accents côté vérité (« Coll ge ») ou modèle qui les perd (« Collge », « Coll?ge »)."""
    fa, fb = fold(a), fold(b)
    if fa == fb:
        return True
    return bool(re.match(_accent_pattern(a), fb) or re.match(_accent_pattern(b), fa))
