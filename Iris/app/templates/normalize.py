"""Normalisation des valeurs saisies à la main, selon le type du champ.

Partagée par la vérité terrain, l'évaluateur et (bloc 3b) la sortie de l'IA :
dates -> jj/mm/aaaa, nombres -> float/int (unités retirées), TA -> {"sys","dia"}
en mmHg (11/7 en cmHg -> 110/70), choix -> code.

`EMPTY_MARKS` : ce qui veut dire « rien d'écrit » (tiret, vide). Une valeur
normalisée à None signifie « champ vide » (statut attendu NON_FOURNI).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .base import FieldDef, norm_label

MISSING_GLYPH = "�"   # glyphe absent de la police manuscrite (accent non rendu sur l'image)
EMPTY_MARKS = {"", "-", "--", "—", "–", "/", "//", "-/-", "...", "…"}


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


def is_empty(raw: Any) -> bool:
    """Rien d'écrit : None, tiret, ou uniquement des glyphes non rendus (tiret absent de la police)."""
    if raw is None or raw == []:
        return True
    return isinstance(raw, str) and clean_text(raw).replace(MISSING_GLYPH, "").strip() in EMPTY_MARKS


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
    if re.search(r"\d\s*k\b|\dk$", s):          # « 186k » plaquettes
        v *= 1000
    return v


def parse_ga(raw: Any) -> float | None:
    """Âge gestationnel : '38 SA', '16SA+3j', '31,5' -> semaines (1 décimale)."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return round(float(raw), 1)
    s = clean_text(raw).lower().replace(" ", "")
    m = re.match(r"(\d+(?:[.,]\d+)?)(?:sa)?(?:\+(\d+)j?)?", s)
    if not m:
        return None
    w = float(m.group(1).replace(",", "."))
    if m.group(2):
        w += int(m.group(2)) / 7
    return round(w, 1)


def parse_date(raw: Any) -> str | None:
    """'3/2/26', '03-02-2026', '2026-02-03' -> '03/02/2026'. Partiel ('2023') -> renvoyé tel quel."""
    s = clean_text(raw)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.match(r"^(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})$", s)
        if not m:
            return s or None
        d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}/{int(mo):02d}/{y}"


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
        sys_, dia = float(nums[0]), float(nums[1])
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
    n = fold(str(raw))
    if n in ("oui", "o", "yes", "true", "1", "x", "+"):
        return True
    if n in ("non", "n", "no", "false", "0"):
        return False
    return None


# ---------------------------------------------------------------- entrée principale
def normalize_value(f: FieldDef, raw: Any) -> Any:
    """Valeur brute (texte manuscrit ou sortie IA) -> valeur canonique ; None si vide/illisible."""
    if is_empty(raw):
        return None
    t = f.type
    if t == "bp":
        return parse_bp(raw)
    if t in ("int", "float"):
        v = parse_ga(raw) if f.unit == "SA" else parse_number(raw)
        if v is None:
            return None
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
    return clean_text(raw)


def values_equal(f: FieldDef, truth: Any, pred: Any) -> bool:
    """Comparaison tolérante (après normalisation) : nombres ±1 %, textes sans casse/accents,
    glyphe manquant de la vérité = joker d'un caractère."""
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
        fa, fb = fold(a), fold(b)
        if MISSING_GLYPH in fa:
            pat = "^" + ".?".join(re.escape(p) for p in fa.split(MISSING_GLYPH)) + "$"
            return re.match(pat, fb) is not None
        return fa == fb
    return a == b
