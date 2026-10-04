"""Moteur de conversation WhatsApp (bloc 4) : vérification des champs, saisie guidée,
liaison patiente, doublons.

État par sage-femme dans `Midwife.conversation_state` (JSON) :
    {"mode", "record_id", "queue", "idx", "version", "paused", ...}
Un seul dossier en conversation à la fois ; les autres attendent leur tour.

IDs des boutons / lignes : "<action>|<id court du dossier>|<clé>|<version>". Une réponse
dont le dossier ou la version ne correspond plus (dossier déjà avancé, message arrivé en
retard après une coupure réseau) est ignorée : « Cette question n'est plus d'actualité. »

Toute réponse passe par `outbox.enqueue`. Aucun message ne contient de donnée
nominative : seuls les libellés du formulaire, les valeurs médicales et le code de registre.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.i18n import t
from app.models import (ExtractedField, FieldSource, FieldStatus, Midwife, Page, Patient, Record, RecordStatus)
from app.services import outbox
from app.state_machine import date_reference, find_duplicate, transition
from app.templates import get_template
from app.templates.base import FieldDef
from app.templates.normalize import clean_text, fold, interpret, to_date
from app.whatsapp import buttons_message, list_message, text_message

log = logging.getLogger(__name__)
T = get_template()
ORDER = {k: i for i, k in enumerate(T.fields)}
MAX_QUESTIONS = 10
VIEW_PAGE = 12

IDLE, RESUME, REVISION, CORRECTION, FIN = "IDLE", "RESUME", "REVISION", "CORRECTION_ATTENDUE", "FIN_REVISION"
MANUEL, LIAISON, CODE, DOUBLON, PHOTO = "SAISIE_MANUELLE", "LIAISON", "CODE_ATTENDU", "DOUBLON", "PHOTO_ATTENDUE"
PENDING_STATUSES = (RecordStatus.A_REVISER, RecordStatus.REVISION_MANUELLE_REQUISE)
INVALID_FLAGS = {"type_invalide", "hors_plage", "date_invalide", "date_partielle", "ta_sys_inferieure_dia",
                 "choix_inconnu"}

CMD_OK = {"OK", "OUI", "YES", "CONFIRMER", "CONFIRM"}
CMD_PAUSE = {"PLUS TARD", "STOP", "PAUSE", "LATER"}
CMD_RESUME = {"REPRENDRE", "RESUME", "CONTINUER", "CONTINUE"}
CMD_HELP = {"AIDE", "HELP", "?"}
WORDS_BLANK = {"vide", "blank", "passer", "skip", "rien", "-", "—"}
WORDS_ILLEGIBLE = {"illisible", "illegible"}


# ------------------------------------------------------------------ état
def load_state(mw: Midwife) -> dict:
    try:
        st = json.loads(mw.conversation_state) if mw.conversation_state else {}
    except ValueError:
        st = {}
    st.setdefault("mode", IDLE)
    st.setdefault("version", 0)
    return st


def save_state(mw: Midwife, st: dict) -> None:
    mw.conversation_state = json.dumps(st, ensure_ascii=False)


def _reset(st: dict) -> dict:
    return {"mode": IDLE, "version": st.get("version", 0)}


def _bid(st: dict, action: str, key: str = "") -> str:
    return f"{action}|{(st.get('record_id') or '')[:8]}|{key}|{st['version']}"


def _bump(st: dict) -> None:
    st["version"] = st.get("version", 0) + 1


# ------------------------------------------------------------------ envoi
class Out:
    """Petit utilitaire d'envoi dans la langue de la sage-femme."""

    def __init__(self, db: Session, mw: Midwife):
        self.db, self.mw, self.lang = db, mw, mw.language or "fr"

    def tr(self, key: str, **kw) -> str:
        return t(self.lang, key, **kw)

    def text(self, body: str) -> None:
        outbox.enqueue(self.db, text_message(self.mw.wa_id, body))

    def buttons(self, body: str, buttons: list[tuple[str, str]]) -> None:
        outbox.enqueue(self.db, buttons_message(self.mw.wa_id, body[:1024], buttons))

    def rows(self, body: str, rows: list[tuple[str, str, str]]) -> None:
        outbox.enqueue(self.db, list_message(self.mw.wa_id, body[:1024], self.tr("list_choose"), rows[:10]))


# ------------------------------------------------------------------ champs
def current_fields(rec: Record) -> dict[str, ExtractedField]:
    return {f"{f.section}.{f.field_key}": f for f in rec.fields if f.is_current is not False}


