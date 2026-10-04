"""Lecture de la page « AUTRES VACCINATIONS » (carnet OMS) — modèle app/templates/carnet_vaccination_oms.py.

1. On ne garde que l'encre BLEUE (B nettement > R et > G) : le fond gris imprimé (« INSTITUT
   D'HYGIÈNE PUBLIQUE ») et les tampons rouges / violets disparaissent.
2. Colonnes (date | vaccin | dose | signature = n° de lot) : lignes verticales du tableau
   (morphologie OpenCV), repli sur la position des en-têtes imprimés.
3. Entrées = LIGNES D'ÉCRITURE (une entrée peut couvrir 2 lignes imprimées) ; une ligne sans date
   ni vaccin complète l'entrée précédente.
4. OCR contraint par colonne (chiffres et « / » pour la date, « 0,5 cc » pour la dose,
   alphanumérique pour le lot) sur la cellule agrandie x3 ; vaccin rapproché du vocabulaire.
   Les deux lectures (page, cellule agrandie) qui diffèrent -> à vérifier.
5. Une date au CRAYON GRIS dans la zone d'une entrée -> « date de rappel ? », toujours à vérifier.
Toutes les cellules sont critiques : CONNU seulement si le 2e avis Ollama lit la même chose.
"""
from __future__ import annotations

import difflib
import re

import numpy as np
from PIL import Image

from app.templates import get_template
from app.templates.base import norm_label
from app.templates.carnet_vaccination_oms import MAX_ENTREES, VACCINS

COLS = ("date", "vaccin", "dose", "lot")
HEADERS = {"date": ("date",), "vaccin": ("vaccin", "vaccine", "vaccination"), "dose": ("dose",),
           "lot": ("signature", "medecin", "doctor")}
ALLOW = {"date": "0123456789/", "dose": "0123456789,.cCmMlL ",
         "lot": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-/"}
DATE_RE = re.compile(r"\b\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{2,4}\b")


def blue_mask(rgb: np.ndarray) -> np.ndarray:
    """Encre bleue / bleu-violet (teinte 200-280°, saturée) : mesuré sur de vraies photos sous lumière
    jaune, l'encre est sombre et peu « bleue » en RGB brut (35, 32, 47) ; tampons rouges / magenta exclus."""
    import cv2
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV)
    return (hsv[..., 0] >= 100) & (hsv[..., 0] <= 140) & (hsv[..., 1] > 50) & (hsv[..., 2] < 235)


def pencil_mask(rgb: np.ndarray) -> np.ndarray:
    """Gris de crayon : peu saturé, nettement plus sombre que le papier, pas noir d'imprimerie."""
    a = rgb.astype(int)
    sat = a.max(axis=2) - a.min(axis=2)
    lum = a.mean(axis=2)
    return (sat < 22) & (lum > 70) & (lum < 165)


def blue_only(rgb: np.ndarray) -> np.ndarray:
    """Encre bleue en NOIR sur fond blanc (traits épaissis), tout le reste effacé."""
    import cv2
    m = cv2.dilate(blue_mask(rgb).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    out = np.full_like(rgb, 255)
    out[m] = 0
    return out


def vertical_lines(rgb: np.ndarray) -> list[float]:
    """Abscisses des longues lignes verticales imprimées (bords des colonnes)."""
    import cv2
    gray = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY)
    # traits imprimés du tableau = les plus sombres (la trame « INSTITUT D'HYGIÈNE » est plus claire)
    bw = (gray < np.percentile(gray, 8)).astype(np.uint8) * 255
    h = rgb.shape[0]
    lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 15))))
    lines = cv2.dilate(lines, np.ones((1, 9), np.uint8))   # trait légèrement penché (photo)
    prof = lines.sum(axis=0) / 255
    xs = [x for x in range(1, len(prof) - 1) if prof[x] > h * 0.2 and prof[x] >= prof[x - 1] and prof[x] >= prof[x + 1]]
    merged: list[float] = []
    for x in xs:
        if merged and x - merged[-1] < 15:
            continue
        merged.append(float(x))
    return merged


