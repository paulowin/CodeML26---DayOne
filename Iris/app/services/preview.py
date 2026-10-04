"""Aperçu de la zone douteuse (bloc 4) : la bande de la photo où l'IA a lu le champ,
avec les zones d'identité masquées (nom, CIN, adresse, téléphone, « Vu par »...).

L'image n'est fabriquée qu'au moment de l'envoi (par l'outbox), EN MÉMOIRE : rien de
déchiffré n'est écrit sur disque. Masquage : bandeaux pleine largeur aux positions des
identifiants de ce type de page (`PageType.identifier_zones`, positions relatives avec
marge, calées sur le spécimen ET les vraies photos du défi). Sur une photo cadrée très
différemment, le masquage reste approximatif : WHATSAPP_APERCUS=false pour désactiver.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy.orm import Session

from app.models import Page, Record
from app.storage import StorageError, get_store
from app.templates import get_template

T = get_template()
MAX_SIDE = 1280
MARGIN = 0.03                 # un peu de contexte au-dessus / au-dessous de la bande
MASK_COLOR = (120, 120, 120)


def _font(size: int):
    """Police avec accents (Arial / DejaVu) ; à défaut, police intégrée + texte sans accents."""
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size), "zone masquée (identité)"
        except OSError:
            continue
    return ImageFont.load_default(), "zone masquee (identite)"


def identifier_zones(page_type: str | None) -> tuple[tuple[float, float], ...]:
    if not page_type:
        return ()
    try:
        return T.page_type(page_type).identifier_zones
    except StopIteration:
        return ()


def render(img: Image.Image, zone: tuple[float, float], page_type: str | None) -> bytes:
    """Découpe [y0, y1] (relatif) + masque les zones d'identité qui la chevauchent -> JPEG."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    y0, y1 = max(0.0, zone[0] - MARGIN), min(1.0, zone[1] + MARGIN)
    crop = img.crop((0, int(y0 * h), w, int(y1 * h)))
    draw = ImageDraw.Draw(crop)
    ch = crop.size[1]
    font, label = _font(max(14, w // 45))
    for z0, z1 in identifier_zones(page_type):
        top, bottom = (max(z0, y0) - y0) * h, (min(z1, y1) - y0) * h
        if bottom > top:
            draw.rectangle((0, int(top), w, min(ch, int(bottom) + 1)), fill=MASK_COLOR)
            draw.text((10, int(top) + 4), label, fill=(255, 255, 255), font=font)
    s = MAX_SIDE / max(crop.size)
    if s < 1:
        crop = crop.resize((int(crop.size[0] * s), int(crop.size[1] * s)), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def build(db: Session, spec: dict) -> bytes | None:
    """`spec` = {"record_id", "page_number", "zone": [y0, y1]} -> JPEG, ou None si indisponible."""
    rec = db.get(Record, spec.get("record_id") or "")
    if rec is None:
        return None
    page: Page | None = next((p for p in rec.pages if p.page_number == spec.get("page_number")), None)
    if page is None or page.replaced:
        return None
    try:
        data = get_store().load(page.storage_key)
        img = Image.open(io.BytesIO(data))
        img.load()
    except (StorageError, OSError):
        return None
    z = spec.get("zone") or [0.0, 1.0]
    return render(img, (float(z[0]), float(z[1])), page.page_type)
