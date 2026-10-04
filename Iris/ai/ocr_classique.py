"""Mode « OCR classique » (étape 3d) : OCR local de la page entière (PaddleOCR ou EasyOCR),
sans modèle génératif pour la lecture.

1. OCR -> lignes (texte, boîte, confiance) ;
2. les LIBELLÉS IMPRIMÉS sont reconnus parmi ces lignes (correspondance approchée avec les
   libellés du template ; « DDR : 26/04/2025 » est coupé en libellé + valeur) ;
3. rattachement géométrique RÉUTILISÉ de scripts/build_ground_truth.py (`PageGT` : libellé
   le plus proche à gauche / au-dessus, ligne + colonne pour les tableaux), dans le repère
   du spécimen (points PDF, 595 pt de large) ;
4. cases à cocher : ai/checkboxes.py (homographie sur les libellés lus + taux d'encre, pas d'IA) ;
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


def _best_label(n: str, labels: list[str], min_ratio: float) -> str | None:
    """Libellé le plus proche (exact d'abord, sinon meilleur score) : « Date de l'accouchement »
    ne doit pas être pris pour « Mode de l'accouchement » parce qu'il arrive premier dans la liste."""
    best, score = None, 0.0
    for lab in labels:
        nl = norm_label(lab)
        if n == nl:
            return lab
        if len(nl) > 3:
            r = _ratio(n, nl)
            if r >= min_ratio and r > score:
                best, score = lab, r
    return best


def split_label(text: str, labels: list[str]) -> tuple[str | None, str]:
    """-> (libellé reconnu ou None, reste = valeur manuscrite éventuelle)."""
    text = text.replace("：", ":").replace("□", " ").strip()     # deux-points pleine largeur (PaddleOCR)
    n = norm_label(text)
    if not n:
        return None, text
    if ":" in text:                                      # « DDR:26/04/2025 » : libellé avant le deux-points
        head, rest = text.split(":", 1)
        lab = _best_label(norm_label(head), labels, 0.86)
        if lab is not None:
            return lab, rest.strip(" :.")
    lab = _best_label(n, labels, 0.86)
    if lab is not None:
        return lab, ""
    best, score, rest_text = None, 0.0, ""
    for lab in labels:                                   # libellé en tête, valeur derrière
        nl = norm_label(lab)
        if len(nl) <= 3 or len(n) <= len(nl) + 1:
            continue
        r = 1.0 if n[:len(nl)] == nl else _ratio(n[:len(nl)], nl)
        if r >= 0.88 and r > score:
            best, score = lab, r
            rest_text = text[len(lab):]
    if best is not None:
        return best, rest_text.strip(" :.")
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
    """Tokens OCR (pixels) -> PageLayout en points PDF ; libellés = imprimé, le reste = manuscrit.
    `conf_of[id(mot)]` = confiance OCR ; `ORIG[id(mot)]` = texte OCR d'origine (en-têtes de tableaux)."""
    s = PT_WIDTH / img_w
    labels = page_labels(page_type)
    words, conf_of = [], {}
    ORIG.clear()
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
                w = _word(lab, x0, x1, y0, y1, hand=False)
                ORIG[id(w)] = tok.text
                words.append(w)
        else:
            parts = tok.text.split()
            xs = np.linspace(x0, x1, len(parts) + 1) if parts else []
            for p, a, b in zip(parts, xs, xs[1:]):
                w = _word(p, a, b - 1, y0, y1, hand=True)
                words.append(w)
                conf_of[id(w)] = tok.conf
    for w in words:                                       # en-têtes isolés (« Visite », « 7ème mois »...)
        ORIG.setdefault(id(w), w.text)
    return PageLayout(0.0, PT_WIDTH, img_h * s, words, [], []), conf_of


ORIG: dict[int, str] = {}


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def header_match(txt: str, cand: str, lenient: bool = False) -> bool:
    """En-tête de colonne lu par l'OCR ~ attendu. Si l'attendu porte un chiffre (« Visite 1 »,
    « 7ème mois »), le chiffre doit être lu : sinon « Visites » (de « Prestations / Visites »)
    passait pour « Visite 1 » et décalait tout le tableau d'une colonne."""
    if txt == cand:
        return True
    dc = _digits(cand)
    if dc:
        if _digits(txt) == dc:
            return _ratio(txt, cand) >= 0.7
        if _digits(txt) or not lenient:
            return False                                  # un AUTRE chiffre : autre colonne
        # 2e passe seulement (la 1re n'a pas trouvé le tableau) — chiffre perdu (photo WhatsApp
        # compressée : « Visite », « Bème mois ») : on accepte le
        # libellé sans son chiffre — l'ordre gauche -> droite fixe la colonne. Le pluriel
        # « Visites » (en-tête « Prestations / Visites ») reste refusé.
        core = " ".join("".join(ch for ch in cand if not ch.isdigit()).split())
        t = " ".join(txt.split())
        return t != core + "s" and (t == core or (len(core) > 5 and _ratio(t, core) >= 0.85))
    return len(cand) > 3 and _ratio(txt, cand) >= 0.75


def ocr_page_gt(layout: PageLayout, page_type: str):
    """`PageGT` (3a) avec une détection d'en-têtes de tableaux TOLÉRANTE aux erreurs d'OCR :
    correspondance approchée dans l'ordre, colonnes manquantes interpolées entre leurs voisines."""
    from scripts.build_ground_truth import PageGT, ROW_TOL
    from eval.pdf_layout import text_lines

    class OcrPageGT(PageGT):
        def _grid(self, sec, t):
            return self._grid_pass(sec, t, False) or self._grid_pass(sec, t, True)

        def _grid_pass(self, sec, t, lenient):
            best = None
            for line in text_lines(self.L.words, 4.0):
                found: dict[int, float] = {}
                i = 0
                for w in line:
                    txt = norm_label(ORIG.get(id(w), w.text))
                    for j in range(i, len(t.cols)):
                        code, label = t.cols[j]
                        cands = [norm_label(l) for l in (label, *t.col_aliases.get(code, ()))]
                        if any(header_match(txt, c, lenient) for c in cands):
                            found[j] = w.x0
                            i = j + 1
                            break
                if len(found) >= max(2, int(0.6 * len(t.cols))) and (best is None or len(found) > len(best[1])):
                    best = (line, found)
            if best is None:
                return None
            line, found = best
            idx = sorted(found)
            xs = []
            for j in range(len(t.cols)):                  # interpolation / extrapolation linéaire
                if j in found:
                    xs.append(found[j])
                    continue
                lo = max((k for k in idx if k < j), default=None)
                hi = min((k for k in idx if k > j), default=None)
                if lo is not None and hi is not None:
                    xs.append(found[lo] + (found[hi] - found[lo]) * (j - lo) / (hi - lo))
                else:
                    a, b = (idx[0], idx[1]) if hi is not None else (idx[-2], idx[-1])
                    step = (found[b] - found[a]) / (b - a)
                    xs.append(found[a] + step * (j - a))
            cols = [{"code": code, "x0": x} for (code, _), x in zip(t.cols, xs)]
            y = line[0].y
            rows = []
            for r in t.rows:
                for h in self.find_print(r.labels):
                    if h.y > y and h.x0 < cols[0]["x0"] - 5:
                        rows.append({"code": r.key, "y": h.y})
            if t.rows:
                bottom = max((r["y"] for r in rows), default=y) + ROW_TOL
            else:
                below = [w for w in self.prints if w.y > y + 4 and w.x1 > cols[0]["x0"]]
                bottom = min((w.y for w in below), default=self.L.height) - 4
            return {"section": sec, "table": t, "y": y, "cols": cols, "rows": rows,
                    "left": cols[0]["x0"] - 8, "bottom": bottom}

    return OcrPageGT(layout, page_type)


# ------------------------------------------------------------------ pipeline
# réponses fréquentes du carnet : une faute de frappe d'OCR proche est corrigée, avec une confiance
# plafonnée (A_REVISER) — mesuré : « Nbrmaux », « Ou; » sortaient en CONNU (erreurs silencieuses)
from app.templates.vocabulaire import VOCABULAIRE_TEXTE as VOCABULARY  # noqa: E402


def in_vocabulary(raw: str) -> bool:
    import re
    n = re.sub(r"[^a-z0-9 ]", "", norm_label(raw)).strip()
    return any(re.sub(r"[^a-z0-9 ]", "", norm_label(v)).strip() == n for v in VOCABULARY)


def snap_vocabulary(raw: str) -> str:
    import re
    n = re.sub(r"[^a-z0-9 ]", "", norm_label(raw)).strip()           # « Ou; » -> « ou »
    if not n or any(norm_label(v) == n for v in VOCABULARY) or any(ch.isdigit() for ch in raw):
        return raw
    best, score = raw, 0.0
    for v in VOCABULARY:
        r = _ratio(n, norm_label(v))
        if r > score:
            best, score = v, r
    # seuil bas assumé : un mot corrigé a sa confiance plafonnée (A_REVISER), une mauvaise
    # correction coûte une question, jamais une erreur silencieuse (« Qui », « ouj », « Nprlaux »)
    return best if score >= 0.55 else raw


def _band_of(y_rel: float, bands) -> int:
    inside = [b for b in bands if b.y0 <= y_rel <= b.y1]
    return min(inside, key=lambda b: abs((b.y0 + b.y1) / 2 - y_rel)).index if inside else 0


# Photo WhatsApp compressée : une ligne d'écriture fait ~16 px (contre ~24 px sur un scan à 200 dpi)
LOW_RES_LINE_PX = 20
ZOOM_TYPES = ("float", "int", "bp")                       # poids, HU, BCF, TA, Hb...


def _zoom_read(img: Image.Image, words, px_per_pt: float) -> str | None:
    """Relit une cellule agrandie x3 (interpolation cubique + netteté), lecture contrainte aux chiffres."""
    import cv2
    x0 = min(w.x0 for w in words) * px_per_pt - 4
    x1 = max(w.x1 for w in words) * px_per_pt + 4
    y0 = min(w.top for w in words) * px_per_pt - 4
    y1 = max(w.y for w in words) * px_per_pt + 6
    a = np.asarray(img.convert("RGB"))[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)]
    if a.size == 0 or _easy is None:
        return None
    a = cv2.resize(a, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    a = cv2.filter2D(a, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))
    try:
        txt = _easy.readtext(a, detail=0, paragraph=True, allowlist="0123456789/.,")
    except Exception:  # noqa: BLE001
        return None
    return " ".join(txt).strip() or None


