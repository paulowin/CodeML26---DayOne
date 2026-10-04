"""Cases à cocher par VISION CLASSIQUE (OpenCV), sans IA générative.

Constat (3b) : le VLM « coche » presque toutes les options visibles (précision ~27 %).
Ici :
1. Localisation : positions des cases du template (app/templates/carnet_maroc_cases.json,
   extraites du PDF spécimen avec la géométrie de scripts/build_ground_truth.py), projetées
   sur la photo par une HOMOGRAPHIE calculée sur les libellés imprimés lus par l'OCR
   (ancres). Si le recalage échoue : détection des petits carrés par contours
   (approxPolyDP 4 côtés, ratio 0.8–1.2, côté 15–45 px) + libellé OCR le plus proche.
2. Mesure : zone = case élargie de 30 % ; encre = pixels bleus (B > R + 20, pas trop clairs :
   stylo bleu sur papier rose) ; repli encre noire : seuillage adaptatif à l'INTÉRIEUR de la
   case seulement (le cadre noir imprimé ne compte pas).
3. Décision : > AI_CASE_COCHEE (15 %) -> cochée ; < AI_CASE_VIDE (4 %) -> vide ; sinon
   incertaine (A_REVISER). Confiance selon l'écart au seuil.
Image de debug : cases encadrées vert (cochée) / rouge (vide) / orange (incertaine).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.templates.base import norm_label

log = logging.getLogger("iris.cases")
LAYOUT_PATH = Path(__file__).resolve().parent.parent / "app" / "templates" / "carnet_maroc_cases.json"
ENLARGE = 0.30
# encre sombre : l'excès au-dessus d'une case vide est plus faible que l'encre bleue (le cadre noir
# occupe déjà la zone) ; mesuré : coche noire >= 0.068, case vide <= 0.04 -> remis à l'échelle des seuils
DARK_SCALE = 2.5
MIN_ANCHORS = 6


@dataclass
class BoxResult:
    key: str
    code: str | None
    box_px: tuple[int, int, int, int]
    ratio: float
    decision: str               # "cochee" | "vide" | "incertaine"
    conf: float


@lru_cache(maxsize=1)
def layout() -> dict:
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


def thresholds() -> tuple[float, float]:
    from app.config import get_settings
    s = get_settings()
    return s.ai_case_cochee, s.ai_case_vide


# ------------------------------------------------------------------ mesure
def blue_ink(rgb: np.ndarray) -> np.ndarray:
    r, g, b = (rgb[:, :, i].astype(int) for i in range(3))
    return (b > r + 20) & (b > g) & ((r + g + b) / 3 < 215)


def measure(rgb: np.ndarray, gray_dark: np.ndarray, box: tuple[float, float, float, float]):
    """(encre bleue [zone], encre sombre [zone], encre sombre [intérieur], zone) — zone = case élargie
    de 30 %. L'encre sombre inclut le cadre imprimé : on lui retire ensuite le niveau d'une case VIDE
    (médiane de la page, cf. read_checkboxes)."""
    h, w = gray_dark.shape
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    ex0, ey0 = int(max(0, x0 - bw * ENLARGE / 2)), int(max(0, y0 - bh * ENLARGE / 2))
    ex1, ey1 = int(min(w, x1 + bw * ENLARGE / 2)), int(min(h, y1 + bh * ENLARGE / 2))
    if ex1 <= ex0 or ey1 <= ey0:
        return 0.0, 0.0, 0.0, (ex0, ey0, ex1, ey1)
    zone = (slice(ey0, ey1), slice(ex0, ex1))
    blue = float(blue_ink(rgb[zone]).mean())
    dark = float(gray_dark[zone].mean())
    ix0, iy0, ix1, iy1 = int(x0 + bw * 0.18), int(y0 + bh * 0.18), int(x1 - bw * 0.18), int(y1 - bh * 0.18)
    inner = float(gray_dark[iy0:iy1, ix0:ix1].mean()) if ix1 > ix0 and iy1 > iy0 else 0.0
    return blue, dark, inner, (ex0, ey0, ex1, ey1)


INNER_MARKED, INNER_EMPTY = 0.08, 0.04       # encre sombre à l'INTÉRIEUR de la case (cadre exclu)


def decide_combined(blue: float, dark_ex: float, inner_ex: float) -> tuple[float, str, float]:
    """Décision prudente (objectif : zéro erreur silencieuse) :
    - encre bleue nette -> cochée ;
    - encre sombre : cochée seulement si la zone ET l'intérieur l'indiquent ; vide seulement si
      les deux sont bas ; un désaccord -> incertaine (à vérifier), jamais une affirmation."""
    hi, lo = thresholds()
    dark = DARK_SCALE * dark_ex
    ratio = max(blue, dark)
    if blue > hi:
        return ratio, *decide(blue)
    if dark > hi and inner_ex > INNER_MARKED:
        return ratio, *decide(dark)
    if blue < lo and dark < lo and inner_ex < INNER_EMPTY:
        return ratio, *decide(max(blue, dark))
    return ratio, "incertaine", 0.4


def decide(ratio: float) -> tuple[str, float]:
    hi, lo = thresholds()
    if ratio > hi:
        return "cochee", round(min(0.99, 0.82 + (ratio - hi) * 1.5), 3)
    if ratio < lo:
        return "vide", round(min(0.99, 0.82 + (lo - ratio) * 4), 3)
    return "incertaine", 0.4


# ------------------------------------------------------------------ recalage
def _anchor_points(page_type: str, tokens) -> tuple[np.ndarray, np.ndarray]:
    """Correspondances libellé du modèle (points PDF) <-> libellé lu par l'OCR (pixels)."""
    import difflib
    src, dst = [], []
    for a in layout()["pages"][page_type]["anchors"]:
        na = norm_label(a["text"])
        best, score = None, 0.0
        for t in tokens:
            nt = norm_label(t.text.replace("：", ":"))
            if not nt:
                continue
            if nt == na:
                r = 1.0
            elif nt.startswith(na + " "):
                r = 0.95                                     # libellé + valeur dans la même ligne OCR
            else:
                r = difflib.SequenceMatcher(None, nt, na).ratio()
            if r > score:
                best, score = t, r
        if best is None or score < 0.86:
            continue
        x0, y0, x1, y1 = best.box
        cy = (y0 + y1) / 2
        src.append((a["x0"], a["cy"]))
        dst.append((x0, cy))
        if score == 1.0:                                     # bord droit fiable seulement si ligne = libellé
            src.append((a["x1"], a["cy"]))
            dst.append((x1, cy))
    return np.float32(src), np.float32(dst)


