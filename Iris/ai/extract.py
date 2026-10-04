"""Pipeline d'extraction : images (octets en mémoire) -> champs structurés.

    python -m ai.extract img1.jpg [img2.jpg ...] --out res.json [--main qwen2.5vl:3b --verify qwen2.5vl:7b]

Pour chaque page : prétraitement (qualité, redressement, bandes) -> type de page
-> lecture de CHAQUE bande avec uniquement les champs du type de page -> fusion
des lectures (accord / désaccord entre bandes qui se recouvrent) -> 2e avis
sur les champs critiques ou douteux -> validations (sur toutes les pages) ->
confiance + statut -> filtre de confidentialité.
API : `extract_pages(images) -> list[PageResult]` (aucune image écrite sur disque).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai import confidence as C
from ai.classify import UNKNOWN, classify
from ai.ollama_client import OllamaClient, OllamaError, OllamaUnavailable
from ai.preprocess import ImageError, load_image, prepare
from ai.prompts import BOOL_OPTION, ETATS, PageSpec, build_prompt, build_schema, output_budget, page_spec
from ai.validate import validate
from app.registry_schema import sanitize_extraction
from app.templates import get_template
from app.templates.base import FieldDef, norm_label
from app.templates.normalize import (CROSSED_MARK, ILLEGIBLE_MARK, Interpretation, clean_text, interpret, is_dash,
                                     values_equal)

log = logging.getLogger("iris.ai")
T = get_template()

# ------------------------------------------------------------------ confidentialité
PHONE_RE = re.compile(r"(?:\+?212[\s.-]?|\b0)[5-7](?:[\s.-]?\d){8}\b")
CIN_RE = re.compile(r"\b[A-Z]{1,2}\s?\d{4,7}\b")


def contains_identifier(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    return bool(PHONE_RE.search(text) or CIN_RE.search(text))


# ------------------------------------------------------------------ structures
@dataclass
class Reading:
    key: str
    raw: Any                       # texte (champ, cellule) ou liste de codes (cases)
    etat: str
    conf: float | None
    band: int | None
    source: str = "main"           # "main" | "verify"


@dataclass
class FieldState:
    f: FieldDef
    readings: list[Reading] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    interp: Interpretation | None = None
    chosen: Reading | None = None
    evidence: C.Evidence | None = None
    candidates: list = field(default_factory=list)


@dataclass
class PageResult:
    index: int
    page_type: str
    classification: str = ""
    quality: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    duration_s: float = 0.0
    fields: dict[str, dict] = field(default_factory=dict)
    error: str | None = None
    deskew_deg: float = 0.0
    band_ranges: list = field(default_factory=list)     # (y0, y1) relatifs de chaque bande
    removed_identifiers: int = 0
    removed_keys: list = field(default_factory=list)     # clés rejetées (identifiants), jamais les valeurs

    def to_dict(self, image: str | None = None) -> dict:
        d = {"image": image or f"page_{self.index + 1}", "page": self.index + 1, "page_type": self.page_type,
             "classification": self.classification, "quality": self.quality, "models": self.models,
             "duration_s": round(self.duration_s, 2), "deskew_deg": self.deskew_deg, "fields": self.fields}
        if self.error:
            d["error"] = self.error
        if self.removed_identifiers:
            d["identifiants_retires"] = self.removed_identifiers
        return d


# ------------------------------------------------------------------ lecture des réponses
def _printed_labels(page_type: str) -> set[str]:
    """Tous les libellés imprimés de la page : une « valeur » égale à l'un d'eux est une hallucination."""
    out = set()
    for sec in T.page_type(page_type).sections:
        for f in T.section(sec).all_fields():
            out.update(norm_label(l) for l in f.labels)
            if not f.ecrit:                     # options d'un choix écrit à la main : pas imprimées
                out.update(norm_label(l) for c in f.choices for l in c.labels)
        for tb in T.section(sec).tables:
            out.update(norm_label(l) for _, l in tb.cols)
            out.add(norm_label(tb.label_fr))
    out.discard("")
    return out


def _cell_etat(txt: str) -> str:
    t = clean_text(txt)
    if t == CROSSED_MARK:
        return "BARRE"
    if t == ILLEGIBLE_MARK:
        return "ILLISIBLE"
    if not t:
        return "VIDE"
    if is_dash(t):
        return "TIRET"
    return "LISIBLE"


def _conf(v: Any) -> float | None:
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    return c / 100 if c > 1 else c


def _text_reading(key: str, v: Any, conf: float | None, band: int | None, source: str) -> Reading | None:
    """Champ « compact » (texte avec codes) ou objet {raw, etat, confiance} (réponse sans format)."""
    if isinstance(v, dict):
        raw = v.get("raw", v.get("valeur"))
        etat = str(v.get("etat") or "").upper()
        conf = _conf(v.get("confiance")) if v.get("confiance") is not None else conf
    else:
        raw, etat = v, ""
    if raw is None and etat not in ETATS:
        return None
    if etat not in ETATS:
        etat = _cell_etat("" if raw is None else str(raw))
    if etat == "ABSENT_DE_CETTE_ZONE":
        return None
    if etat == "LISIBLE" and not clean_text(raw):
        etat = "VIDE"
    return Reading(key, raw, etat, conf, band, source)


def parse_response(spec: PageSpec, data: dict, band: int | None, source: str = "main") -> list[Reading]:
    """Réponse du modèle -> lectures. Toute clé hors du type de page est ignorée (clé inventée)."""
    out: list[Reading] = []
    conf = _conf(data.get("confiance"))
    champs = dict(data.get("champs") or {})
    champs.update({k: v for k, v in data.items() if k in spec.simple})       # réponse « à plat » (sans format)
    for k, v in champs.items():
        if k in spec.simple and (r := _text_reading(k, v, conf, band, source)):
            out.append(r)
    for lk, lv in (data.get("lignes") or {}).items():
        line = spec.lines.get(lk)
        if not line or not isinstance(lv, dict):
            continue
        cells = lv.get("valeurs") if isinstance(lv.get("valeurs"), dict) else lv
        for col, txt in cells.items():
            if col in line.cells and txt is not None and not isinstance(txt, (dict, list)):
                out.append(Reading(line.cells[col], str(txt), _cell_etat(str(txt)), conf, band, source))
    # cases cochées : liste plate de jetons « clé » / « clé=code »
    checked: dict[str, list[str]] = {}
    for tok in data.get("cochees") or []:
        if not isinstance(tok, str):
            continue
        key, _, code = tok.partition("=")
        f = spec.checks.get(key)
        if f is None or (f.type == "bool") != (code == "") or (code and code not in f.choice_codes):
            continue
        checked.setdefault(key, []).append(code or BOOL_OPTION)
    for key, codes in checked.items():
        out.append(Reading(key, sorted(set(codes)), "LISIBLE", conf, band, source))
    return out


# ------------------------------------------------------------------ fusion
def _interp(f: FieldDef, r: Reading) -> Interpretation:
    if f.is_checkbox:
        codes = r.raw if isinstance(r.raw, list) else []
        if f.type == "bool":
            return Interpretation(BOOL_OPTION in codes, None)
        if f.type == "checkbox_group":
            return Interpretation(sorted(codes), None)
        if not codes:
            return Interpretation(None, "NON_FOURNI")
        if len(codes) > 1:
            return Interpretation(codes[0], None, ["plusieurs_cases_cochees"])
        return Interpretation(codes[0], None)
    return interpret(f, r.raw, r.etat)


def _same(f: FieldDef, a: Interpretation, b: Interpretation) -> bool:
    if a.status or b.status:
        return a.status == b.status
    if f.type == "bool" or f.type == "checkbox_group":
        return a.value == b.value
    return values_equal(f, a.value, b.value)


def _merge_checks(st: FieldState, main: list[Reading]) -> None:
    """Cases : union des options vues cochées ; accord = nb de bandes qui voient la même chose."""
    codes = sorted({c for r in main for c in (r.raw or [])})
    r0 = max(main, key=lambda r: r.conf or 0)
    st.chosen = Reading(r0.key, codes, "LISIBLE", r0.conf, r0.band, "main")
    st.interp = _interp(st.f, st.chosen)
    st.flags += st.interp.flags
    agree = min(sum(c in (r.raw or []) for r in main) for c in codes) if codes else 1
    st.evidence = C.Evidence(declared=r0.conf, n_agree=agree)


def merge(st: FieldState) -> None:
    """Choisit la lecture retenue parmi les lectures principales (bandes)."""
    f = st.f
    main = [r for r in st.readings if r.source == "main"]
    if not main:
        return
    if f.is_checkbox:
        _merge_checks(st, main)
        return
    readable = [r for r in main if r.etat == "LISIBLE"]
    pool = readable or main                 # une bande coupée qui voit « VIDE » ne contredit pas une lecture
    groups: list[list[tuple[Reading, Interpretation]]] = []
    for r in pool:
        it = _interp(f, r)
        for g in groups:
            if _same(f, g[0][1], it):
                g.append((r, it))
                break
        else:
            groups.append([(r, it)])
    if not readable:
        # que des états visuels : le plus prudent l'emporte
        order = {"ILLISIBLE": 0, "BARRE": 1, "TIRET": 2, "VIDE": 3}
        groups.sort(key=lambda g: order.get(g[0][0].etat, 9))
    else:
        groups.sort(key=lambda g: (-len(g), -max((r.conf or 0) for r, _ in g)))
    best = groups[0]
    st.chosen, st.interp = max(best, key=lambda ri: ri[0].conf or 0)
    st.flags += st.interp.flags
    disagreement = bool(readable) and len(groups) > 1
    if disagreement:
        st.candidates = [g[0][1].value for g in groups]
    st.evidence = C.Evidence(declared=st.chosen.conf, n_agree=len(best), disagreement=disagreement)


def drop_impossible_readings(states: dict[str, FieldState], n_bands: int) -> None:
    """Un champ tient dans 1 ou 2 bandes (recouvrement), jamais dans toutes : s'il est « vu »
    dans TOUTES les bandes sans jamais être lisible (« #ILLISIBLE » / "" partout), le modèle
    répond pour un champ absent de la page -> on n'en garde rien."""
    if n_bands < 3:
        return
    for st in states.values():
        main = [r for r in st.readings if r.source == "main"]
        if (not st.f.is_checkbox and main and len({r.band for r in main}) >= n_bands
                and all(r.etat != "LISIBLE" for r in main)):
            st.readings = [r for r in st.readings if r.source != "main"]
            st.flags.append("absent_de_la_page")


def apply_verify(st: FieldState) -> None:
    ver = [r for r in st.readings if r.source == "verify"]
    if not ver or st.interp is None or st.evidence is None:
        return
    it = _interp(st.f, ver[0])
    agree = _same(st.f, st.interp, it)
    st.evidence.verified = agree
    if not agree:
        vals = st.candidates or [st.interp.value]
        if it.value is not None and all(not _same(st.f, Interpretation(v, None), it) for v in vals):
            vals.append(it.value)
        st.candidates = vals


# ------------------------------------------------------------------ pipeline
def add_checkbox_readings(states: dict[str, FieldState], results, bands, page_height_px: int) -> None:
    """Résultats de ai/checkboxes.py -> une lecture par champ case à cocher (drapeau `lecture_cv` :
    vision classique, pas d'IA ; incertaine -> confiance 0.4 -> A_REVISER)."""
    from ai.checkboxes import to_readings
    by_key = to_readings(results)
    ys = {}
    for r in results:
        ys.setdefault(r.key, (r.box_px[1] + r.box_px[3]) / 2)
    for key, (codes, conf, unsure) in by_key.items():
        if key not in T.stored_fields:
            continue
        st = states.setdefault(key, FieldState(T.fields[key]))
        st.readings = [rd for rd in st.readings if not st.f.is_checkbox]   # le VLM ne lit plus les cases
        st.flags.append("lecture_cv")
        if unsure:
            st.flags.append("case_incertaine")
            conf = min(conf, 0.4)
        elif not codes and T.fields[key].type == "enum":
            # choix unique sans AUCUNE case vue cochée : plus probablement une coche manquée (stylo
            # fin, cadre légèrement décalé) qu'un champ vide -> à confirmer, jamais « vide » affirmé
            st.flags.append("aucune_case_cochee")
            conf = min(conf, 0.5)
        y_rel = ys.get(key, 0) / max(1, page_height_px)
        band = next((b.index for b in bands if b.y0 <= y_rel <= b.y1), 0)
        st.readings.append(Reading(key, codes, "LISIBLE", conf, band))


def _needs_verify(st: FieldState, seuil: float) -> bool:
    if "lecture_cv" in st.flags:                       # case lue par vision classique : pas de 2e avis VLM
        return False
    if "hors_vocabulaire" in st.flags or ("lecture_ocr" in st.flags and st.f.type == "date"):
        return st.interp is not None and st.interp.status is None and st.chosen is not None
    if st.interp is None or st.interp.status or st.chosen is None or st.chosen.etat != "LISIBLE":
        return False
    prelim = C.score(st.evidence)
    return st.f.critique or st.f.is_checkbox or (0.4 <= prelim < seuil) or st.evidence.disagreement


def strip_printed_label(r: Reading, st: FieldState, labels: set[str]) -> Reading | None:
    """« Autres à préciser : #ILLISIBLE » -> « #ILLISIBLE » ; une valeur qui n'est QUE un libellé
    imprimé (« DDR = En milieu surveillé ») est rejetée (drapeau `libelle_recopie`)."""
    raw = clean_text(r.raw)
    if "#ILLISIBLE" in raw.upper():
        return Reading(r.key, ILLEGIBLE_MARK, "ILLISIBLE", r.conf, r.band, r.source)
    if r.etat != "LISIBLE":
        return r
    if norm_label(raw) in labels:
        st.flags.append("libelle_recopie")
        return None
    for lab in sorted({clean_text(l) for l in st.f.labels}, key=len, reverse=True):
        n = norm_label(lab)
        if n and (norm_label(raw).startswith(n + " ") or norm_label(raw) == n):
            rest = re.sub(r"^[\s:.\-…]+", "", raw[len(lab):] if raw.lower().startswith(lab.lower())
                          else raw.split(":", 1)[-1])
            st.flags.append("libelle_retire")
            return Reading(r.key, rest, _cell_etat(rest), r.conf, r.band, r.source)
    return r


def _read_page(client, spec: PageSpec, bands, model: str, use_cache: bool, labels: set[str],
               states: dict[str, FieldState]) -> list[str]:
    errors, n_calls = [], 0
    for b in bands:
        for part in spec.chunks():
            n_calls += 1
            try:
                res = client.generate(model, build_prompt(part, b.index, len(bands)), [b.jpeg], build_schema(part),
                                      use_cache=use_cache, num_predict=output_budget(part))
            except OllamaError as e:
                errors.append(f"bande {b.index + 1} : {e}")
                continue
            _collect(part, res.data, b.index, labels, states)
    return errors if len(errors) == n_calls else []


def _collect(spec: PageSpec, data: dict, band: int, labels: set[str], states: dict[str, FieldState]) -> None:
    for r in parse_response(spec, data, band):
        st = states.setdefault(r.key, FieldState(T.fields[r.key]))
        if not st.f.is_checkbox and isinstance(r.raw, str):
            r = strip_printed_label(r, st, labels)
            if r is None:
                continue
        st.readings.append(r)


def _second_opinion(client, page_type: str, bands, model: str, use_cache: bool,
                    states: dict[str, FieldState], seuil: float, critical_only: bool = False) -> None:
    by_band: dict[int, set[str]] = {}
    for k, st in states.items():
        if critical_only and not (st.f.critique or st.f.type == "date" or "hors_vocabulaire" in st.flags):
            continue                                   # mode OCR : 2e avis sur critiques, dates, texte inconnu
        if _needs_verify(st, seuil) and st.chosen.band is not None:
            by_band.setdefault(st.chosen.band, set()).add(k)
    for band_idx, keys in sorted(by_band.items()):
        full = page_spec(page_type, only=keys)
        b = bands[band_idx]
        for spec in ([] if full.is_empty() else full.chunks()):
            try:                               # autre rendu de la bande : lecture moins corrélée
                res = client.generate(model, build_prompt(spec, b.index, len(bands)), [b.alt_jpeg or b.jpeg],
                                      build_schema(spec), use_cache=use_cache, num_predict=output_budget(spec))
            except OllamaError as e:
                log.warning("2e avis impossible (bande %d) : %s", band_idx + 1, e)
                continue
            seen = set()
            for r in parse_response(spec, res.data, b.index, source="verify"):
                if r.key in keys:
                    states[r.key].readings.append(r)
                    seen.add(r.key)
            for k in (keys & set(spec.checks)) - seen:   # case que le 2e avis ne voit PAS cochée : désaccord
                states[k].readings.append(Reading(k, [], "LISIBLE", _conf(res.data.get("confiance")),
                                                  b.index, "verify"))
    for st in states.values():
        apply_verify(st)


def _finalize(pages: list[tuple[PageResult, dict[str, FieldState]]], seuil: float) -> None:
    values = {}
    for _, states in pages:
        for k, st in states.items():
            if st.interp is not None and st.interp.status is None and k not in values:
                values[k] = st.interp.value
    vflags = validate(values)
    from ai.validate import coherent_term_dates
    coherent = coherent_term_dates(values)
    for res, states in pages:
        out = {}
        for k, st in states.items():
            if st.interp is None:
                continue
            if k in vflags:
                st.flags += vflags[k]
                st.evidence.validation_failed = True
            if "libelle_recopie" in st.flags or st.interp.flags:
                st.evidence.validation_failed = True
            conf = C.score(st.evidence)
            if "hors_vocabulaire" in st.flags and st.evidence.verified is not True:
                conf = min(conf, 0.6)                  # texte libre inconnu, non confirmé par le 2e avis
            vlm_box = st.f.is_checkbox and "lecture_cv" not in st.flags
            if vlm_box:
                # mesuré : le VLM invente des cases cochées, même confirmées par un 2e avis du même
                # modèle -> une case lue par le VLM est toujours à confirmer par la sage-femme
                # (une case lue par vision classique — taux d'encre, mode OCR — n'est pas concernée)
                conf = min(conf, C.CHECKBOX_CAP)
            # mode OCR : une date n'est jamais CONNU sur une seule lecture (chiffre manquant/mal lu)
            ocr_date = "lecture_ocr" in st.flags and st.f.type == "date"
            critical = st.f.critique or vlm_box or ocr_date
            status = C.status(st.interp.status, conf, seuil, critical, st.evidence)
            if "crayon_gris" in st.flags and status == "CONNU":
                status = "A_REVISER"                    # date au crayon : rappel ? toujours à confirmer
            if (k in coherent and status == "A_REVISER" and not st.interp.flags and k not in vflags
                    and not st.evidence.disagreement and st.evidence.verified is not False):
                conf, status = max(conf, 0.9), "CONNU"  # DDR/DPA/DDT confirmées entre elles
                st.flags.append("dates_terme_coherentes")
            if status == "NON_FOURNI" and {"case_incertaine", "aucune_case_cochee"} & set(st.flags):
                status = "A_REVISER"                    # « rien coché » n'est pas une certitude
            if vlm_box and status == "CONNU":
                status = "A_REVISER"                    # quel que soit le seuil
            raw = st.chosen.raw if isinstance(st.chosen.raw, str) else None
            out[k] = {"value": st.interp.value, "raw_text": raw, "status": status, "confidence": conf,
                      "candidates": st.candidates, "flags": sorted(set(st.flags)), "page": res.index + 1,
                      "lectures": C.readings_count(st.evidence)}
            if st.chosen.band is not None and st.chosen.band < len(res.band_ranges):
                out[k]["zone"] = [round(v, 4) for v in res.band_ranges[st.chosen.band]]
        res.fields, res.removed_identifiers, res.removed_keys = privacy_filter(out)


def privacy_filter(fields: dict[str, dict]) -> tuple[dict[str, dict], int, list[str]]:
    """Liste blanche du schéma + suppression de tout texte ressemblant à un téléphone ou une CIN.
    -> (champs gardés, nb de retraits, clés rejetées par la liste blanche)."""
    kept, rejected = sanitize_extraction(fields)
    removed = len(rejected)
    for k in list(kept):
        d = kept[k]
        if contains_identifier(d.get("value")) or any(contains_identifier(c) for c in d.get("candidates") or []):
            del kept[k]
            removed += 1
            continue
        if contains_identifier(d.get("raw_text")):
            d["raw_text"] = None
            d["flags"] = sorted(set(d["flags"]) | {"identifiant_retire"})
            removed += 1
    return kept, removed, sorted(rejected)


def extract_pages(images: list[bytes], *, client: OllamaClient | None = None, main_model: str | None = None,
                  verify_model: str | None = None, seuil: float | None = None, use_cache: bool = False,
                  page_types: list[str | None] | None = None) -> list[PageResult]:
    """Lit des pages (octets en mémoire). Lève OllamaUnavailable si le serveur ne répond pas."""
    from app.config import get_settings
    s = get_settings()
    client = client or OllamaClient(s.ollama_url, timeout=s.ai_timeout_seconds, num_ctx=s.ai_num_ctx, num_predict=s.ai_num_predict)
    main_model = main_model or s.ai_model_main
    verify_model = s.ai_model_verify if verify_model is None else verify_model
    seuil = s.ai_seuil_connu if seuil is None else seuil

    pages: list[tuple[PageResult, dict[str, FieldState]]] = []
    for i, data in enumerate(images):
        t0 = time.monotonic()
        res = PageResult(i, UNKNOWN, models={"main": main_model, "verify": verify_model or None})
        states: dict[str, FieldState] = {}
        pages.append((res, states))
        try:
            prep = prepare(data)
        except ImageError as e:
            res.error, res.duration_s = str(e), time.monotonic() - t0
            continue
        res.quality, res.deskew_deg = prep.quality, prep.deskew_deg
        res.band_ranges = [(b.y0, b.y1) for b in prep.bands]
        hint = page_types[i] if page_types and i < len(page_types) else None
        if hint:
            res.page_type, res.classification = hint, "impose"
        else:
            try:
                res.page_type, res.classification = classify(client, main_model, prep.thumb, T, use_cache)
            except OllamaError as e:             # ex. 500 répétés : la page est signalée, les autres continuent
                res.error, res.duration_s = f"classification impossible : {e}", time.monotonic() - t0
                continue
        if res.page_type == UNKNOWN:
            res.error = "type de page non reconnu"
            res.duration_s = time.monotonic() - t0
            continue
        spec = page_spec(res.page_type)
        if s.ai_cases_cv and spec.checks:              # cases : vision classique (ai/checkboxes.py)
            try:
                from ai.checkboxes import read_checkboxes
                img = load_image(data)
                boxes, method = read_checkboxes(img, res.page_type)
                add_checkbox_readings(states, boxes, prep.bands, img.size[1])
                res.models["cases"] = f"opencv:{method}"
                spec.checks = {}                       # le VLM ne lit plus que le texte
            except Exception as e:  # noqa: BLE001  (OCR des libellés indisponible : le VLM garde les cases)
                log.warning("Cases par vision classique impossibles : %s", e)
        errors = _read_page(client, spec, prep.bands, main_model, use_cache, _printed_labels(res.page_type), states)
        if errors:                              # toutes les requêtes ont échoué
            res.error = "; ".join(errors)
        drop_impossible_readings(states, len(prep.bands))
        for st in states.values():
            merge(st)
        if verify_model:
            _second_opinion(client, res.page_type, prep.bands, verify_model, use_cache, states, seuil)
        res.duration_s = time.monotonic() - t0
    _finalize(pages, seuil)
    return [r for r, _ in pages]


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings
    s = get_settings()
    ap = argparse.ArgumentParser(description="Extraction locale (Ollama) d'images de registre")
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--main", default=s.ai_model_main)
    ap.add_argument("--verify", default=s.ai_model_verify, help="modèle du 2e avis ('' = désactivé)")
    ap.add_argument("--seuil", type=float, default=s.ai_seuil_connu)
    ap.add_argument("--type", help="impose le type de page (sinon classification)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from eval.common import EVAL_DIR
    client = OllamaClient(s.ollama_url, timeout=s.ai_timeout_seconds, num_ctx=s.ai_num_ctx, num_predict=s.ai_num_predict,
                          cache_dir=None if args.no_cache else EVAL_DIR / "cache")
    try:
        results = extract_pages([p.read_bytes() for p in args.images], client=client, main_model=args.main,
                                verify_model=args.verify, seuil=args.seuil, use_cache=not args.no_cache,
                                page_types=[args.type] * len(args.images) if args.type else None)
    except OllamaUnavailable as e:
        print(f"Ollama indisponible : {e}", file=sys.stderr)
        return 3
    docs = [r.to_dict(p.name) for r, p in zip(results, args.images)]
    out = json.dumps(docs if len(docs) > 1 else docs[0], ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
    for d in docs:
        st = {}
        for v in d["fields"].values():
            st[v["status"]] = st.get(v["status"], 0) + 1
        print(f"{d['image']} : {d['page_type']} ({d['classification']}), {d['duration_s']} s, statuts {st}"
              + (f", ERREUR {d['error']}" if d.get("error") else ""))
    if not args.out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
