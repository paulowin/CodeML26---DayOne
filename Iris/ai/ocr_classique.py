"""Mode « OCR classique » (étape 3d) : OCR local de la page entière (PaddleOCR ou EasyOCR),
sans modèle génératif pour la lecture.

1. OCR -> lignes (texte, boîte, confiance) ;
2. les LIBELLÉS IMPRIMÉS sont reconnus parmi ces lignes (correspondance approchée avec les
   libellés du template ; « DDR : 26/04/2025 » est coupé en libellé + valeur) ;
3. rattachement géométrique RÉUTILISÉ de scripts/build_ground_truth.py (`PageGT` : libellé
   le plus proche à gauche / au-dessus, ligne + colonne pour les tableaux), dans le repère
   du spécimen (points PDF, 595 pt de large) ;
4. cases à cocher : carrés détectés par OpenCV + taux d'encre à l'intérieur (pas d'IA) ;
5. confiance / statuts : mêmes règles qu'en 3b (`ai.confidence`), 2e avis Ollama
   UNIQUEMENT sur les champs critiques (et douteux).

PaddleOCR n'existe pas pour Python 3.14 : il tourne dans `.venv-ocr` (Python 3.13), appelé
en sous-processus (`ai/_paddle_worker.py`), l'image passant par stdin (jamais sur disque).
"""
from __future__ import annotations

import difflib
import io
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ai import confidence as C
from ai.classify import UNKNOWN, classify_text
from ai.extract import (FieldState, PageResult, Reading, _cell_etat, _finalize, _second_opinion,
                        drop_impossible_readings, merge)
from ai.preprocess import load_image, prepare
from app.templates import get_template
from app.templates.base import norm_label
from eval.pdf_layout import Char, PageLayout, Stroke, Word

log = logging.getLogger("iris.ocr")
T = get_template()
ROOT = Path(__file__).resolve().parent.parent
PT_WIDTH = 595.2756                 # largeur d'une page du spécimen en points PDF
INK_MARKED = 0.10                   # taux d'encre au-delà duquel une case est cochée


@dataclass
class Token:
    text: str
    box: tuple[float, float, float, float]       # x0, y0, x1, y1 en pixels
    conf: float


# ------------------------------------------------------------------ moteurs OCR
_easy = None


def ocr_easyocr(img: Image.Image) -> list[Token]:
    global _easy
    import easyocr
    if _easy is None:
        _easy = easyocr.Reader(["fr", "en"], gpu=False, verbose=False)
    out = []
    for box, text, conf in _easy.readtext(np.asarray(img), paragraph=False):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append(Token(str(text), (min(xs), min(ys), max(xs), max(ys)), float(conf)))
    return out


def ocr_paddle(img: Image.Image) -> list[Token]:
    py = ROOT / ".venv-ocr" / "Scripts" / "python.exe"
    if not py.exists():
        py = ROOT / ".venv-ocr" / "bin" / "python"
    if not py.exists():
        raise RuntimeError("PaddleOCR absent : créer .venv-ocr (Python 3.13) avec paddlepaddle + paddleocr")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
    r = subprocess.run([str(py), str(ROOT / "ai" / "_paddle_worker.py")], input=buf.getvalue(),
                       capture_output=True, timeout=900, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"PaddleOCR a échoué : {r.stderr.decode('utf-8', 'replace')[-600:]}")
    data = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    return [Token(d["text"], tuple(d["box"]), float(d["conf"])) for d in data]


ENGINES = {"easyocr": ocr_easyocr, "paddle": ocr_paddle}


# ------------------------------------------------------------------ libellés imprimés
def page_labels(page_type: str) -> list[str]:
    """Tous les textes imprimés utiles au rattachement (libellés, en-têtes, options, contextes)."""
    labels = set()
    for sec in T.page_type(page_type).sections:
        s = T.section(sec)
        for f in s.all_fields():
            labels.update(f.labels)
            if f.context:
                labels.add(f.context)
            if f.is_checkbox:
                labels.update(lab for c in f.choices for lab in c.labels)
        for tb in s.tables:
            labels.update(l for _, l in tb.cols)
            labels.update(l for als in tb.col_aliases.values() for l in als)
    return sorted((l for l in labels if norm_label(l)), key=lambda l: -len(norm_label(l)))


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def split_label(text: str, labels: list[str]) -> tuple[str | None, str]:
    """-> (libellé reconnu ou None, reste = valeur manuscrite éventuelle)."""
    n = norm_label(text)
    if not n:
        return None, text
    for lab in labels:                                   # du plus long au plus court
        nl = norm_label(lab)
        if len(nl) <= 3:
            if n == nl:
                return lab, ""
            continue
        if n == nl or _ratio(n, nl) >= 0.86:
            return lab, ""
        head = n[:len(nl)]
        if len(n) > len(nl) + 1 and (head == nl or _ratio(head, nl) >= 0.88):
            # coupe dans le texte d'origine : après le « : » s'il y en a un, sinon à la longueur du libellé
            if ":" in text[:len(lab) + 4]:
                rest = text.split(":", 1)[1]
            else:
                rest = text[len(lab):]
            return lab, rest.strip(" :.")
    return None, text


