"""Détection (PAS lecture) de l'écriture arabe dans une zone de champ.

Le lecteur EasyOCR principal est ["fr", "en"] : un mot arabe y sort en charabia peu sûr.
Sur ces zones-là seulement (lecture vide ou peu sûre), un 2e lecteur EasyOCR ["ar", "en"], chargé
à la demande (jamais au démarrage), regarde s'il voit de l'arabe ; le 2e avis Ollama qui répond en
caractères arabes (U+0600–U+06FF) le signale aussi. Le champ devient alors A_REVISER, raison
« écrit en arabe » : la sage-femme donne la valeur. Une lecture arabe n'est jamais CONNU.
"""
from __future__ import annotations

import logging
import re
import time

import numpy as np

log = logging.getLogger(__name__)

ARABIC = re.compile(r"[؀-ۿ]")
DOUBT_CONF = 0.5                 # lecture française en dessous : on regarde si c'est de l'arabe
MIN_ARABIC_CHARS = 2
PAGE_BUDGET_S = 5.0              # au plus 5 s de détection par page (≈ 0,9 s par zone sur CPU)
_reader = None
load_seconds: float | None = None


def has_arabic(text) -> bool:
    return isinstance(text, str) and len(ARABIC.findall(text)) >= MIN_ARABIC_CHARS


def reader_loaded() -> bool:
    return _reader is not None


def reader():
    """Lecteur ['ar', 'en'] chargé à la PREMIÈRE zone douteuse seulement (coût mesuré : load_seconds)."""
    global _reader, load_seconds
    if _reader is None:
        import easyocr
        t0 = time.monotonic()
        _reader = easyocr.Reader(["ar", "en"], gpu=False, verbose=False)
        load_seconds = time.monotonic() - t0
        log.info("Lecteur arabe chargé en %.1f s", load_seconds)
    return _reader


def zone_is_arabic(rgb: np.ndarray, box: tuple[float, float, float, float]) -> bool:
    """La zone (pixels x0, y0, x1, y1) contient-elle de l'écriture arabe ?"""
    x0, y0, x1, y1 = (int(v) for v in box)
    a = rgb[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4]
    if a.size == 0:
        return False
    try:
        found = reader().readtext(np.ascontiguousarray(a), paragraph=False)
    except Exception:  # noqa: BLE001  (modèle arabe absent : on ne bloque jamais la lecture)
        log.exception("Détection de l'arabe impossible")
        return False
    return any(has_arabic(t) and c >= 0.2 for _, t, c in found)
