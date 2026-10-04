"""Prétraitement des photos (en mémoire uniquement, jamais d'écriture disque).

orientation EXIF -> contrôle qualité (flou, luminosité, résolution) ->
redressement léger -> contraste (CLAHE) -> découpe en bandes horizontales
qui se recouvrent (chaque bande ≤ 1280 px) + vignette pour la classification.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1280
ALT_SIDE = 1024          # vue alternative pour le 2e avis (gris, sans CLAHE) : lecture moins corrélée
THUMB_SIDE = 896
N_BANDS = 3
OVERLAP = 0.15

# seuils de qualité (mesurés sur les pages spécimen et les vraies photos du défi)
BLUR_MIN = 40.0          # variance du Laplacien (image ramenée à 1000 px de large)
DARK_MAX_MEAN = 70.0
BRIGHT_MIN_MEAN = 245.0
MIN_SHORT_SIDE = 600


class ImageError(Exception):
    pass


@dataclass
class Band:
    index: int
    y0: float              # position relative dans la page (0 = haut)
    y1: float
    jpeg: bytes
    alt_jpeg: bytes = b""     # même bande, autre rendu (2e avis)


@dataclass
class PreparedPage:
    quality: dict
    bands: list[Band] = field(default_factory=list)
    thumb: bytes = b""
    deskew_deg: float = 0.0


def load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except Exception as e:  # noqa: BLE001  (format inconnu, fichier tronqué...)
        raise ImageError(f"image illisible : {e}") from e


def _gray(img: Image.Image, width: int | None = None) -> np.ndarray:
    g = np.asarray(img.convert("L"))
    if width and g.shape[1] != width:
        h = int(g.shape[0] * width / g.shape[1])
        g = cv2.resize(g, (width, h), interpolation=cv2.INTER_AREA)
    return g


def quality(img: Image.Image) -> dict:
    g = _gray(img, 1000)
    blur = float(cv2.Laplacian(g, cv2.CV_64F).var())
    mean = float(g.mean())
    w, h = img.size
    reasons = []
    if blur < BLUR_MIN:
        reasons.append("floue")
    if mean < DARK_MAX_MEAN:
        reasons.append("sombre")
    if mean > BRIGHT_MIN_MEAN:
        reasons.append("surexposée")
    if min(w, h) < MIN_SHORT_SIDE:
        reasons.append("résolution trop faible")
    return {"ok": not reasons, "raisons": reasons, "flou": round(blur, 1), "luminosite": round(mean, 1),
            "resolution": [w, h]}


def estimate_skew(img: Image.Image) -> float:
    """Angle (degrés) des lignes quasi horizontales (lignes du formulaire), médiane, borné à ±10°."""
    g = _gray(img, 1000)
    edges = cv2.Canny(g, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=120, minLineLength=250, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) <= 10:
            angles.append(a)
    return float(np.median(angles)) if len(angles) >= 3 else 0.0


def deskew(img: Image.Image, angle: float) -> Image.Image:
    if abs(angle) < 0.3:
        return img
    return img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))


def enhance(img: Image.Image) -> Image.Image:
    lab = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return Image.fromarray(cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB))


def fit(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    s = max_side / max(w, h)
    return img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS) if s < 1 else img


def to_jpeg(img: Image.Image, q: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q)
    return buf.getvalue()


def split_bands(img: Image.Image, n: int = N_BANDS, overlap: float = OVERLAP) -> list[tuple[float, float, Image.Image]]:
    w, h = img.size
    band_h = h / (n - (n - 1) * overlap)
    step = band_h * (1 - overlap)
    out = []
    for i in range(n):
        top = int(round(i * step))
        bottom = h if i == n - 1 else int(round(top + band_h))
        out.append((top / h, bottom / h, img.crop((0, top, w, bottom))))
    return out


def prepare(data: bytes, n_bands: int = N_BANDS) -> PreparedPage:
    img = load_image(data)
    q = quality(img)
    angle = estimate_skew(img)
    straight = deskew(img, angle)
    img = enhance(straight)
    alts = [fit(b.convert("L").convert("RGB"), ALT_SIDE) for _, _, b in split_bands(straight, n_bands)]
    bands = [Band(i, y0, y1, to_jpeg(fit(b, MAX_SIDE)), to_jpeg(alts[i]))
             for i, (y0, y1, b) in enumerate(split_bands(img, n_bands))]
    return PreparedPage(q, bands, to_jpeg(fit(img, THUMB_SIDE), 85), round(angle, 2))