def column_bounds(tokens, rgb: np.ndarray) -> tuple[dict[str, tuple[float, float]], float] | None:
    """{colonne: (x0, x1)} et ordonnée du bas des en-têtes ; None si les en-têtes sont introuvables."""
    found: dict[str, tuple[float, float, float]] = {}
    for t in tokens:
        n = norm_label(t.text)
        for col, keys in HEADERS.items():
            if col not in found and any(k in n for k in keys) and len(n) < 40:
                found[col] = (t.box[0], t.box[2], t.box[3])
    if "vaccin" not in found or "dose" not in found:
        return None
    width = rgb.shape[1]
    centers = {c: (v[0] + v[1]) / 2 for c, v in found.items()}
    # en-tête caché (tampon sur « Signature du médecin », « Date » mal lu) : extrapolé des voisins
    step = centers["dose"] - centers["vaccin"]
    centers.setdefault("date", centers["vaccin"] - 0.6 * step)
    centers.setdefault("lot", centers["dose"] + 0.9 * step)
    vx = vertical_lines(rgb)
    order = list(COLS)
    bounds = {}
    for i, c in enumerate(order):
        lo = (centers[order[i - 1]] + centers[c]) / 2 if i else 0.0
        # bord gauche = ligne verticale imprimée la plus proche du milieu entre deux en-têtes
        near = [x for x in vx if abs(x - lo) < 0.25 * step] if i else []
        bounds[c] = [min(near, key=lambda x: abs(x - lo)) if near else lo, width]
    for a, b in zip(order, order[1:]):
        bounds[a][1] = bounds[b][0]
    header_bottom = max(v[2] for v in found.values())
    return {c: tuple(v) for c, v in bounds.items()}, header_bottom


