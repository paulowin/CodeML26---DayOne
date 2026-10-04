"""Prompts et schémas JSON construits DEPUIS LE TEMPLATE, pour un type de page.

Anti-hallucination :
- on ne demande QUE les champs du type de page détecté, jamais les identifiants ;
- toutes les clés du schéma sont optionnelles : le modèle n'inclut que ce qu'il
  voit dans la bande (clé omise = ABSENT_DE_CETTE_ZONE) ;
- l'état visuel est codé dans le texte : "" vide, "—" tiret, "#BARRE", "#ILLISIBLE" ;
- cases à cocher : UNE liste plate des options vraiment cochées (pas un champ par
  groupe : qwen2.5vl:3b « remplit » alors chaque groupe au hasard) ;
- règles explicites : ne jamais deviner, ne jamais recopier un libellé imprimé.

Format de réponse COMPACT (mesuré : un objet {raw, etat, confiance} par champ fait
dégénérer qwen2.5vl:3b, qui répond « ILLISIBLE, 0.5 » partout) :
    {"champs": {clé: texte},
     "lignes": {clé_ligne: {COLONNE: texte}},       # tableaux
     "cochees": ["clé" (case seule) | "clé=code"],   # cases cochées
     "confiance": 0..1}                              # certitude globale sur la bande
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.templates import get_template
from app.templates.base import FieldDef, TableDef, Template

ETATS = ("LISIBLE", "VIDE", "TIRET", "BARRE", "ILLISIBLE", "ABSENT_DE_CETTE_ZONE")
BOOL_OPTION = "coche"
VISIT_COL_HELP = {"T1V1": "1er trimestre, Visite 1", "T1V2": "1er trimestre, Visite 2",
                  "T1V3": "1er trimestre, Visite 3", "T2V1": "2ème trimestre, Visite 1",
                  "T2V2": "2ème trimestre, Visite 2", "T2V3": "2ème trimestre, Visite 3",
                  "M7": "3ème trimestre, 7ème mois", "M8": "3ème trimestre, 8ème mois",
                  "M9": "3ème trimestre, 9ème mois"}
TYPE_HINT = {"int": "nombre", "float": "nombre", "date": "date", "bp": "tension ex. 11/7 ou 110/70",
             "str": "texte", "enum": "choix"}


@dataclass
class TableLine:
    key: str                                 # clé de ligne dans la réponse
    label: str                               # en-tête de ligne imprimé
    table_label: str
    cells: dict[str, str]                    # code colonne -> clé complète du champ
    col_labels: dict[str, str]


@dataclass
class PageSpec:
    page_type: str
    page_label: str
    simple: dict[str, FieldDef] = field(default_factory=dict)       # clé complète -> champ
    lines: dict[str, TableLine] = field(default_factory=dict)
    checks: dict[str, FieldDef] = field(default_factory=dict)

    @property
    def keys(self) -> set[str]:
        return set(self.simple) | {k for ln in self.lines.values() for k in ln.cells.values()} | set(self.checks)

    def is_empty(self) -> bool:
        return not (self.simple or self.lines or self.checks)

    def chunks(self, max_lines: int = 8) -> list["PageSpec"]:
        """Découpe en requêtes plus petites : champs simples + cases, puis les lignes de tableau
        par paquets. Mesuré sur RTX 2050 : le tableau de visites entier en une requête
        (~3 600 tokens à 7,7 tokens/s) dépasse le délai ou fait planter la grammaire JSON."""
        out = []
        if self.simple or self.checks:
            out.append(PageSpec(self.page_type, self.page_label, dict(self.simple), {}, dict(self.checks)))
        keys = list(self.lines)
        for i in range(0, len(keys), max_lines):
            out.append(PageSpec(self.page_type, self.page_label, {}, {k: self.lines[k] for k in keys[i:i + max_lines]}, {}))
        return out or [self]


def check_options(f: FieldDef) -> list[tuple[str, str]]:
    if f.type == "bool":
        return [(BOOL_OPTION, f.label_fr)]
    return [(c.code, c.label_fr) for c in f.choices]


def page_spec(page_type: str, only: set[str] | None = None, template: Template | None = None) -> PageSpec:
    """Champs à demander pour ce type de page (sans identifiants), éventuellement restreints à `only`."""
    t = template or get_template()
    pt = t.page_type(page_type)
    spec = PageSpec(page_type, pt.label_fr or pt.key)
    for sec_key in pt.sections:
        sec = t.section(sec_key)
        for f in sec.fields:
            k = f"{sec_key}.{f.key}"
            if f.identifiant or (only is not None and k not in only):
                continue
            (spec.checks if f.is_checkbox else spec.simple)[k] = f
        for tb in sec.tables:
            _add_table(spec, sec_key, tb, only)
    return spec


def _add_table(spec: PageSpec, sec_key: str, tb: TableDef, only: set[str] | None) -> None:
    prefix = f"{sec_key}." + (f"{tb.key}." if tb.key else "")
    if not tb.rows:                                   # tableau « en colonnes » = champs texte simples
        for cell in tb.cells():
            k = prefix + cell.key
            if only is None or k in only:
                spec.simple[k] = cell
        return
    col_labels = {}
    for code, label in tb.cols:
        col_labels[code] = VISIT_COL_HELP.get(code, label)
    for r in tb.rows:
        if r.identifiant:
            continue
        cells = {}
        for code, _ in tb.cols:
            k = prefix + (f"{code}.{r.key}" if tb.instance == "col" else f"{r.key}.{code}")
            if only is None or k in only:
                cells[code] = k
        if cells:
            line_key = prefix + r.key
            spec.lines[line_key] = TableLine(line_key, r.label_fr, tb.label_fr, cells,
                                             {c: col_labels[c] for c in cells})


# ------------------------------------------------------------------ texte du prompt
RULES = """RÈGLES ABSOLUES :
1. Ne devine JAMAIS. Si tu n'es pas sûr de ce qui est écrit, écris "#ILLISIBLE".
2. Ne recopie JAMAIS un libellé IMPRIMÉ comme valeur (ex. « Autres : », « En milieu surveillé », « Visite 1 »). Seule l'écriture au stylo est une valeur.
3. Si un champ n'est pas dans CETTE image, ne l'inclus pas.
4. N'écris JAMAIS de nom, prénom, CIN, adresse, téléphone, nom du mari, ni qui a fait l'examen (« Vu par », « Examen fait par ») : ces zones sont interdites.
5. Recopie le texte EXACT, sans corriger ni convertir (garde « RAS », « nég », « 11/7 », « 16SA+3j », « 0,76 g/l », les unités).
Codes : "" = rien d'écrit, "—" = un tiret ou un trait, "#BARRE" = case barrée d'un grand trait, "#ILLISIBLE" = illisible."""


def check_tokens(k: str, f: FieldDef) -> list[tuple[str, str]]:
    """Jetons « clé » / « clé=code » des cases à cocher, avec leur libellé imprimé."""
    if f.type == "bool":
        return [(k, f.label_fr)]
    return [(f"{k}={c.code}", c.label_fr) for c in f.choices]


def build_prompt(spec: PageSpec, band_index: int | None = None, n_bands: int | None = None) -> str:
    where = (f"une BANDE horizontale (partie {band_index + 1} sur {n_bands}, de haut en bas) de la page"
             if band_index is not None else "la page")
    parts = [f"Tu lis {where} « {spec.page_label} » d'un carnet de suivi de grossesse marocain "
             "(formulaire imprimé rempli à la main au stylo). Recopie l'écriture manuscrite des champs listés.",
             RULES]
    if spec.simple:
        parts.append('CHAMPS -> "champs" {clé: texte écrit à côté du libellé imprimé} :')
        for k, f in spec.simple.items():
            hint = TYPE_HINT.get(f.type, f.type)
            if f.type == "enum":
                hint += " parmi " + ", ".join(c.label_fr for c in f.choices)
            if f.unit:
                hint += f", unité {f.unit}"
            parts.append(f"- {k} : « {f.label_fr} » [{hint}]")
    if spec.lines:
        tables: dict[str, list[TableLine]] = {}
        for ln in spec.lines.values():
            tables.setdefault(ln.table_label, []).append(ln)
        parts.append('TABLEAUX -> "lignes" {clé_ligne: {COLONNE: texte}}. Seulement les lignes VISIBLES ; '
                     "une cellule par colonne visible, lue dans SA colonne (ne décale pas).")
        for label, lines in tables.items():
            cols = lines[0].col_labels
            parts.append(f"Tableau « {label} », colonnes : " + " ; ".join(f"{c} = {l}" for c, l in cols.items()))
            parts += [f"- {ln.key} : « {ln.label} »" for ln in lines]
    if spec.checks:
        parts.append('CASES À COCHER -> "cochees" : liste UNIQUEMENT les cases réellement cochées dans cette image '
                     "(croix, coche ou option entourée). Une case vide n'est PAS cochée. [] si aucune.")
        for k, f in spec.checks.items():
            parts += [f"- {tok} : « {lab} »" for tok, lab in check_tokens(k, f)]
    parts.append('"confiance" : de 0 à 1, ta certitude globale sur ta lecture. Réponds UNIQUEMENT en JSON.')
    return "\n".join(parts)


def build_schema(spec: PageSpec) -> dict:
    """Schéma JSON (structured outputs) : conteneurs obligatoires, champs optionnels."""
    props: dict = {}
    if spec.simple:
        props["champs"] = {"type": "object", "properties": {k: {"type": "string"} for k in spec.simple}}
    if spec.lines:
        props["lignes"] = {"type": "object", "properties": {
            k: {"type": "object", "properties": {c: {"type": "string"} for c in ln.cells}}
            for k, ln in spec.lines.items()}}
    if spec.checks:
        tokens = [tok for k, f in spec.checks.items() for tok, _ in check_tokens(k, f)]
        props["cochees"] = {"type": "array", "items": {"type": "string", "enum": tokens}}
    props["confiance"] = {"type": "number"}
    # les CONTENEURS sont obligatoires (sinon le 3B répond juste {"confiance": 0.9}),
    # les champs à l'intérieur restent optionnels (champ non vu = clé omise)
    return {"type": "object", "properties": props, "required": list(props)}


def output_budget(spec: PageSpec) -> int:
    """Tokens de sortie raisonnables pour cette requête (le modèle qui boucle est coupé tôt :
    ~7,7 tokens/s sur RTX 2050, 2048 tokens = 4 min 30)."""
    n_cells = sum(len(ln.cells) for ln in spec.lines.values())
    n_checks = sum(len(check_tokens(k, f)) for k, f in spec.checks.items())
    return 150 + 18 * len(spec.simple) + 10 * n_cells + 14 * n_checks