def register(page_type: str, tokens, img_w: int, img_h: int) -> np.ndarray | None:
    src, dst = _anchor_points(page_type, tokens)
    if len(src) < MIN_ANCHORS:
        return None
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, max(8.0, img_w * 0.01))
    if H is None or mask is None or int(mask.sum()) < MIN_ANCHORS:
        return None
    pw, ph = layout()["page_size"]
    corners = cv2.perspectiveTransform(np.float32([[[0, 0]], [[pw, 0]], [[pw, ph]], [[0, ph]]]), H)[:, 0]
    area = cv2.contourArea(corners)
    if not (0.2 * img_w * img_h < area < 4 * img_w * img_h) or not cv2.isContourConvex(corners.astype(np.float32)):
        return None                                           # recalage aberrant
    return H


# ------------------------------------------------------------------ repli : contours
def _fallback(page_type: str, rgb: np.ndarray, tokens) -> list[tuple[dict, tuple]]:
    """Petits carrés (contours) + libellé OCR le plus proche -> case du modèle de même libellé."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).copy()
    g[blue_ink(rgb)] = 255
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))   # coins effacés par la croix
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    squares = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (15 <= w <= 45 and 15 <= h <= 45 and 0.8 <= w / h <= 1.2):
            continue
        if len(cv2.approxPolyDP(c, 0.1 * cv2.arcLength(c, True), True)) != 4:
            continue
        if any(abs(x - sx) < w / 2 and abs(y - sy) < h / 2 for sx, sy, _, _ in squares):
            continue
        squares.append((x, y, w, h))
    boxes = layout()["pages"][page_type]["boxes"]
    ph = layout()["page_size"][1]
    out = []
    for x, y, w, h in squares:
        cy = y + h / 2
        near = [t for t in tokens if abs((t.box[1] + t.box[3]) / 2 - cy) < h and
                (0 <= t.box[0] - (x + w) < 4 * w or 0 <= x - t.box[2] < 4 * w)]
        if not near:
            continue
        tok = min(near, key=lambda t: min(abs(t.box[0] - x - w), abs(x - t.box[2])))
        nt = norm_label(tok.text)
        cands = [b for b in boxes if norm_label(b["label"]) and nt.startswith(norm_label(b["label"]))]
        if not cands:
            continue
        rel = cy / rgb.shape[0]
        b = min(cands, key=lambda b: abs((b["box"][1] + b["box"][3]) / 2 / ph - rel))
        out.append((b, (x, y, x + w, y + h)))
    return out


# ------------------------------------------------------------------ entrée principale
def read_checkboxes(img: Image.Image, page_type: str, tokens=None, debug_path: Path | None = None,
                    engine: str = "easyocr") -> tuple[list[BoxResult], str]:
    """-> (résultats par case, méthode : 'homographie' | 'contours' | 'aucune')."""
    if page_type not in layout()["pages"]:
        return [], "aucune"
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    if tokens is None:
        from ai.ocr_classique import ENGINES
        tokens = ENGINES[engine](img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    dark = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 20)
    H = register(page_type, tokens, w, h)
    placed: list[tuple[dict, tuple]] = []
    if H is not None:
        method = "homographie"
        for b in layout()["pages"][page_type]["boxes"]:
            x0, y0, x1, y1 = b["box"]
            pts = cv2.perspectiveTransform(np.float32([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]]), H)[:, 0]
            placed.append((b, (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())))
    else:
        method = "contours"
        placed = _fallback(page_type, rgb, tokens)
    measures = [(b, *measure(rgb, dark, box)) for b, box in placed]
    base_in = float(np.median([m[3] for m in measures])) if measures else 0.0
    # encre sombre (stylo noir) : ce que le cadre imprimé n'explique pas. La plupart des cases d'une
    # page sont vides -> la médiane donne le niveau « cadre seul ». Mesuré : patiente 2 coche au stylo
    # presque noir, l'ancienne mesure (intérieur seul) ratait les coches qui débordent.
    base = float(np.median([m[2] for m in measures])) if measures else 0.0
    results = []
    for b, blue, dk, inner, zone in measures:
        ratio, decision, conf = decide_combined(blue, dk - base, inner - base_in)
        results.append(BoxResult(b["key"], b["code"], tuple(int(v) for v in zone), round(ratio, 4), decision, conf))
    if debug_path is not None:
        save_debug(img, results, debug_path)
    log.info("Cases %s : %d par %s", page_type, len(results), method)
    return results, method


def save_debug(img: Image.Image, results: list[BoxResult], path: Path) -> None:
    """Cases encadrées : vert = cochée, rouge = vide, orange = incertaine (+ taux d'encre)."""
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    colors = {"cochee": (0, 170, 0), "vide": (220, 0, 0), "incertaine": (255, 140, 0)}
    for r in results:
        d.rectangle(r.box_px, outline=colors[r.decision], width=3)
        d.text((r.box_px[2] + 3, r.box_px[1]), f"{r.ratio:.0%}", fill=colors[r.decision])
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def to_readings(results: list[BoxResult]) -> dict[str, tuple[list[str], float, bool]]:
    """Par champ : (codes cochés, confiance = la plus faible des options, au moins une incertaine ?)."""
    from app.templates import get_template
    T = get_template()
    out: dict[str, tuple[list[str], float, bool]] = {}
    for r in results:
        f = T.fields.get(r.key)
        if f is None:
            continue
        codes, conf, unsure = out.get(r.key, ([], 1.0, False))
        if r.decision == "cochee":
            codes = codes + (["coche"] if f.type == "bool" else [r.code])
        out[r.key] = (sorted(set(codes)), min(conf, r.conf), unsure or r.decision == "incertaine")
    return out