def _zoom(reader, rgb: np.ndarray, box, allow: str | None) -> str:
    import cv2
    x0, y0, x1, y1 = (int(v) for v in box)
    a = rgb[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4]
    if a.size == 0:
        return ""
    a = cv2.resize(a, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    try:
        return " ".join(reader.readtext(a, detail=0, paragraph=True, allowlist=allow)).strip()
    except Exception:  # noqa: BLE001
        return ""


def snap_vaccine(raw: str) -> tuple[str, bool]:
    """(vaccin du vocabulaire, reconnu ?) — correspondance approchée."""
    n = norm_label(raw)
    best, score = raw, 0.0
    for v in VACCINS:
        s = difflib.SequenceMatcher(None, n, norm_label(v)).ratio()
        if s > score:
            best, score = v, s
    return (best, True) if score >= 0.6 else (raw, False)


def norm_dose(raw: str) -> str:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(cc|ml)?", raw.lower())
    if not m:
        return raw.strip()
    return f"{m.group(1).replace('.', ',')} {m.group(2) or 'cc'}"


def read_entries(img: Image.Image, reader, tokens=None) -> tuple[list[dict], dict]:
    """-> (entrées [{col: [(texte, conf, source)], 'y': .., 'rappel': ..}], diagnostic).
    `tokens` : OCR de la page déjà fait (classification), en pixels de `img` — pas de 2e passe."""
    from ai.ocr_classique import Token
    s = 0.5 if img.size[0] > 1600 else 1.0              # écriture grande : 2x plus rapide, aussi lisible
    if s != 1.0:
        img = img.resize((int(img.size[0] * s), int(img.size[1] * s)))
    rgb = np.asarray(img.convert("RGB"))
    if tokens is None:
        toks = [Token(str(t), (min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b),
                               max(p[1] for p in b)), float(c)) for b, t, c in reader.readtext(rgb, paragraph=False)]
    else:
        toks = [Token(t.text, tuple(v * s for v in t.box), t.conf) for t in tokens]
    cb = column_bounds(toks, rgb)
    if cb is None:
        return [], {"erreur": "en-têtes du tableau introuvables"}
    bounds, top = cb
    clean = blue_only(rgb)
    ink = [Token(str(t), (min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b), max(p[1] for p in b)),
                 float(c)) for b, t, c in reader.readtext(clean, paragraph=False)]
    ink = [t for t in ink if t.box[1] > top - 2 and t.text.strip()]
    # lignes d'écriture
    hs = sorted(t.box[3] - t.box[1] for t in ink) or [20]
    tol = 0.6 * hs[len(hs) // 2]
    lines: list[list] = []
    for t in sorted(ink, key=lambda t: (t.box[1] + t.box[3]) / 2):
        cy = (t.box[1] + t.box[3]) / 2
        if lines and abs(cy - np.mean([(u.box[1] + u.box[3]) / 2 for u in lines[-1]])) < tol:
            lines[-1].append(t)
        else:
            lines.append([t])
    entries: list[dict] = []
    for line in lines:
        cells: dict[str, list] = {}
        for c, (x0, x1) in bounds.items():
            ws = sorted((t for t in line if x0 <= (t.box[0] + t.box[2]) / 2 < x1), key=lambda t: t.box[0])
            if not ws:
                continue
            raw = " ".join(t.text for t in ws)
            conf = float(np.mean([t.conf for t in ws]))
            box = (min(t.box[0] for t in ws), min(t.box[1] for t in ws), max(t.box[2] for t in ws),
                   max(t.box[3] for t in ws))
            reads = [(raw, conf, "page")]
            z = _zoom(reader, clean, box, ALLOW.get(c))
            if z:
                reads.append((z, conf, "zoom"))
            cells[c] = reads
        if not cells:
            continue
        y = float(np.mean([(t.box[1] + t.box[3]) / 2 for t in line]))
        if entries and "date" not in cells and "vaccin" not in cells:
            for c, r in cells.items():                   # suite de l'entrée précédente (2e ligne imprimée)
                entries[-1].setdefault(c, r)
            entries[-1]["y1"] = y
            continue
        entries.append({**cells, "y": y, "y1": y})
    # dates au crayon gris -> rappel probable de l'entrée la plus proche
    pencil = pencil_mask(rgb)
    blue = blue_mask(rgb)
    for t in toks:
        if t.box[1] < top or not DATE_RE.search(t.text) or not entries:
            continue
        x0, y0, x1, y1 = (int(v) for v in t.box)
        zone = (slice(max(0, y0), y1), slice(max(0, x0), x1))
        if blue[zone].mean() > 0.02 or pencil[zone].mean() < 0.03:
            continue
        cy = (y0 + y1) / 2
        e = min(entries, key=lambda e: min(abs(cy - e["y"]), abs(cy - e["y1"])))
        e.setdefault("rappel", [(DATE_RE.search(t.text).group(0), min(t.conf, 0.5), "crayon")])
    return entries[:MAX_ENTREES], {"colonnes": {c: [round(v) for v in b] for c, b in bounds.items()},
                                   "lignes_ecriture": len(lines), "entrees": len(entries)}


def read_vaccination_states(img: Image.Image, reader, bands, tokens=None) -> tuple[dict, dict]:
    """Entrées -> FieldState du pipeline (fusion, 2e avis et statuts : ai/extract.py)."""
    from ai.extract import FieldState, Reading
    from ai.ocr_classique import _band_of
    T = get_template()
    entries, diag = read_entries(img, reader, tokens)
    h = img.size[1] // 2 if img.size[0] > 1600 else img.size[1]
    states = {}
    for i, e in enumerate(entries, 1):
        band = _band_of(e["y"] / h, bands)
        for c in (*COLS, "rappel"):
            if c not in e:
                continue
            key = f"vaccinations.E{i}.{c}"
            st = FieldState(T.fields[key], flags=["lecture_ocr"])
            seen = set()
            for raw, conf, src in e[c]:
                if c == "vaccin":
                    raw, known = snap_vaccine(raw)
                    if not known:
                        st.flags.append("hors_vocabulaire")
                    elif norm_label(raw) != norm_label(e[c][0][0]):
                        conf = min(conf, 0.6)            # corrigé vers le vocabulaire : à vérifier
                elif c == "dose":
                    raw = norm_dose(raw)
                elif c in ("date", "rappel"):
                    m = DATE_RE.search(raw)
                    raw = m.group(0) if m else raw
                if norm_label(str(raw)) in seen:
                    continue                             # zoom = même moteur : identique ne vaut pas 2 avis
                seen.add(norm_label(str(raw)))
                st.readings.append(Reading(key, raw, "LISIBLE", conf, band))
            if c == "rappel":
                st.flags.append("crayon_gris")
            states[key] = st
    return states, diag