def set_field(db: Session, rec: Record, key: str, value, status: FieldStatus, source: FieldSource,
              confidence: float = 1.0, raw_text: str | None = None, details: dict | None = None) -> ExtractedField:
    """Nouvelle version du champ (l'ancienne passe is_current=False) : l'historique est gardé."""
    old = current_fields(rec).get(key)
    if old is not None:
        old.is_current = False
    section, field_key = key.split(".", 1)
    ef = ExtractedField(section=section, field_key=field_key, value_json=json.dumps(value, ensure_ascii=False),
                        raw_text=raw_text, status=status, confidence=confidence, source=source,
                        page_number=old.page_number if old is not None else None, is_current=True,
                        details_json=json.dumps(details, ensure_ascii=False) if details else None)
    rec.fields.append(ef)
    db.flush()
    return ef


def _value(ef: ExtractedField):
    return json.loads(ef.value_json) if ef.value_json else None


def _details(ef: ExtractedField) -> dict:
    try:
        return json.loads(ef.details_json) if ef.details_json else {}
    except ValueError:
        return {}


def field_label(key: str) -> str:
    """« Grossesse actuelle · 2ème trimestre, Visite 1 · TA » (libellés du formulaire)."""
    f = T.fields[key]
    sec = T.section(key.split(".", 1)[0])
    parts = [sec.label_fr]
    if f.table:
        tb = next(tb for tb in sec.tables if tb.key == f.table)
        if tb.rows:
            col_label = dict(tb.cols).get(f.col, f.col)
            if f.table == "visites":
                from ai.prompts import VISIT_COL_HELP          # libellé complet de la colonne
                col_label = VISIT_COL_HELP.get(f.col, col_label)
            row = next((r for r in tb.rows if r.key == f.row), None)
            if tb.instance == "col":
                parts += [col_label, row.label_fr if row else f.row]
            else:
                parts += [row.label_fr if row else f.row, col_label]
        else:
            parts.append(f.label_fr)
    else:
        parts.append(f.label_fr)
    return " · ".join(p.rstrip(" :") for p in parts)


def fmt_value(f: FieldDef, value, lang: str = "fr") -> str:
    if value is None:
        return "—"
    if f.type == "bp" and isinstance(value, dict):
        return f"{value.get('sys')}/{value.get('dia')} mmHg"
    if f.type == "date" and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        y, m, d = value.split("-")
        return f"{d}/{m}/{y}"
    if f.type == "bool":
        return t(lang, "yes") if value else t(lang, "no")
    labels = {c.code: c.label_fr for c in f.choices}
    if f.type == "enum":
        return labels.get(value, str(value))
    if f.type == "checkbox_group":
        return ", ".join(labels.get(v, v) for v in value) or t(lang, "none")
    if f.type in ("int", "float"):
        num = f"{value:g}" if isinstance(value, float) else str(value)
        return f"{num} {f.unit}" if f.unit else num
    return str(value)


def format_hint(f: FieldDef, lang: str) -> str:
    if f.type == "bp":
        return t(lang, "hint_bp")
    if f.type == "date":
        return t(lang, "hint_date")
    if f.type in ("int", "float"):
        rng = t(lang, "hint_range", lo=f"{f.plausible[0]:g}", hi=f"{f.plausible[1]:g}") if f.plausible else ""
        return t(lang, "hint_number", unit=f" ({f.unit})" if f.unit else "", range=rng)
    if f.type == "bool":
        return t(lang, "hint_bool")
    if f.type == "enum":
        return t(lang, "hint_choice", choices=", ".join(c.label_fr for c in f.choices))
    if f.type == "checkbox_group":
        return t(lang, "hint_group", choices=", ".join(c.label_fr for c in f.choices))
    return t(lang, "hint_text")


def parse_answer(f: FieldDef, text: str) -> tuple[str, object] | None:
    """Réponse tapée -> ("valeur", v) | ("vide", None) | ("illisible", None) | None si invalide."""
    from ai.validate import check_field                          # mêmes contrôles que l'IA
    raw = clean_text(text)
    low = fold(raw)
    if low in WORDS_BLANK:
        return ("vide", None)
    if low in WORDS_ILLEGIBLE:
        return ("illisible", None)
    if f.type == "checkbox_group":
        if low in ("aucune", "aucun", "none", "rien"):
            return ("valeur", [])
        codes = [c.code for part in re.split(r"[,;]", raw) for c in f.choices
                 if fold(part) and fold(part) in (fold(c.label_fr), c.code)]
        return ("valeur", sorted(set(codes))) if codes else None
    if f.type == "bool":
        v = {"oui": True, "yes": True, "o": True, "non": False, "no": False, "n": False}.get(low)
        return ("valeur", v) if v is not None else None
    it = interpret(f, raw)
    if it.status or it.value is None or set(it.flags) & INVALID_FLAGS:
        return None
    if set(check_field(f, it.value)) & INVALID_FLAGS:
        return None
    return ("valeur", it.value)


