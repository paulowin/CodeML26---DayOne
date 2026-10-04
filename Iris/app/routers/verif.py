"""Page de vérification LOCALE (HTML simple, sans framework JS) : ce que l'extraction a enregistré.

- GET /verif                          liste des dossiers (plus récent d'abord)
- GET /verif/{id}                     par page : image d'origine | champs courants (+ « attendu »
                                      si la page est une page du défi avec vérité terrain)
- GET /verif/{id}/pages/{n}/image     image déchiffrée EN MÉMOIRE (jamais écrite en clair)
- GET /verif/{id}/pages/{n}/cases     image de debug des cases à cocher (si elle existe)

Accès : poste local uniquement (127.0.0.1, sans en-tête X-Forwarded-For : une requête passée
par ngrok porte cet en-tête -> 403), ou clé du personnel (X-API-Key ou ?key=). Chaque image
affichée est tracée dans AccessLog. Aucun identifiant direct n'est affiché (ils ne sont pas stockés ;
les `_identifiants` de la vérité terrain ne sont jamais lus ici).
"""
from __future__ import annotations

import html
import json
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccessLog, FieldSource, FieldStatus, Page, Record, Role, Staff
from app.security import hash_api_key
from app.storage import StorageError, get_store
from app.templates import get_template

router = APIRouter(tags=["verification"])
T = get_template()
ORDER = {k: i for i, k in enumerate(T.fields)}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
LOCAL_LABEL = "poste local (/verif)"
ROOT = Path(__file__).resolve().parent.parent.parent


# ------------------------------------------------------------------ accès
def require_local_or_staff(request: Request, db: Session = Depends(get_db)) -> Staff:
    key = request.headers.get("x-api-key") or request.query_params.get("key")
    if key:
        staff = db.scalar(select(Staff).where(Staff.api_key_hash == hash_api_key(key), Staff.active.is_(True)))
        if staff:
            return staff
        raise HTTPException(401, "Clé du personnel invalide")
    host = request.client.host if request.client else ""
    if request.headers.get("x-forwarded-for") or host not in LOCAL_HOSTS:
        raise HTTPException(403, "Page de vérification réservée au poste local (ou à une clé du personnel)")
    return _local_staff(db)


def _local_staff(db: Session) -> Staff:
    """Compte technique DÉSACTIVÉ (sa clé ne sert à rien) : rattache les accès locaux à AccessLog."""
    st = db.scalar(select(Staff).where(Staff.label == LOCAL_LABEL))
    if st is None:
        st = Staff(label=LOCAL_LABEL, role=Role.SUPERVISEUR, api_key_hash=hash_api_key(secrets.token_hex(32)),
                   active=False)
        db.add(st)
        db.commit()
    return st


def _log(db: Session, staff: Staff, record: Record, action: str, page_id: str | None = None, allowed=True):
    db.add(AccessLog(staff_id=staff.id, record_id=record.id, page_id=page_id, action=action, allowed=allowed))
    db.commit()


def _check_record(db: Session, staff: Staff, rec: Record | None, action: str) -> Record:
    if rec is None:
        raise HTTPException(404, "Dossier introuvable")
    allowed = staff.role in (Role.ADMIN, Role.SUPERVISEUR) or staff.midwife_id == rec.midwife_id
    if not allowed:
        _log(db, staff, rec, action, allowed=False)
        raise HTTPException(403, "Accès refusé à ce dossier")
    return rec


# ------------------------------------------------------------------ vérité terrain (pages du défi)
@lru_cache(maxsize=1)
def _manifest_by_sha() -> dict:
    p = ROOT / "eval" / "manifest.json"
    if not p.exists():
        return {}
    return {e["sha256"]: e for e in json.loads(p.read_text(encoding="utf-8"))["images"]}


def expected_for(page: Page) -> tuple[dict | None, dict | None]:
    """(entrée du manifeste, vérité terrain) si l'image est une page du défi ; jamais les _identifiants."""
    from eval.common import GT_DIR, gt_name_for
    e = _manifest_by_sha().get(page.sha256)
    if not e:
        return None, None
    p = GT_DIR / gt_name_for(e)
    if not p.exists():
        return e, None
    gt = json.loads(p.read_text(encoding="utf-8"))
    return e, {"fields": {k: v for k, v in gt.get("fields", {}).items() if v is not None}}


