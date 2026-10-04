"""Vérité terrain des 80 pages spécimen -> eval/ground_truth/specimen_pNN.json.

Dans le PDF, l'écriture « manuscrite » est du vrai texte (polices Caveat,
NanumPen, Gaegu...) et l'imprimé est en Helvetica ; les coches sont des
tracés vectoriels colorés posés sur des cases 8x8. On rattache donc :
- chaque mot manuscrit au champ du template dont le libellé imprimé est le
  plus proche à gauche (sinon au-dessus) ; dans un tableau, via l'en-tête de
  ligne (colonne de gauche) et l'en-tête de colonne ;
- chaque case cochée au libellé imprimé à sa droite (sinon à sa gauche),
  puis au champ dont ce libellé est une option (ancre = libellé du groupe
  le plus proche au-dessus).
Les valeurs des champs identifiants vont dans `_identifiants` (jamais dans
`fields`) : l'évaluateur vérifie que l'IA ne les sort jamais.

    python -m scripts.build_ground_truth            # + rapport par type de page
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pdfplumber

from app.templates.base import FieldDef, TableDef, norm_label
from app.templates.carnet_maroc import SPECIMEN_PAGE_ORDER, TEMPLATE
from app.templates.normalize import clean_text, normalize_value
from eval.common import GT_DIR, PDF_PATH, gt_name_for, load_manifest, write_json
from eval.pdf_layout import PageLayout, Stroke, Word, make_word, page_layout, text_lines

LINE_TOL = 6.0          # même ligne : écart de ligne de base (pt)
ROW_TOL = 14.0          # rattachement à une ligne de tableau
ABOVE_MAX = 30.0        # libellé au-dessus de la valeur


@dataclass
class Assign:
    key: str
    words: list[Word] = field(default_factory=list)


def _same_line(a_y: float, b_y: float, tol: float = LINE_TOL) -> bool:
    return abs(a_y - b_y) <= tol


def _label_matches(word_text: str, labels) -> bool:
    n = norm_label(word_text)
    return any(n == norm_label(l) for l in labels)


class PageGT:
    def __init__(self, layout: PageLayout, page_type: str):
        self.L = layout
        self.page_type = page_type
        self.sections = TEMPLATE.page_type(page_type).sections
        self.fields: dict[str, FieldDef] = TEMPLATE.section_fields(self.sections)
        self.free = {k: f for k, f in self.fields.items() if f.table is None}
        self.prints = layout.print_words
        self.present: set[str] = set()        # champs dont le libellé est imprimé sur la page

    # ---------------------------------------------------------- libellés
    def find_print(self, labels) -> list[Word]:
        return [w for w in self.prints if _label_matches(w.text, labels)]

    def _ctx_distance(self, f: FieldDef, y: float) -> float:
        if not f.context:
            return 1e6
        ds = [y - w.y for w in self.find_print([f.context]) if y - w.y >= -LINE_TOL]
        return min(ds) if ds else 1e6

    def resolve(self, cands: list[tuple[str, FieldDef]], y: float) -> tuple[str, FieldDef] | None:
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        return min(cands, key=lambda kf: self._ctx_distance(kf[1], y))

    def field_for_label(self, w: Word, y: float) -> tuple[str, FieldDef] | None:
        cands = [(k, f) for k, f in self.free.items()
                 if f.type not in ("bool", "checkbox_group") and _label_matches(w.text, f.labels)]
        return self.resolve(cands, y)

    # ---------------------------------------------------------- tableaux
    def table_grids(self):
        """Repère les en-têtes de colonnes de chaque tableau ; renvoie une liste de grilles."""
        grids = []
        for sec in self.sections:
            for t in TEMPLATE.section(sec).tables:
                g = self._grid(sec, t)
                if g:
                    grids.append(g)
        # bornes droites : prochain en-tête de colonne d'un autre tableau sur la même ligne
        for g in grids:
            others = [c["x0"] for h in grids if h is not g and _same_line(h["y"], g["y"]) for c in h["cols"]
                      if c["x0"] > g["cols"][-1]["x0"]]
            g["right"] = min(others) - 6 if others else self.L.width
        return grids

    def _grid(self, sec: str, t: TableDef):
        for line in text_lines(self.prints, 3.0):
            cols, i = [], 0
            for w in line:
                if i >= len(t.cols):
                    break
                code, label = t.cols[i]
                if _label_matches(w.text, (label, *t.col_aliases.get(code, ()))):
                    cols.append({"code": code, "x0": w.x0})
                    i += 1
            if len(cols) == len(t.cols):
                y = line[0].y
                rows = []
                for r in t.rows:
                    hits = [w for w in self.find_print(r.labels) if w.y > y and w.x0 < cols[0]["x0"] - 5]
                    for h in hits:          # toutes les occurrences : la plus proche gagne
                        rows.append({"code": r.key, "y": h.y})
                if t.rows:
                    bottom = max((r["y"] for r in rows), default=y) + ROW_TOL
                else:
                    below = [w for w in self.prints if w.y > y + 4 and w.x1 > cols[0]["x0"]]
                    bottom = min((w.y for w in below), default=self.L.height) - 4
                return {"section": sec, "table": t, "y": y, "cols": cols, "rows": rows,
                        "left": cols[0]["x0"] - 8, "bottom": bottom}
        return None

    def cell_key(self, g, w: Word) -> str | None:
        if not (g["y"] + 3 < w.y < g["bottom"] and g["left"] <= w.x0 < g["right"]):
            return None
        cols = [c for c in g["cols"] if c["x0"] <= w.x0 + 6]
        if not cols:
            return None
        col = max(cols, key=lambda c: c["x0"])["code"]
        t: TableDef = g["table"]
        prefix = f"{g['section']}." + (f"{t.key}." if t.key else "")
        if not t.rows:
            return prefix + col
        near = [r for r in g["rows"] if abs(r["y"] - w.y) <= ROW_TOL]
        if not near:
            return None
        row = min(near, key=lambda r: abs(r["y"] - w.y))["code"]
        return prefix + (f"{col}.{row}" if t.instance == "col" else f"{row}.{col}")

    # ---------------------------------------------------------- cases à cocher
    def checkboxes(self):
        squares = [s for s in self.L.strokes
                   if 6 < s.x1 - s.x0 < 10 and 6 < s.bottom - s.top < 10 and len(s.pts) >= 4]
        if not squares:
            return [], []
        form_color = Counter(str(s.color) for s in squares).most_common(1)[0][0]
        boxes = [s for s in squares if str(s.color) == form_color]
        ink = [s for s in self.L.strokes if str(s.color) != form_color]
        out, unmatched = [], []
        for b in boxes:
            cy = (b.top + b.bottom) / 2
            marked = any(s.x0 < b.x1 + 2 and s.x1 > b.x0 - 2 and s.top < b.bottom + 2 and s.bottom > b.top - 2
                         for s in ink)
            label = self._box_label(b, cy)
            hit = self._box_field(label, cy) if label else None
            if hit is None:
                unmatched.append({"label": label.text if label else None, "x": round(b.x0), "y": round(cy),
                                  "coche": marked})
                continue
            out.append((hit[0], hit[1], hit[2], marked))
        return out, unmatched

    def _box_label(self, b: Stroke, cy: float) -> Word | None:
        right = [w for w in self.prints if abs(w.cy - cy) < 5 and 0 <= w.x0 - b.x1 <= 12]
        if right:
            return min(right, key=lambda w: w.x0)
        left = [w for w in self.prints if abs(w.cy - cy) < 5 and w.x1 <= b.x0 + 2]
        return max(left, key=lambda w: w.x1) if left else None

    def _box_field(self, label: Word, cy: float):
        """-> (clé, FieldDef, code option | None pour bool) ; ancre = libellé du groupe le plus proche."""
        cands = []
        for k, f in self.free.items():
            if f.type == "bool" and _label_matches(label.text, f.labels):
                cands.append((0.0, k, f, None))
            elif f.type in ("enum", "checkbox_group"):
                c = f.choice_by_label(label.text)
                if c:
                    anchors = [cy - w.cy for w in self.find_print(f.labels) if cy - w.cy >= -5]
                    cands.append((min(anchors) if anchors else 500.0, k, f, c.code))
        if not cands:
            return None
        _, k, f, code = min(cands, key=lambda c: c[0])
        return k, f, code

    # ---------------------------------------------------------- mots manuscrits
    def assign_hand(self, grids) -> tuple[dict[str, list[Word]], list[Word]]:
        assigned: dict[str, list[Word]] = defaultdict(list)
        orphans = []
        words = [part for w in self.L.hand_words for part in self._split_on_columns(w, grids)]
        self.n_hand = len(words)
        for w in words:
            key = None
            for g in grids:
                key = self.cell_key(g, w)
                if key:
                    break
            if key is None:
                key = self._free_key(w)
            if key is None:
                orphans.append(w)
            else:
                assigned[key].append(w)
        return assigned, orphans

    @staticmethod
    def _split_on_columns(w: Word, grids) -> list[Word]:
        """Deux cellules voisines très remplies fusionnent en un seul « mot » : on recoupe
        caractère par caractère aux frontières de colonnes du tableau qui le contient."""
        for g in grids:
            if not (g["y"] + 3 < w.y < g["bottom"]):
                continue
            starts = [c["x0"] for c in g["cols"] if w.x0 + 4 < c["x0"] < w.x1]
            if not starts:
                continue
            # on ne coupe qu'à un vrai blanc (>= 2 pt) proche d'un début de colonne :
            # une date qui déborde un peu de sa cellule reste entière
            chars = sorted(w.chars, key=lambda c: c.x0)
            parts, cur = [], [chars[0]]
            for prev, c in zip(chars, chars[1:]):
                if c.x0 - prev.x1 >= 2 and any(abs(c.x0 - x) <= 8 for x in starts):
                    parts.append(cur)
                    cur = []
                cur.append(c)
            parts.append(cur)
            return [p for p in (make_word(cs) for cs in parts) if p.text.strip()]
        return [w]

    def _free_key(self, w: Word) -> str | None:
        # libellé à gauche sur la même ligne ; on compare les DÉBUTS de libellé car la valeur
        # est souvent écrite par-dessus les pointillés (« Autres à préciser : ........ »)
        left = [p for p in self.prints if _same_line(p.y, w.y) and p.x0 < w.x0 - 2]
        if left:
            hit = self.field_for_label(max(left, key=lambda p: p.x0), w.y)
            if hit:
                return hit[0]
        above = [p for p in self.prints if 3 < w.y - p.y <= ABOVE_MAX and p.x0 <= w.x0 + 20 and p.x1 >= w.x0 - 10]
        for p in sorted(above, key=lambda p: w.y - p.y):
            hit = self.field_for_label(p, w.y)
            if hit:
                return hit[0]
        return None

    def mark_present(self, grids) -> None:
        for k, f in self.free.items():
            if self.find_print(f.labels):
                self.present.add(k)
        for g in grids:
            t: TableDef = g["table"]
            prefix = f"{g['section']}." + (f"{t.key}." if t.key else "")
            for c in g["cols"]:
                if not t.rows:
                    self.present.add(prefix + c["code"])
                for r in {r["code"]: r for r in g["rows"]}.values():
                    self.present.add(prefix + (f"{c['code']}.{r['code']}" if t.instance == "col"
                                               else f"{r['code']}.{c['code']}"))


def _printed_identifiers(gt: PageGT) -> dict[str, str]:
    """Identifiants IMPRIMÉS (en-tête « MÈRE — Nom Prénom » des pages post-partum)."""
    out = {}
    for w in gt.prints:
        if w.text.startswith("MÈRE") and "—" in w.text:
            name = w.text.split("—", 1)[1].strip()
            sec = gt.sections[0]
            if name and f"{sec}.nom_patiente" in gt.fields:
                out[f"{sec}.nom_patiente"] = name
    return out


def build_page(page, pdf_page: int) -> tuple[dict, dict]:
    page_type = SPECIMEN_PAGE_ORDER[(pdf_page - 1) % len(SPECIMEN_PAGE_ORDER)]
    patient = (pdf_page - 1) // len(SPECIMEN_PAGE_ORDER) + 1
    gt = PageGT(page_layout(page), page_type)
    grids = gt.table_grids()
    gt.mark_present(grids)
    assigned, orphans = gt.assign_hand(grids)

    fields, raw, idents = {}, {}, _printed_identifiers(gt)
    for key, words in assigned.items():
        words.sort(key=lambda w: (round(w.y / 4), w.x0))
        text = clean_text(" ".join(w.text for w in words))
        f = gt.fields[key]
        if f.identifiant:
            idents[key] = text
            continue
        raw[key] = text
        value = normalize_value(f, text)
        if value is not None:               # tiret / vide : reste dans raw et vides
            fields[key] = value

    boxes, unmatched_boxes = gt.checkboxes()
    by_field: dict[str, list] = defaultdict(list)
    for key, f, code, marked in boxes:
        by_field[key].append((f, code, marked))
        gt.present.add(key)
    checked = []
    for key, items in by_field.items():
        f = items[0][0]
        on = [code for _, code, m in items if m]
        if f.type == "bool":
            fields[key] = bool(any(m for _, _, m in items))
            if fields[key]:
                checked.append(key)
        elif f.type == "enum":
            if on:                          # plusieurs cases d'un choix unique : on garde la liste
                fields[key] = on[0] if len(on) == 1 else on
            checked += [f"{key}:{c}" for c in on]
        else:
            fields[key] = sorted(on)
            checked += [f"{key}:{c}" for c in sorted(on)]

    vides = sorted(k for k in gt.present if not gt.fields[k].identifiant and fields.get(k) is None)
    doc = {
        "source": "specimen",
        "pdf_page": pdf_page,
        "patient": patient,
        "page_type": page_type,
        "sections": list(gt.sections),
        "fields": dict(sorted(fields.items())),
        "raw": dict(sorted(raw.items())),
        "checked": sorted(checked),
        "champs_cases": sorted(by_field),
        "vides": vides,
        "_identifiants": dict(sorted(idents.items())),
        "non_rattache": [w.text for w in orphans],
        "cases_non_rattachees": unmatched_boxes,
    }
    stats = {"hand_words": gt.n_hand, "orphans": len(orphans),
             "boxes": len(boxes) + len(unmatched_boxes), "boxes_unmatched": len(unmatched_boxes)}
    return doc, stats


def build_all(pages: list[int] | None = None) -> dict[str, Counter]:
    report: dict[str, Counter] = defaultdict(Counter)
    with pdfplumber.open(PDF_PATH) as pdf:
        for n in pages or range(1, len(pdf.pages) + 1):
            doc, st = build_page(pdf.pages[n - 1], n)
            write_json(GT_DIR / f"specimen_p{n:02d}.json", doc)
            report[doc["page_type"]].update(st)
            report[doc["page_type"]]["pages"] += 1
    return report


def reel_template(entry: dict) -> dict:
    """Modèle à remplir à la main pour une photo réelle : tous les champs plausibles à null."""
    keys = []
    for sec in entry["sections"]:
        for k, f in TEMPLATE.section_fields([sec]).items():
            if f.identifiant:
                continue
            if "visit_cols" in entry and sec == "grossesse_actuelle":
                if f.table == "visites" and f.col not in entry["visit_cols"]:
                    continue
                if f.table is None and f.key not in entry.get("champs_entete", []):
                    continue
            keys.append(k)
    idents = sorted(k for sec in entry["sections"] for k, f in TEMPLATE.section_fields([sec]).items()
                    if f.identifiant and ("visit_cols" not in entry or f.col in entry["visit_cols"]))
    return {
        "source": "reel",
        "image": entry["file"],
        "page_type": entry["page_type"],
        "sections": entry["sections"],
        "a_remplir": True,
        "fields": {k: None for k in keys},
        "checked": [],
        "champs_cases": sorted(k for k in keys if TEMPLATE.fields[k].type in ("bool", "checkbox_group")
                               or (TEMPLATE.fields[k].type == "enum" and TEMPLATE.fields[k].table is None)),
        "vides": [],
        "_identifiants": {},
        "_identifiants_cles": idents,
        "non_rattache": [],
    }


def build_reel_templates() -> list[str]:
    """Crée les modèles reel_*.json MANQUANTS (ne jamais écraser le travail de l'équipe)."""
    created = []
    local_ids = {}
    for e in load_manifest()["images"]:
        if e["source"] != "reel":
            continue
        path = GT_DIR / gt_name_for(e)
        tpl = reel_template(e)
        local_ids[path.name] = {k: None for k in tpl["_identifiants_cles"]}
        if not path.exists():
            write_json(path, tpl)
            created.append(path.name)
    local = GT_DIR / "reel_identifiants.local.json"
    if not local.exists():
        write_json(local, local_ids)
        created.append(local.name)
    return created


def print_report(report: dict[str, Counter]) -> float:
    print(f"{'type de page':28} {'pages':>5} {'mots':>6} {'rattachés':>9} {'non ratt.':>9} {'%non':>6} "
          f"{'cases':>6} {'cases n.r.':>10}")
    tot = Counter()
    for pt in SPECIMEN_PAGE_ORDER:
        r = report.get(pt)
        if not r:
            continue
        tot.update(r)
        pct = 100 * r["orphans"] / max(1, r["hand_words"])
        print(f"{pt:28} {r['pages']:5} {r['hand_words']:6} {r['hand_words'] - r['orphans']:9} {r['orphans']:9} "
              f"{pct:5.1f}% {r['boxes']:6} {r['boxes_unmatched']:10}")
    pct = 100 * tot["orphans"] / max(1, tot["hand_words"])
    print(f"{'TOTAL':28} {tot['pages']:5} {tot['hand_words']:6} {tot['hand_words'] - tot['orphans']:9} "
          f"{tot['orphans']:9} {pct:5.1f}% {tot['boxes']:6} {tot['boxes_unmatched']:10}")
    print(f"Objectif < 5 % de non rattaché : {'OK' if pct < 5 else 'NON ATTEINT'}")
    return pct


def main(argv: list[str]) -> int:
    pages = [int(a) for a in argv] or None
    pct = print_report(build_all(pages))
    created = build_reel_templates()
    if created:
        print("Modèles de photos réelles créés :", ", ".join(created))
    return 0 if pct < 5 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
