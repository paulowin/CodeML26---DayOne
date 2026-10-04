"""Lecture géométrique des pages du PDF spécimen (pdfplumber).

Chaque page du PDF est légèrement tournée (effet « scan », ±0,5°) et chaque
caractère manuscrit a sa propre inclinaison. On redresse tout dans un repère
commun (rotation inverse de l'angle dominant des caractères imprimés), puis
on regroupe les caractères en mots et en lignes.

Repère redressé : x vers la droite, y vers le BAS (comme `top` de pdfplumber).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

PRINT_FONTS = ("Helvetica",)  # tout le reste (Caveat, NanumPen, Gaegu...) = manuscrit


def is_print_font(fontname: str) -> bool:
    base = fontname.split("+")[-1]
    return base.startswith(PRINT_FONTS)


@dataclass
class Char:
    text: str
    x0: float
    x1: float
    y: float          # ligne de base (redressée, y vers le bas)
    size: float
    hand: bool
    bold: bool


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    y: float          # ligne de base
    size: float
    hand: bool
    bold: bool = False
    chars: list[Char] = field(default_factory=list, repr=False)

    @property
    def top(self) -> float:
        return self.y - self.size * 0.75

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return self.y - self.size * 0.35


@dataclass
class Box:
    """Rectangle redressé (cases à cocher, cellules)."""
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.bottom - self.top

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Stroke:
    """Tracé vectoriel (courbe ou segment), redressé, en boîte englobante."""
    x0: float
    top: float
    x1: float
    bottom: float
    pts: list[tuple[float, float]]
    color: object = None
    width: float = 0.0


@dataclass
class PageLayout:
    angle_deg: float
    width: float
    height: float
    words: list[Word]
    boxes: list[Box]
    strokes: list[Stroke]

    @property
    def print_words(self) -> list[Word]:
        return [w for w in self.words if not w.hand]

    @property
    def hand_words(self) -> list[Word]:
        return [w for w in self.words if w.hand]


# ---------------------------------------------------------------- géométrie
def _dominant_angle(chars: list[dict]) -> float:
    cnt = Counter()
    for c in chars:
        if not is_print_font(c["fontname"]):
            continue
        a, b = c["matrix"][0], c["matrix"][1]
        cnt[round(math.atan2(b, a), 5)] += 1
    if not cnt:
        return 0.0
    return cnt.most_common(1)[0][0]


class _Rot:
    """Rotation de -angle autour du centre de page, coordonnées PDF -> redressées (y bas)."""

    def __init__(self, angle: float, w: float, h: float):
        self.c, self.s = math.cos(-angle), math.sin(-angle)
        self.cx, self.cy = w / 2, h / 2
        self.h = h

    def pdf(self, x: float, y: float) -> tuple[float, float]:
        """(x, y) en repère PDF (y haut) -> (x', y') redressé, y vers le bas."""
        dx, dy = x - self.cx, y - self.cy
        rx = self.c * dx - self.s * dy + self.cx
        ry = self.s * dx + self.c * dy + self.cy
        return rx, self.h - ry

    def top(self, x: float, top: float) -> tuple[float, float]:
        """(x, top) en repère pdfplumber (y bas) -> redressé."""
        return self.pdf(x, self.h - top)


def page_layout(page) -> PageLayout:
    chars = page.chars
    angle = _dominant_angle(chars)
    rot = _Rot(angle, float(page.width), float(page.height))

    out: list[Char] = []
    for c in chars:
        a, b, _, _, e, f = c["matrix"]
        x, y = rot.pdf(e, f)
        size = float(c.get("size") or math.hypot(a, b))
        adv = (c["x1"] - c["x0"]) if abs(math.atan2(b, a)) < 0.2 else size * 0.5
        out.append(Char(c["text"], x, x + adv, y, size,
                        hand=not is_print_font(c["fontname"]),
                        bold="Bold" in c["fontname"]))

    words = _group_words(out)

    boxes, strokes = [], []
    for r in page.rects:
        pts = [rot.top(r["x0"], r["top"]), rot.top(r["x1"], r["top"]),
               rot.top(r["x0"], r["bottom"]), rot.top(r["x1"], r["bottom"])]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        boxes.append(Box(min(xs), min(ys), max(xs), max(ys)))
    for obj in list(page.curves) + list(page.lines):
        raw = obj.get("pts") or [(obj["x0"], obj["top"]), (obj["x1"], obj["bottom"])]
        pts = [rot.top(px, py) for px, py in raw]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        strokes.append(Stroke(min(xs), min(ys), max(xs), max(ys), pts,
                              obj.get("stroking_color"), float(obj.get("linewidth") or 0)))
    return PageLayout(math.degrees(angle), float(page.width), float(page.height), words, boxes, strokes)


# ---------------------------------------------------------------- regroupement
def _group_words(chars: list[Char]) -> list[Word]:
    """Regroupe en mots : même type (imprimé/manuscrit), même ligne de base, écart < seuil."""
    words: list[Word] = []
    for hand in (False, True):
        pool = sorted((c for c in chars if c.hand == hand), key=lambda c: (round(c.y), c.x0))
        lines: list[list[Char]] = []
        for c in sorted(pool, key=lambda c: c.y):
            tol = c.size * (0.45 if hand else 0.3)
            for ln in lines:
                if abs(ln[-1].y - c.y) <= tol and abs(sum(k.y for k in ln) / len(ln) - c.y) <= tol:
                    ln.append(c)
                    break
            else:
                lines.append([c])
        for ln in lines:
            ln.sort(key=lambda c: c.x0)
            cur: list[Char] = []
            for c in ln:
                if cur:
                    gap = c.x0 - cur[-1].x1
                    space_gap = cur[-1].text == " " or c.text == " "
                    if gap > c.size * (0.6 if hand else 0.4) or (space_gap and not hand and gap > c.size * 0.25):
                        words.append(make_word(cur))
                        cur = []
                cur.append(c)
            if cur:
                words.append(make_word(cur))
    return [w for w in words if w.text.strip()]


def make_word(cs: list[Char]) -> Word:
    text = "".join(c.text for c in cs).strip()
    ys = sorted(c.y for c in cs)
    return Word(text, min(c.x0 for c in cs), max(c.x1 for c in cs), ys[len(ys) // 2],
                max(c.size for c in cs), cs[0].hand, all(c.bold for c in cs if c.text.strip()), cs)


def merge_line(words: list[Word], gap: float) -> list[Word]:
    """Fusionne des mots déjà sur une même ligne si l'écart horizontal < gap."""
    out: list[Word] = []
    for w in sorted(words, key=lambda w: w.x0):
        if out and w.x0 - out[-1].x1 <= gap:
            p = out[-1]
            out[-1] = Word(p.text + " " + w.text, p.x0, max(p.x1, w.x1), p.y, max(p.size, w.size),
                           p.hand, p.bold and w.bold, p.chars + w.chars)
        else:
            out.append(w)
    return out


def text_lines(words: list[Word], tol: float = 3.0) -> list[list[Word]]:
    """Regroupe des mots en lignes (par ligne de base), triées de haut en bas."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.y):
        if lines and abs(lines[-1][0].y - w.y) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w.x0)
    return lines