def debug_image(entry: dict | None) -> Path | None:
    if not entry:
        return None
    stem = Path(entry["file"]).stem
    hits = sorted((ROOT / "eval" / "preds").glob(f"*/debug_{stem}.png"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


# ------------------------------------------------------------------ rendu
CSS = """
:root{--fg:#111;--mut:#6B6B6B;--line:#E6E6E6;--acc:#4A1942;--ok:#2E7D4F;--rev:#B8650A;--err:#B3261E;--nl:#9A9A9A}
*{box-sizing:border-box}
body{font-family:system-ui,"Segoe UI",sans-serif;font-size:15px;line-height:1.5;margin:0;color:var(--fg);
background:#fff;font-variant-numeric:tabular-nums}
.top{max-width:1400px;margin:0 auto;padding:24px 40px 0}
.brand{color:var(--acc);font-weight:700;font-size:14px;letter-spacing:.02em}
main{max-width:1400px;margin:0 auto;padding:8px 40px 64px}
h1{font-size:28px;font-weight:600;line-height:1.25;margin:24px 0 8px;color:var(--fg)}
h1 .st{display:block;margin-top:6px;font-size:12px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;
color:var(--mut)}
h2{font-size:17px;font-weight:600;margin:48px 0 16px;padding-top:24px;border-top:1px solid var(--line);color:var(--acc)}
p{margin:12px 0}.meta{color:var(--mut);font-size:14px}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
button{font:inherit;font-size:13px;color:var(--fg);background:#fff;border:1px solid var(--line);border-radius:4px;
padding:4px 12px;cursor:pointer}a+button{margin-left:16px}button:hover{background:#F7F7F7}
table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}
th,td{border:0;border-bottom:1px solid var(--line);padding:9px 12px 9px 0;text-align:left;vertical-align:top}
th{position:sticky;top:0;background:#fff;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
color:var(--mut)}
.liste tr:hover td{background:#F7F7F7}
.liste td.ok,.liste td.rev,.liste td.nl{text-align:right}.liste th.n{text-align:right}
td.nl,.liste td.nl{color:var(--nl)}
td.st{white-space:nowrap;font-size:13px}
td.st::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;
vertical-align:1px;background:var(--nl)}
tr.ok td.st::before{background:var(--ok)}tr.rev td.st::before{background:var(--rev)}
tr.nl td{color:var(--nl)}
.faux{color:var(--err);font-weight:600}
.page{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:40px;margin:16px 0;align-items:start}
.page .img{position:sticky;top:24px}.page .img img{width:100%;display:block;border:1px solid var(--line)}
.page .img p{font-size:13px}
.page .tab{max-height:90vh;overflow:auto}
@media (max-width:1100px){.page{grid-template-columns:1fr}.page .img{position:static}.page .tab{max-height:none}}
@media (max-width:640px){.top,main{padding-left:16px;padding-right:16px}}
.stats{display:flex;flex-wrap:wrap;margin:32px 0 8px;padding:20px 0 0;border-top:1px solid var(--line)}
.stats span{display:flex;flex-direction:column;padding:0 40px 0 0;margin-right:40px;border-right:1px solid var(--line);
font-size:12px;color:var(--mut);max-width:220px}
.stats span:last-child{border-right:0}
.stats b{order:-1;font-size:32px;font-weight:600;line-height:1.1;color:var(--fg);margin-bottom:4px}
.stats span.alert b{color:var(--err)}
.alerte{border-left:3px solid var(--err);background:#fff;padding:8px 16px;margin:16px 0;color:var(--fg)}
.alerte b{font-weight:600}.alerte small{color:var(--mut);font-size:13px}
"""


def _page_html(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>{html.escape(title)}"
                        "</title><meta name='viewport' content='width=device-width,initial-scale=1'>"
                        f"<style>{CSS}</style></head><body><header class='top'><span class='brand'>Iris</span></header>"
                        f"<main>{body}</main></body></html>")


def _source(ef, rec: Record) -> str:
    flags = _flags(ef)
    if ef.source == FieldSource.SAGE_FEMME:
        return "sage-femme"
    if ef.source == FieldSource.SYSTEME:
        return "système"
    if "lecture_cv" in flags:
        return "case"
    if (rec.extraction_model or "").startswith("ocr:"):
        return "ocr"
    return "ia"


def _flags(ef) -> list:
    try:
        return (json.loads(ef.details_json) or {}).get("flags") or [] if ef.details_json else []
    except ValueError:
        return []


def _value(ef):
    return json.loads(ef.value_json) if ef.value_json else None


def _css(ef) -> str:
    if ef.status == FieldStatus.CONNU and (ef.confidence or 0) >= 0.8 and _value(ef) is not None:
        return "ok"
    if ef.status in (FieldStatus.A_REVISER, FieldStatus.ILLISIBLE):
        return "rev"
    if ef.status == FieldStatus.CONNU:
        return "ok"
    return "nl"


def _counts(rec: Record) -> dict:
    cur = [f for f in rec.fields if f.is_current]
    return {"CONNU": sum(f.status == FieldStatus.CONNU for f in cur),
            "A_REVISER": sum(f.status == FieldStatus.A_REVISER for f in cur),
            "ILLISIBLE": sum(f.status == FieldStatus.ILLISIBLE for f in cur),
            "non lus": sum(f.status in (FieldStatus.NON_FOURNI, FieldStatus.NON_APPLICABLE, FieldStatus.INCONNU)
                           for f in cur)}


@router.get("/verif", response_class=HTMLResponse)
def verif_list(staff: Staff = Depends(require_local_or_staff), db: Session = Depends(get_db)):
    q = select(Record).order_by(Record.created_at.desc())
    if staff.role == Role.SAGE_FEMME:
        q = q.where(Record.midwife_id == staff.midwife_id)
    rows = []
    for rec in db.scalars(q.limit(200)).all():
        c = _counts(rec)
        rows.append(f"<tr><td><a href='/verif/{rec.id}'>{rec.id[:8]}</a></td>"
                    f"<td>{rec.created_at:%d/%m/%Y %H:%M}</td><td>{rec.status.value}</td>"
                    f"<td>{len([p for p in rec.pages if not p.replaced])}</td>"
                    f"<td class='ok'>{c['CONNU']}</td><td class='rev'>{c['A_REVISER']}</td>"
                    f"<td class='rev'>{c['ILLISIBLE']}</td><td class='nl'>{c['non lus']}</td></tr>")
    body = ("<h1>Vérification de l'extraction</h1>"
            "<p><button onclick='location.reload()'>Rafraîchir</button></p>"
            "<table class='liste'><tr><th>Dossier</th><th>Date</th><th>Statut</th><th>Pages</th><th class='n'>CONNU</th>"
            "<th class='n'>À réviser</th><th class='n'>Illisibles</th><th class='n'>Non lus</th></tr>" + "".join(rows) + "</table>")
    return _page_html("Vérification – dossiers", body)


@router.get("/verif/{record_id}", response_class=HTMLResponse)
def verif_record(record_id: str, request: Request, staff: Staff = Depends(require_local_or_staff),
                 db: Session = Depends(get_db)):
    from app.services.conversation import field_label, fmt_value
    from app.templates.normalize import values_equal
    rec = _check_record(db, staff, db.get(Record, record_id), "verif_record")
    _log(db, staff, rec, "verif_record")
    cur = {f"{f.section}.{f.field_key}": f for f in rec.fields if f.is_current}
    qk = request.query_params.get("key")
    key_q = f"?key={html.escape(qk)}" if qk else ""
    total = {"attendus": 0, "justes": 0, "couverts": 0, "silencieuses": 0}
    blocks = []
    pages = sorted(rec.pages, key=lambda p: p.page_number) or [None]
    for page in pages:
        n = page.page_number if page else None
        entry, gt = expected_for(page) if page else (None, None)
        gt_fields = (gt or {}).get("fields", {})
        first = pages[0] is page
        keys = sorted((k for k, f in cur.items() if f.page_number == n or (first and f.page_number is None)),
                      key=lambda k: ORDER.get(k, 10**6))
        keys += [k for k in gt_fields if k not in keys]          # attendus non lus
        lines = []
        for k in keys:
            f = T.fields.get(k)
            ef = cur.get(k)
            label = html.escape(field_label(k)) if f else html.escape(k)
            if ef is not None:
                val = _value(ef)
                tds = (f"<td>{html.escape(ef.raw_text or '')}</td>"
                       f"<td>{html.escape(fmt_value(f, val)) if f else html.escape(str(val))}</td>"
                       f"<td class='st'>{ef.status.value}</td><td>{ef.confidence:.2f}</td><td>{_source(ef, rec)}</td>")
                css = _css(ef)
            else:
                val, tds, css = None, "<td></td><td>—</td><td class='st'>non lu</td><td></td><td></td>", "nl"
            exp_td = ""
            if gt is not None:
                if k in gt_fields and f is not None:
                    total["attendus"] += 1
                    exp = gt_fields[k]
                    ok = ef is not None and val is not None and values_equal(f, exp, val)
                    if ef is not None and val is not None:
                        total["couverts"] += 1
                    total["justes"] += ok
                    if ef is not None and val is not None and not ok and ef.status == FieldStatus.CONNU:
                        total["silencieuses"] += 1
                    exp_td = (f"<td class='{'juste' if ok else 'faux'}'>"
                              f"{html.escape(fmt_value(f, exp) if not isinstance(exp, str) else exp)}</td>")
                else:
                    exp_td = "<td></td>"
            lines.append(f"<tr class='{css}'><td>{html.escape(k.split('.')[0])}</td><td>{label}</td>{tds}{exp_td}</tr>")
        head = ("<tr><th>Section</th><th>Libellé</th><th>Valeur brute</th><th>Valeur normalisée</th><th>Statut</th>"
                "<th>Conf.</th><th>Source</th>" + ("<th>Attendu</th>" if gt is not None else "") + "</tr>")
        img = ""
        if page is not None:
            img = f"<img src='/verif/{rec.id}/pages/{n}/image{key_q}' alt='page {n}'>"
            if debug_image(entry):
                img += (f"<p><a href='/verif/{rec.id}/pages/{n}/cases{key_q}' target='_blank'>"
                        "Superposer : détection des cases (vert = cochée, rouge = vide, orange = incertaine)</a></p>")
        title = f"Page {n}" + (f" – {html.escape(page.page_type or '')}" if page else "") + \
                (" (remplacée)" if page is not None and page.replaced else "") + \
                (f" – page du défi : {html.escape(entry['file'])}" if entry else "")
        blocks.append(f"<h2>{title}</h2><div class='page'><div class='img'>{img}</div>"
                      f"<div class='tab'><table>{head}{''.join(lines)}</table></div></div>")
    stats = ""
    if total["attendus"]:
        a = total["attendus"]
        stats = ("<div class='stats'>"
                 f"<span>Exactitude : <b>{100 * total['justes'] / a:.1f} %</b> ({total['justes']}/{a})</span>"
                 f"<span>Couverture : <b>{100 * total['couverts'] / a:.1f} %</b></span>"
                 f"<span{' class=alert' if total['silencieuses'] else ''}>Erreurs silencieuses (faux mais affiché sûr) : <b>{total['silencieuses']}</b></span></div>")
    c = _counts(rec)
    from app.services import alerts
    al = alerts.message(alerts.record_alerts(rec), "fr")
    banner = ("<div class='alerte'>"
              f"<b>{html.escape(al)}</b><br><small>Aide à la décision, pas un diagnostic : seules les valeurs "
              f"confirmées par la sage-femme sont prises en compte.</small></div>") if al else ""
    body = (f"<p><a href='/verif'>← tous les dossiers</a> <button onclick='location.reload()'>Rafraîchir</button></p>"
            f"<h1>Dossier {rec.id[:8]} <span class='st'>– {rec.status.value}</span></h1>{banner}"
            f"<p class='meta'>Modèle : {html.escape(rec.extraction_model or '—')} · CONNU {c['CONNU']} · à réviser {c['A_REVISER']}"
            f" · illisibles {c['ILLISIBLE']} · non lus {c['non lus']}</p>{stats}" + "".join(blocks))
    return _page_html(f"Vérification – {rec.id[:8]}", body)


def _page_of(rec: Record, n: int) -> Page:
    page = next((p for p in rec.pages if p.page_number == n), None)
    if page is None:
        raise HTTPException(404, "Page introuvable")
    return page


@router.get("/verif/{record_id}/pages/{n}/image")
def verif_image(record_id: str, n: int, staff: Staff = Depends(require_local_or_staff),
                db: Session = Depends(get_db)):
    rec = _check_record(db, staff, db.get(Record, record_id), "verif_image")
    page = _page_of(rec, n)
    _log(db, staff, rec, "verif_image", page.id)
    try:
        data = get_store().load(page.storage_key)                # déchiffrée en mémoire seulement
    except StorageError:
        raise HTTPException(500, "Image indisponible ou altérée")
    return Response(content=data, media_type=page.mime_type,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/verif/{record_id}/pages/{n}/cases")
def verif_cases_debug(record_id: str, n: int, staff: Staff = Depends(require_local_or_staff),
                      db: Session = Depends(get_db)):
    rec = _check_record(db, staff, db.get(Record, record_id), "verif_cases")
    page = _page_of(rec, n)
    path = debug_image(expected_for(page)[0])
    if path is None:
        raise HTTPException(404, "Pas d'image de debug des cases pour cette page")
    _log(db, staff, rec, "verif_cases", page.id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