# ------------------------------------------------------------------ dossiers en attente
def _pending_records(db: Session, mw: Midwife, exclude: str | None = None) -> list[Record]:
    recs = db.scalars(select(Record).where(Record.midwife_id == mw.id, Record.status.in_(PENDING_STATUSES))
                      .order_by(Record.created_at)).all()
    return [r for r in recs if r.id != exclude]


def _start_next(db: Session, mw: Midwife, st: dict, out: Out) -> None:
    nxt = _pending_records(db, mw)
    if not nxt:
        save_state(mw, _reset(st))
        return
    rec = nxt[0]
    if rec.status == RecordStatus.REVISION_MANUELLE_REQUISE:
        _manual_intro(db, mw, rec, _reset(st), out)
    else:
        _summary(db, mw, rec, _reset(st), out)


def on_record_ready(db: Session, rec: Record) -> None:
    """Appelé par l'ai_worker quand un dossier passe en A_REVISER."""
    mw = db.get(Midwife, rec.midwife_id)
    st, out = load_state(mw), Out(db, mw)
    if st["mode"] != IDLE and st.get("record_id") not in (None, rec.id):
        out.text(out.tr("queued", rid=rec.id[:8]))
        return
    _summary(db, mw, rec, _reset(st), out)


def on_manual_required(db: Session, rec: Record) -> None:
    """Appelé quand un dossier passe en REVISION_MANUELLE_REQUISE (IA impossible)."""
    mw = db.get(Midwife, rec.midwife_id)
    st, out = load_state(mw), Out(db, mw)
    if st["mode"] != IDLE and st.get("record_id") not in (None, rec.id):
        return                                        # présenté après le dossier en cours
    _manual_intro(db, mw, rec, _reset(st), out)


# ------------------------------------------------------------------ révision
def review_queue(rec: Record) -> tuple[list[str], list[str]]:
    """(questions, débordement) : doutes de l'IA, critiques d'abord, ordre du carnet ; 10 questions max."""
    keys = [k for k, f in current_fields(rec).items()
            if f.source == FieldSource.IA and f.status in (FieldStatus.A_REVISER, FieldStatus.ILLISIBLE)
            and k in T.fields]
    keys.sort(key=lambda k: (not T.fields[k].critique, ORDER.get(k, 10**6)))
    return keys[:MAX_QUESTIONS], keys[MAX_QUESTIONS:]