def read_page_ocr(img_bytes: bytes, engine: str, page_type: str | None = None, debug_path=None):
    """OCR + rattachement -> (type de page, lectures par champ, page préparée, tokens)."""
    img = load_image(img_bytes)
    prep = prepare(img_bytes)
    tokens = ENGINES[engine](img)
    if page_type is None:
        page_type = classify_text(" ".join(t.text for t in tokens)) or UNKNOWN
    states: dict[str, FieldState] = {}
    if page_type == UNKNOWN:
        return page_type, states, prep, tokens
    if page_type == "vaccinations" and _easy is not None:      # carnet OMS : lecteur dédié (encre bleue)
        from ai.vaccination import read_vaccination_states
        states, _diag = read_vaccination_states(img, _easy, prep.bands, tokens)
        return page_type, states, prep, tokens
    if page_type == "vaccination_couverture":                   # identifiants directs : rien à extraire
        return page_type, states, prep, tokens
    layout, conf_of = build_layout(tokens, img.size[0], img.size[1], page_type)
    heights = sorted(t.box[3] - t.box[1] for t in tokens)
    low_res = engine == "easyocr" and bool(heights) and heights[len(heights) // 2] < LOW_RES_LINE_PX
    gt = ocr_page_gt(layout, page_type)                  # géométrie de la vérité terrain (3a)
    grids = gt.table_grids()
    assigned, _ = gt.assign_hand(grids)
    for key, words in assigned.items():
        f = gt.fields[key]
        if f.identifiant or key not in T.stored_fields:
            continue                                     # identifiants : jamais extraits
        words.sort(key=lambda w: (round(w.y / 4), w.x0))
        raw = " ".join(w.text for w in words)
        conf = float(np.mean([conf_of.get(id(w), 0.5) for w in words]))
        st = states.setdefault(key, FieldState(f))
        st.flags.append("lecture_ocr")
        if f.type in ("str", "enum") and not f.vocabulaire:
            fixed = snap_vocabulary(raw)
            if fixed != raw:                     # « Nbrmaux » -> « Normaux » : corrigé MAIS à vérifier
                raw, conf = fixed, min(conf, 0.6)
            elif f.type == "str" and not in_vocabulary(raw):
                # texte libre inconnu (« Chuffeur ») : CONNU seulement si le 2e avis lit la même chose
                st.flags.append("hors_vocabulaire")
        band = _band_of(np.mean([w.cy for w in words]) / layout.height, prep.bands)
        st = states.setdefault(key, FieldState(f))
        st.readings.append(Reading(key, raw, _cell_etat(raw), conf, band))
        if low_res and f.type in ZOOM_TYPES and f.table:
            # photo compressée : relecture de la cellule agrandie x3, chiffres seulement. Un
            # désaccord (« 74 » / « 74,8 ») = 2 lectures différentes -> à vérifier, jamais CONNU
            zoom = _zoom_read(img, words, img.size[0] / PT_WIDTH)
            if zoom and _digits(zoom) != _digits(raw):
                st.readings.append(Reading(key, zoom, _cell_etat(zoom), conf, band))
    # cases : vision classique (ai/checkboxes.py), avec les libellés déjà lus par l'OCR comme ancres
    from ai.checkboxes import read_checkboxes
    from ai.extract import add_checkbox_readings
    for k in [k for k, st in states.items() if st.f.is_checkbox]:
        del states[k]                                    # un mot OCR ne vaut pas une case cochée
    boxes, _method = read_checkboxes(img, page_type, tokens=tokens, debug_path=debug_path)
    add_checkbox_readings(states, boxes, prep.bands, img.size[1])
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
            _second_opinion(client, page_type, prep.bands, verify_model, use_cache, states, seuil,
                            critical_only=True)
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