# ------------------------------------------------------------------ mise en page « spécimen »
def _word(text: str, x0: float, x1: float, y_top: float, y_bot: float, hand: bool) -> Word:
    size = max(4.0, (y_bot - y_top) * 0.85)
    y = y_bot - (y_bot - y_top) * 0.2
    chars, n = [], max(1, len(text))
    for i, ch in enumerate(text):                         # caractères répartis sur la boîte (découpe en colonnes)
        cx0 = x0 + (x1 - x0) * i / n
        chars.append(Char(ch, cx0, cx0 + (x1 - x0) / n * 0.9, y, size, hand, False))
    return Word(text, x0, x1, y, size, hand, False, chars)


def build_layout(tokens: list[Token], img_w: int, img_h: int, page_type: str) -> tuple[PageLayout, dict]:
    """Tokens OCR (pixels) -> PageLayout en points PDF ; libellés = imprimé, le reste = manuscrit."""
    s = PT_WIDTH / img_w
    labels = page_labels(page_type)
    words, conf_of = [], {}
    for tok in tokens:
        x0, y0, x1, y1 = (v * s for v in tok.box)
        lab, rest = split_label(tok.text, labels)
        if lab is not None:
            if rest:
                frac = min(0.9, max(0.1, len(lab) / max(1, len(tok.text))))
                xl = x0 + (x1 - x0) * frac
                words.append(_word(lab, x0, xl, y0, y1, hand=False))
                parts = rest.split()
                xs = np.linspace(xl + 2, x1, len(parts) + 1)
                for p, a, b in zip(parts, xs, xs[1:]):
                    w = _word(p, a, b - 1, y0, y1, hand=True)
                    words.append(w)
                    conf_of[id(w)] = tok.conf
            else:
                words.append(_word(lab, x0, x1, y0, y1, hand=False))
        else:
            parts = tok.text.split()
            xs = np.linspace(x0, x1, len(parts) + 1) if parts else []
            for p, a, b in zip(parts, xs, xs[1:]):
                w = _word(p, a, b - 1, y0, y1, hand=True)
                words.append(w)
                conf_of[id(w)] = tok.conf
    return PageLayout(0.0, PT_WIDTH, img_h * s, words, [], []), conf_of


# ------------------------------------------------------------------ cases à cocher (vision classique)
def detect_checkboxes(img: Image.Image) -> list[tuple[Stroke, float]]:
    """Carrés de ~8 pt -> (case en points PDF, taux d'encre à l'intérieur)."""
    g = np.asarray(img.convert("L"))
    h, w = g.shape
    s = PT_WIDTH / w
    lo, hi = 5.0 / s, 12.0 / s                        # côté d'une case en pixels
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if not (lo <= cw <= hi and lo <= ch <= hi and 0.75 <= cw / ch <= 1.33):
            continue
        approx = cv2.approxPolyDP(c, 0.12 * cv2.arcLength(c, True), True)
        if len(approx) != 4:
            continue
        if any(abs(x - fx) < cw * 0.5 and abs(y - fy) < ch * 0.5 for fx, fy, _, _, _ in found):
            continue                                    # contours intérieur / extérieur du même carré
        mx, my = int(cw * 0.22), int(ch * 0.22)
        inner = bw[y + my:y + ch - my, x + mx:x + cw - mx]
        ink = float(inner.mean() / 255) if inner.size else 0.0
        found.append((x, y, cw, ch, ink))
    return [(Stroke(x * s, y * s, (x + cw) * s, (y + ch) * s, []), ink) for x, y, cw, ch, ink in found]


# ------------------------------------------------------------------ pipeline
def _band_of(y_rel: float, bands) -> int:
    inside = [b for b in bands if b.y0 <= y_rel <= b.y1]
    return min(inside, key=lambda b: abs((b.y0 + b.y1) / 2 - y_rel)).index if inside else 0