def _summary(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    queue, overflow = review_queue(rec)
    fields = current_fields(rec)
    read = sum(1 for f in fields.values() if f.value_json not in (None, "null"))
    st.update(mode=RESUME, record_id=rec.id, queue=queue, overflow=overflow, idx=0, paused=False)
    _bump(st)
    body = out.tr("summary", rid=rec.id[:8], read=read, check=len(queue) + len(overflow))
    if not queue and not overflow:
        body += "\n" + out.tr("summary_none")
    others = len(_pending_records(db, mw, exclude=rec.id))
    if others:
        body += "\n" + out.tr("others_waiting", n=others)
    out.buttons(body, [(_bid(st, "REV"), out.tr("btn_verify")), (_bid(st, "PHOTO"), out.tr("btn_retake")),
                       (_bid(st, "LATER"), out.tr("btn_later"))])
    save_state(mw, st)


def _ask_field(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    queue = st.get("queue", [])
    if st["idx"] >= len(queue):
        _final(db, mw, rec, st, out)
        return
    key = queue[st["idx"]]
    ef = current_fields(rec).get(key)
    if ef is None or ef.source != FieldSource.IA:          # déjà tranché entre-temps
        st["idx"] += 1
        _ask_field(db, mw, rec, st, out)
        return
    f = T.fields[key]
    st["mode"] = REVISION
    _bump(st)
    lines = [out.tr("question", i=st["idx"] + 1, n=len(queue), label=field_label(key))]
    value = _value(ef)
    if ef.raw_text or value is not None:
        norm = fmt_value(f, value, out.lang)
        raw = ef.raw_text or norm
        lines.append(out.tr("read_as", raw=raw, norm=out.tr("read_norm", value=norm) if norm != raw else ""))
        lines.append(out.tr("not_sure"))
    else:
        lines.append(out.tr("unreadable"))
    cands = [c for c in _details(ef).get("candidates") or [] if c is not None]
    if len(cands) >= 2:
        lines.append(out.tr("candidates"))
        rows = [(_bid(st, "CAND", f"{key}#{i}"), fmt_value(f, c, out.lang)[:24], out.tr("row_candidate", n=i + 1))
                for i, c in enumerate(cands[:7])]
        rows += [(_bid(st, "CORR", key), out.tr("row_other"), out.tr("row_other_d")),
                 (_bid(st, "ILL", key), out.tr("row_illegible"), out.tr("row_illegible_d")),
                 (_bid(st, "PHOTO", key), out.tr("row_retake"), out.tr("row_retake_d"))]
        out.rows("\n".join(lines), rows)
    elif value is None:
        out.buttons("\n".join(lines), [(_bid(st, "CORR", key), out.tr("btn_correct")),
                                       (_bid(st, "ILL", key), out.tr("btn_illegible")),
                                       (_bid(st, "VIDE", key), out.tr("btn_blank"))])
    else:
        out.buttons("\n".join(lines), [(_bid(st, "CONF", key), out.tr("btn_confirm")),
                                       (_bid(st, "CORR", key), out.tr("btn_correct")),
                                       (_bid(st, "ILL", key), out.tr("btn_illegible"))])
    save_state(mw, st)


def _ask_correction(mw: Midwife, st: dict, out: Out, key: str, back: str) -> None:
    st.update(mode=CORRECTION, pending=key, back=back)
    out.text(out.tr("type_value", label=field_label(key), hint=format_hint(T.fields[key], out.lang)))
    save_state(mw, st)


def _next_question(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    st["idx"] = st.get("idx", 0) + 1
    _ask_field(db, mw, rec, st, out)


def _others(rec: Record, st: dict) -> list[str]:
    """Champs encore « IA » hors questions : à confirmer en bloc."""
    skip = set(st.get("queue", [])) | set(st.get("overflow", []))
    return sorted((k for k, f in current_fields(rec).items() if f.source == FieldSource.IA and k not in skip
                   and k in T.fields), key=lambda k: ORDER.get(k, 10**6))


def _final(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    st["mode"] = FIN
    _bump(st)
    n = len(_others(rec, st))
    body = out.tr("final", n=n) if n else out.tr("final_none")
    buttons = [(_bid(st, "ALLOK"), out.tr("btn_all_ok"))]
    if n:
        buttons.append((_bid(st, "VIEW", "0"), out.tr("btn_view")))
    out.buttons(body, buttons)
    save_state(mw, st)


def _view(db: Session, mw: Midwife, rec: Record, st: dict, out: Out, page: int) -> None:
    keys = _others(rec, st)
    fields = current_fields(rec)
    start = page * VIEW_PAGE
    chunk = keys[start:start + VIEW_PAGE]
    lines = [out.tr("view_head", start=start + 1, end=start + len(chunk), total=len(keys))]
    for i, k in enumerate(chunk, start + 1):
        line = f"{i}. {field_label(k)} : {fmt_value(T.fields[k], _value(fields[k]), out.lang)}"
        lines.append(line[:110])
    lines.append(out.tr("view_tail"))
    body = "\n".join(lines)
    while len(body) > 1024 and len(lines) > 3:                 # limite WhatsApp
        lines.pop(-2)
        body = "\n".join(lines)
    st["mode"] = FIN
    st["view"] = keys
    _bump(st)
    buttons = [(_bid(st, "ALLOK"), out.tr("btn_all_ok"))]
    if start + VIEW_PAGE < len(keys):
        buttons.append((_bid(st, "VIEW", str(page + 1)), out.tr("btn_view_more")))
    out.buttons(body, buttons)
    save_state(mw, st)


def _confirm_all(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    fields = current_fields(rec)
    for k in _others(rec, st):
        ef = fields[k]
        status = ef.status if ef.status in (FieldStatus.NON_FOURNI, FieldStatus.NON_APPLICABLE) else FieldStatus.CONNU
        set_field(db, rec, k, _value(ef), status, FieldSource.SAGE_FEMME, 1.0, ef.raw_text, _details(ef) or None)
    overflow = [k for k in st.get("overflow", []) if k in fields and fields[k].source == FieldSource.IA]
    for k in overflow:                                     # au-delà de 10 questions : superviseur
        ef = fields[k]
        det = _details(ef)
        det["flags"] = sorted(set(det.get("flags") or []) | {"a_verifier_superviseur"})
        set_field(db, rec, k, _value(ef), FieldStatus.A_REVISER, FieldSource.SYSTEME, ef.confidence, ef.raw_text, det)
    transition(db, rec, RecordStatus.VALIDE, f"midwife:{mw.id}", "vérifié sur WhatsApp")
    msg = out.tr("validated", rid=rec.id[:8])
    if overflow:
        msg += "\n" + out.tr("overflow", n=len(overflow))
    out.text(msg)
    start_linking(db, mw, rec, st, out)


# ------------------------------------------------------------------ photo à reprendre
def _ask_photo(db: Session, mw: Midwife, rec: Record, st: dict, out: Out, key: str = "") -> None:
    pages = [p for p in sorted(rec.pages, key=lambda p: p.page_number) if not p.replaced]
    target = None
    if key and key in current_fields(rec):
        n = current_fields(rec)[key].page_number
        target = next((p for p in pages if p.page_number == n), None)
    if target is None and len(pages) == 1:
        target = pages[0]
    if target is None and pages:
        _bump(st)
        rows = [(_bid(st, "PHOTOPAGE", str(p.page_number)), out.tr("row_page", n=p.page_number),
                 _page_type_label(p)) for p in pages]
        out.rows(out.tr("retake_which"), rows)
        save_state(mw, st)
        return
    st.update(mode=PHOTO, photo_page=target.page_number if target else None)
    out.text(out.tr("retake_ask", n=target.page_number if target else 1, ptype=_page_type_label(target)))
    save_state(mw, st)


def _page_type_label(p: Page | None) -> str:
    if p is None or not p.page_type:
        return "registre"
    try:
        pt = T.page_type(p.page_type)
        return pt.label_fr or pt.key
    except StopIteration:
        return p.page_type


def awaiting_photo(mw: Midwife) -> bool:
    return load_state(mw)["mode"] == PHOTO


def attach_replacement_photo(db: Session, mw: Midwife, page_kwargs: dict) -> Record | None:
    """La photo reçue remplace la page demandée ; le dossier repart en lecture IA."""
    st, out = load_state(mw), Out(db, mw)
    rec = db.get(Record, st.get("record_id") or "")
    if rec is None or rec.status != RecordStatus.A_REVISER:
        save_state(mw, _reset(st))
        return None
    old_no = st.get("photo_page")
    old = next((p for p in rec.pages if p.page_number == old_no), None)
    new_no = max((p.page_number for p in rec.pages), default=0) + 1
    if old is not None:
        old.replaced = True
    rec.pages.append(Page(page_number=new_no, replaces_page=old_no, **page_kwargs))
    transition(db, rec, RecordStatus.EN_ATTENTE_IA, f"midwife:{mw.id}", f"page {old_no} reprise en photo")
    out.text(out.tr("retake_ok", n=old_no or new_no, rid=rec.id[:8]))
    save_state(mw, _reset(st))
    db.flush()
    return rec


# ------------------------------------------------------------------ saisie manuelle
def manual_fields(rec: Record) -> list[str]:
    """Champs clés (colonne du CSV ou critiques), hors tableaux, dans l'ordre du carnet."""
    types = {p.page_type for p in rec.pages if p.page_type and not p.replaced}
    sections = [s for pt in T.page_types if pt.key in types for s in pt.sections] or [s.key for s in T.sections]
    keys = [k for k, f in T.stored_fields.items() if f.table is None and k.split(".", 1)[0] in sections
            and (f.csv_column or f.critique)]
    done = {k for k, f in current_fields(rec).items() if f.source == FieldSource.SAGE_FEMME}
    return [k for k in keys if k not in done]


def _manual_intro(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    queue = manual_fields(rec)
    st.update(mode=MANUEL, record_id=rec.id, queue=queue, idx=-1, paused=False)
    _bump(st)
    out.buttons(out.tr("manual_intro", rid=rec.id[:8], n=len(queue)),
                [(_bid(st, "MAN"), out.tr("btn_start")), (_bid(st, "LATER"), out.tr("btn_later"))])
    save_state(mw, st)


def _manual_ask(db: Session, mw: Midwife, rec: Record, st: dict, out: Out) -> None:
    queue = st.get("queue", [])
    if st["idx"] >= len(queue):
        out.text(out.tr("manual_done"))
        transition(db, rec, RecordStatus.VALIDE, f"midwife:{mw.id}", "saisie guidée sur WhatsApp")
        out.text(out.tr("validated", rid=rec.id[:8]))
        start_linking(db, mw, rec, st, out)
        return
    key = queue[st["idx"]]
    st["mode"] = MANUEL
    out.text(out.tr("manual_q", i=st["idx"] + 1, n=len(queue), label=field_label(key),
                    hint=format_hint(T.fields[key], out.lang)))
    save_state(mw, st)


def _manual_answer(db: Session, mw: Midwife, rec: Record, st: dict, out: Out, text: str) -> None:
    if st.get("idx", -1) < 0:
        st["idx"] = 0
        _manual_ask(db, mw, rec, st, out)
        return
    key = st["queue"][st["idx"]]
    f = T.fields[key]
    ans = parse_answer(f, text)
    if ans is None:
        out.text(out.tr("invalid", text=clean_text(text)[:40], hint=format_hint(f, out.lang)))
        return
    kind, value = ans
    status = {"vide": FieldStatus.NON_FOURNI, "illisible": FieldStatus.ILLISIBLE}.get(kind, FieldStatus.CONNU)
    set_field(db, rec, key, value, status, FieldSource.SAGE_FEMME, 1.0, clean_text(text)[:200])
    st["idx"] += 1
    _manual_ask(db, mw, rec, st, out)


# ------------------------------------------------------------------ liaison patiente
_CONFUSIONS = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def find_patients(db: Session, mw: Midwife, code: str, limit: int = 2) -> list[tuple[Patient, int]]:
    """Patientes de CETTE sage-femme : code exact (score 0), puis proche (≤ 1 erreur, confusions O/0,
    I/1, S/5, B/8 comprises) ; triées par score."""
    target = norm_code(code)
    if not target:
        return []
    out = []
    for p in db.scalars(select(Patient).where(Patient.midwife_id == mw.id)).all():
        c = norm_code(p.code)
        if c == target:
            score = 0
        elif c.translate(_CONFUSIONS) == target.translate(_CONFUSIONS):
            score = 1
        elif _edit_distance(c.translate(_CONFUSIONS), target.translate(_CONFUSIONS)) <= 1:
            score = 2
        else:
            continue
        out.append((p, score))
    out.sort(key=lambda ps: (ps[1], ps[0].created_at))
    return out[:limit]


def patient_summary(db: Session, p: Patient) -> tuple[int, str | None]:
    """(nb de visites enregistrées, date de la dernière jj/mm) — aucune donnée nominative."""
    recs = db.scalars(select(Record).where(Record.patient_id == p.id, Record.status.in_(
        [RecordStatus.ENREGISTRE, RecordStatus.SYNCHRONISE, RecordStatus.ECHEC_SYNCHRO]))).all()
    dates = [d for d in (date_reference(r) for r in recs) if d]
    last = max(dates, key=lambda d: to_date(d)) if dates else None
    return len(recs), (last[:5] if last else None)


def _confirmed_code(rec: Record) -> str | None:
    ef = current_fields(rec).get("couverture.numero_fiche")
    if ef is not None and ef.source == FieldSource.SAGE_FEMME and ef.status == FieldStatus.CONNU:
        v = _value(ef)
        return str(v) if v else None
    return None


def start_linking(db: Session, mw: Midwife, rec: Record, st: dict, out: Out, code: str | None = None) -> None:
    code = code or st.get("code") or _confirmed_code(rec)
    st.update(record_id=rec.id, code=code)
    if not code:
        st["mode"] = CODE
        out.text(out.tr("ask_code"))
        save_state(mw, st)
        return
    cands = find_patients(db, mw, code)
    st.update(mode=LIAISON, cands=[p.id for p, _ in cands])
    _bump(st)
    shown = norm_code(code)
    if cands:
        rows = []
        for i, (p, _) in enumerate(cands, 1):
            n, last = patient_summary(db, p)
            rows.append((_bid(st, "LINKP", str(i - 1)), out.tr("row_patient", n=i),
                         out.tr("row_patient_d", code=p.code, visits=n,
                                last=out.tr("row_last", date=last) if last else "")))
        rows += [(_bid(st, "LINKNEW"), out.tr("row_create"), out.tr("row_create_d", code=shown)),
                 (_bid(st, "LINKUNK"), out.tr("row_dont_know"), out.tr("row_dont_know_d"))]
        out.rows(out.tr("link_choose", code=shown), rows)
    else:
        out.buttons(out.tr("link_none", code=shown), [(_bid(st, "LINKNEW"), out.tr("btn_create")),
                                                      (_bid(st, "FIXCODE"), out.tr("btn_fix_code")),
                                                      (_bid(st, "LINKUNK"), out.tr("btn_dont_know"))])
    save_state(mw, st)


def _link(db: Session, mw: Midwife, rec: Record, patient: Patient, st: dict, out: Out) -> None:
    actor = f"midwife:{mw.id}"
    rec.patient_id, rec.link_pending = patient.id, False
    dup = find_duplicate(db, rec, patient.id)
    if dup is not None:
        transition(db, rec, RecordStatus.DOUBLON_SUSPECT, actor, f"ressemble au dossier {dup.id[:8]}")
        st.update(mode=DOUBLON, dup_id=dup.id)
        _bump(st)
        d = date_reference(dup) or "?"
        out.buttons(out.tr("duplicate", date=d, code=patient.code),
                    [(_bid(st, "DUPUPD"), out.tr("btn_update")), (_bid(st, "DUPNEW"), out.tr("btn_new_visit")),
                     (_bid(st, "DUPCANCEL"), out.tr("btn_cancel"))])
        save_state(mw, st)
        return
    _register(db, mw, rec, patient, st, out)


def _register(db: Session, mw: Midwife, rec: Record, patient: Patient, st: dict, out: Out) -> None:
    actor = f"midwife:{mw.id}"
    transition(db, rec, RecordStatus.PATIENTE_LIEE, actor, f"patiente code {patient.code}")
    transition(db, rec, RecordStatus.ENREGISTRE, actor)
    out.text(out.tr("linked", rid=rec.id[:8], code=patient.code))
    _start_next(db, mw, st, out)


def _merge_into(db: Session, mw: Midwife, rec: Record, dup: Record, st: dict, out: Out) -> None:
    """« Mettre à jour » : les valeurs confirmées deviennent de nouvelles versions du dossier existant."""
    for k, ef in current_fields(rec).items():
        if ef.source == FieldSource.SAGE_FEMME and ef.status in (FieldStatus.CONNU, FieldStatus.NON_FOURNI,
                                                                  FieldStatus.NON_APPLICABLE, FieldStatus.ILLISIBLE):
            set_field(db, dup, k, _value(ef), ef.status, FieldSource.SAGE_FEMME, 1.0, ef.raw_text)
    transition(db, rec, RecordStatus.ANNULE, f"midwife:{mw.id}", f"fusionné dans le dossier {dup.id[:8]}")
    out.text(out.tr("dup_updated", date=date_reference(dup) or "?"))
    _start_next(db, mw, st, out)


# ------------------------------------------------------------------ point d'entrée
def handle_text(db: Session, mw: Midwife, text: str) -> bool:
    """Traite une réponse (bouton, liste ou texte libre). Renvoie False si rien à voir avec la conversation."""
    st, out = load_state(mw), Out(db, mw)
    raw = clean_text(text)
    cmd = raw.upper()
    parts = raw.split("|")
    if len(parts) == 4 and parts[3].isdigit():
        return _handle_button(db, mw, st, out, *parts)

    if cmd in ("EN", "FR"):
        mw.language = cmd.lower()
        out = Out(db, mw)
        out.text(out.tr("lang_set"))
        return True
    if cmd in CMD_HELP:
        out.text(out.tr("help"))
        return True
    if cmd in CMD_PAUSE:
        st["paused"] = True
        save_state(mw, st)
        out.text(out.tr("paused"))
        return True
    if cmd in CMD_RESUME:
        st["paused"] = False
        _reask(db, mw, st, out)
        return True

    rec = db.get(Record, st.get("record_id") or "")
    mode = st["mode"]
    if mode == CORRECTION and rec is not None:
        _correction_answer(db, mw, rec, st, out, raw)
        return True
    if mode == MANUEL and rec is not None:
        _manual_answer(db, mw, rec, st, out, raw)
        return True
    if mode == CODE and rec is not None:
        start_linking(db, mw, rec, st, out, code=raw)
        return True
    m = re.fullmatch(r"(?:CORRIGER|CORRECT)\s+(\d+)", cmd)
    if m and mode == FIN and rec is not None:
        keys = st.get("view") or _others(rec, st)
        i = int(m.group(1)) - 1
        if 0 <= i < len(keys):
            _ask_correction(mw, st, out, keys[i], back=FIN)
            return True
    if cmd in CMD_OK and rec is not None:
        if mode == REVISION:
            key = st["queue"][st["idx"]]
            return _handle_button(db, mw, st, out, "CONF", rec.id[:8], key, str(st["version"]))
        if mode == FIN:
            return _handle_button(db, mw, st, out, "ALLOK", rec.id[:8], "", str(st["version"]))
    if mode == IDLE and _pending_records(db, mw) and cmd in CMD_OK:
        _start_next(db, mw, st, out)
        return True
    return False


def _reask(db: Session, mw: Midwife, st: dict, out: Out) -> None:
    rec = db.get(Record, st.get("record_id") or "")
    mode = st["mode"]
    if rec is None or mode == IDLE:
        if _pending_records(db, mw):
            _start_next(db, mw, st, out)
        else:
            out.text(out.tr("nothing"))
        return
    if mode == RESUME:
        _summary(db, mw, rec, st, out)
    elif mode == REVISION:
        _ask_field(db, mw, rec, st, out)
    elif mode == CORRECTION:
        _ask_correction(mw, st, out, st["pending"], st.get("back", REVISION))
    elif mode == FIN:
        _final(db, mw, rec, st, out)
    elif mode == MANUEL:
        if st.get("idx", -1) < 0:
            _manual_intro(db, mw, rec, st, out)
        else:
            _manual_ask(db, mw, rec, st, out)
    elif mode in (LIAISON, CODE):
        start_linking(db, mw, rec, st, out)
    elif mode == DOUBLON:
        dup = db.get(Record, st.get("dup_id") or "")
        patient = db.get(Patient, rec.patient_id) if rec.patient_id else None
        _bump(st)
        out.buttons(out.tr("duplicate", date=date_reference(dup) if dup else "?", code=patient.code if patient else "?"),
                    [(_bid(st, "DUPUPD"), out.tr("btn_update")), (_bid(st, "DUPNEW"), out.tr("btn_new_visit")),
                     (_bid(st, "DUPCANCEL"), out.tr("btn_cancel"))])
        save_state(mw, st)
    elif mode == PHOTO:
        page = next((p for p in rec.pages if p.page_number == st.get("photo_page")), None)
        out.text(out.tr("retake_ask", n=st.get("photo_page") or 1, ptype=_page_type_label(page)))


def _correction_answer(db: Session, mw: Midwife, rec: Record, st: dict, out: Out, text: str) -> None:
    key = st["pending"]
    f = T.fields[key]
    ans = parse_answer(f, text)
    if ans is None:
        out.text(out.tr("invalid", text=text[:40], hint=format_hint(f, out.lang)))
        return
    kind, value = ans
    status = {"vide": FieldStatus.NON_FOURNI, "illisible": FieldStatus.ILLISIBLE}.get(kind, FieldStatus.CONNU)
    set_field(db, rec, key, value, status, FieldSource.SAGE_FEMME, 1.0, text[:200])
    back = st.pop("back", REVISION)
    st.pop("pending", None)
    if back == FIN:
        _view(db, mw, rec, st, out, 0) if st.get("view") else _final(db, mw, rec, st, out)
    else:
        _next_question(db, mw, rec, st, out)


def _handle_button(db: Session, mw: Midwife, st: dict, out: Out, action: str, rid: str, key: str,
                   version: str) -> bool:
    rec = db.get(Record, st.get("record_id") or "")
    if rec is None or rid != rec.id[:8] or int(version) != st.get("version"):
        out.text(out.tr("stale"))
        return True
    st["paused"] = False
    if action == "LATER":
        st["paused"] = True
        save_state(mw, st)
        out.text(out.tr("paused"))
    elif action == "REV":
        st["idx"] = 0
        _ask_field(db, mw, rec, st, out)
    elif action == "PHOTO":
        _ask_photo(db, mw, rec, st, out, key)
    elif action == "PHOTOPAGE":
        page = next((p for p in rec.pages if str(p.page_number) == key), None)
        st.update(mode=PHOTO, photo_page=page.page_number if page else None)
        out.text(out.tr("retake_ask", n=key, ptype=_page_type_label(page)))
        save_state(mw, st)
    elif action in ("CONF", "ILL", "VIDE", "CAND"):
        k, _, idx = key.partition("#")
        ef = current_fields(rec).get(k)
        if ef is None:
            out.text(out.tr("stale"))
            return True
        if action == "CONF":
            set_field(db, rec, k, _value(ef), FieldStatus.CONNU, FieldSource.SAGE_FEMME, 1.0, ef.raw_text)
        elif action == "ILL":
            set_field(db, rec, k, None, FieldStatus.ILLISIBLE, FieldSource.SAGE_FEMME, 1.0, ef.raw_text)
        elif action == "VIDE":
            set_field(db, rec, k, None, FieldStatus.NON_FOURNI, FieldSource.SAGE_FEMME, 1.0, ef.raw_text)
        else:
            cands = _details(ef).get("candidates") or []
            if not idx.isdigit() or int(idx) >= len(cands):
                out.text(out.tr("stale"))
                return True
            set_field(db, rec, k, cands[int(idx)], FieldStatus.CONNU, FieldSource.SAGE_FEMME, 1.0, ef.raw_text)
        _next_question(db, mw, rec, st, out)
    elif action == "CORR":
        _ask_correction(mw, st, out, key, back=REVISION)
    elif action == "VIEW":
        _view(db, mw, rec, st, out, int(key or 0))
    elif action == "ALLOK":
        _confirm_all(db, mw, rec, st, out)
    elif action == "MAN":
        st["idx"] = 0
        _manual_ask(db, mw, rec, st, out)
    elif action == "LINKP":
        cands = st.get("cands") or []
        p = db.get(Patient, cands[int(key)]) if key.isdigit() and int(key) < len(cands) else None
        if p is None or p.midwife_id != mw.id:
            out.text(out.tr("stale"))
            return True
        _link(db, mw, rec, p, st, out)
    elif action == "LINKNEW":
        p = Patient(midwife_id=mw.id, code=norm_code(st.get("code") or "") or rec.id[:8].upper())
        db.add(p)
        db.flush()
        _link(db, mw, rec, p, st, out)
    elif action == "LINKUNK":
        rec.link_pending = True
        out.text(out.tr("link_pending"))
        _start_next(db, mw, st, out)
    elif action == "FIXCODE":
        st.update(mode=CODE, code=None)
        out.text(out.tr("ask_code"))
        save_state(mw, st)
    elif action in ("DUPUPD", "DUPNEW", "DUPCANCEL"):
        dup = db.get(Record, st.get("dup_id") or "")
        patient = db.get(Patient, rec.patient_id) if rec.patient_id else None
        if action == "DUPUPD" and dup is not None:
            _merge_into(db, mw, rec, dup, st, out)
        elif action == "DUPNEW" and patient is not None:
            _register(db, mw, rec, patient, st, out)
        else:
            transition(db, rec, RecordStatus.ANNULE, f"midwife:{mw.id}", "doublon annulé")
            out.text(out.tr("cancelled", rid=rec.id[:8]))
            _start_next(db, mw, st, out)
    else:
        out.text(out.tr("stale"))
    return True