def read_page_ocr(img_bytes: bytes, engine: str, page_type: str | None = None):
    """OCR + rattachement -> (type de page, lectures par champ, page préparée, tokens)."""
    from scripts.build_ground_truth import PageGT        # géométrie de la vérité terrain (3a)
    img = load_image(img_bytes)
    prep = prepare(img_bytes)
    tokens = ENGINES[engine](img)
    if page_type is None:
        page_type = classify_text(" ".join(t.text for t in tokens)) or UNKNOWN
    states: dict[str, FieldState] = {}
    if page_type == UNKNOWN:
        return page_type, states, prep, tokens
    layout, conf_of = build_layout(tokens, img.size[0], img.size[1], page_type)
    gt = PageGT(layout, page_type)
    grids = gt.table_grids()
    assigned, _ = gt.assign_hand(grids)
    for key, words in assigned.items():
        f = gt.fields[key]
        if f.identifiant or key not in T.stored_fields:
            continue                                     # identifiants : jamais extraits
        words.sort(key=lambda w: (round(w.y / 4), w.x0))
        raw = " ".join(w.text for w in words)
        conf = float(np.mean([conf_of.get(id(w), 0.5) for w in words]))
        band = _band_of(np.mean([w.cy for w in words]) / layout.height, prep.bands)
        st = states.setdefault(key, FieldState(f))
        st.readings.append(Reading(key, raw, _cell_etat(raw), conf, band))
    # cases : taux d'encre (aucune IA)
    for box, ink in detect_checkboxes(img):
        cy = (box.top + box.bottom) / 2
        label = gt._box_label(box, cy)
        hit = gt._box_field(label, cy) if label else None
        if not hit:
            continue
        key, f, code = hit
        if key not in T.stored_fields:
            continue
        st = states.setdefault(key, FieldState(f))
        st.flags.append("lecture_cv")
        marked = ink >= INK_MARKED
        conf = min(0.95, 0.55 + abs(ink - INK_MARKED) * 3)
        codes = ["coche"] if (f.type == "bool" and marked) else ([code] if marked and code else [])
        band = _band_of(cy / layout.height, prep.bands)
        prev = next((r for r in st.readings if r.source == "main"), None)
        if prev is None:
            st.readings.append(Reading(key, codes, "LISIBLE", conf, band))
        else:                                            # plusieurs cases du même groupe : union
            prev.raw = sorted(set(prev.raw or []) | set(codes))
            prev.conf = min(prev.conf or 1, conf)
    return page_type, states, prep, tokens


def extract_pages_ocr(images: list[bytes], *, engine: str = "paddle", client=None, verify_model: str | None = None,
                      seuil: float | None = None, use_cache: bool = False,
                      page_types: list[str | None] | None = None) -> list[PageResult]:
    from app.config import get_settings
    s = get_settings()
    seuil = s.ai_seuil_connu if seuil is None else seuil
    pages = []
    for i, data in enumerate(images):
        t0 = time.monotonic()
        res = PageResult(i, UNKNOWN, models={"main": f"ocr:{engine}", "verify": verify_model or None})
        hint = page_types[i] if page_types and i < len(page_types) else None
        try:
            page_type, states, prep, tokens = read_page_ocr(data, engine, hint)
        except Exception as e:  # noqa: BLE001  (moteur absent, image illisible...)
            log.exception("OCR %s impossible", engine)
            res.error, res.duration_s = f"OCR {engine} : {e}", time.monotonic() - t0
            pages.append((res, {}))
            continue
        res.page_type, res.classification = page_type, "impose" if hint else "mots_cles"
        res.quality, res.deskew_deg = prep.quality, prep.deskew_deg
        res.band_ranges = [(b.y0, b.y1) for b in prep.bands]
        drop_impossible_readings(states, len(prep.bands))
        for st in states.values():
            merge(st)
        if verify_model and client is not None:          # 2e avis Ollama : champs critiques/douteux seulement
            _second_opinion(client, page_type, prep.bands, verify_model, use_cache, states, seuil)
        res.duration_s = time.monotonic() - t0
        pages.append((res, states))
    _finalize(pages, seuil)
    return [r for r, _ in pages]


if __name__ == "__main__":                                # python -m ai.ocr_classique img [--engine easyocr]
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--engine", default="paddle", choices=list(ENGINES))
    a = ap.parse_args()
    t0 = time.monotonic()
    toks = ENGINES[a.engine](load_image(a.image.read_bytes()))
    print(f"{len(toks)} lignes en {time.monotonic() - t0:.1f} s")
    for tk in toks[:60]:
        print(f"{tk.conf:.2f} {[round(v) for v in tk.box]} {tk.text}")
    sys.exit(0)
