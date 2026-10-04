"""Briques pour décrire un carnet papier (un carnet = un fichier template).

Un template décrit des SECTIONS (pas des pages : une photo réelle peut en
contenir une ou plusieurs). Chaque section contient des champs simples et/ou
des tableaux ; un tableau génère un champ par cellule, avec une clé indexée
(`grossesse_actuelle.visites.T2V1.poids_kg`).

Les libellés `label_fr` reprennent le texte IMPRIMÉ sur le formulaire : ils
servent à aligner l'écriture manuscrite sur le bon champ (vérité terrain,
extraction IA). `aliases` couvre les variantes d'impression (vrai carnet).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Iterable

FIELD_TYPES = ("int", "float", "str", "date", "enum", "bool", "checkbox_group", "bp")


def slug(text: str) -> str:
    """'Voie basse non instrumentale' -> 'voie_basse_non_instrumentale'."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = t.replace("<", " moins ").replace("+", " plus ")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def norm_label(text: str) -> str:
    """Normalise un libellé imprimé pour comparaison (casse, accents, ponctuation finale, pointillés)."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = t.replace("œ", "oe")
    t = re.sub(r"\.{2,}|…", " ", t)            # pointillés de saisie
    t = re.sub(r"[:?]", " ", t)
    t = re.sub(r"^[-–—•]\s*", "", t.strip())    # puces « - Anémie »
    return re.sub(r"\s+", " ", t).strip(" .")


@dataclass(frozen=True)
class Choice:
    code: str
    label_fr: str
    aliases: tuple[str, ...] = ()

    @property
    def labels(self) -> tuple[str, ...]:
        return (self.label_fr, *self.aliases)


def ch(label: str, code: str | None = None, *aliases: str) -> Choice:
    return Choice(code or slug(label), label, tuple(aliases))


@dataclass(frozen=True)
class FieldDef:
    key: str                                   # clé locale (dans la section)
    label_fr: str                              # texte imprimé (libellé, ou en-tête de ligne d'un tableau)
    type: str = "str"
    choices: tuple[Choice, ...] = ()
    unit: str | None = None
    plausible: tuple[float, float] | None = None
    csv_column: str | tuple[str, ...] | None = None   # colonne(s) de maternal_registry_synthetic.csv
    identifiant: bool = False                  # identifiant direct : jamais extrait, jamais stocké
    critique: bool = False                     # jamais CONNU sur une seule lecture (bloc 3b)
    ecrit: bool = False                        # choix fermé mais ÉCRIT à la main (pas de cases), ex. « Sexe : F »
    longitudinal: bool = False                 # varie d'une visite à l'autre
    context: str | None = None                 # libellé voisin qui lève l'ambiguïté (« Le » rubéole / hépatite)
    aliases: tuple[str, ...] = ()
    # renseignés pour les cellules de tableau
    table: str | None = None
    col: str | None = None                     # code de colonne (T1V1, 1, femme...)
    row: str | None = None                     # code de ligne

    def __post_init__(self):
        assert self.type in FIELD_TYPES, self.type

    @property
    def labels(self) -> tuple[str, ...]:
        return (self.label_fr, *self.aliases)

    @property
    def is_checkbox(self) -> bool:
        """Saisi par cases à cocher (bool, groupe, ou choix unique non écrit)."""
        return self.type in ("bool", "checkbox_group") or (self.type == "enum" and not self.ecrit)

    @property
    def choice_codes(self) -> tuple[str, ...]:
        return tuple(c.code for c in self.choices)

    def choice_by_label(self, text: str) -> Choice | None:
        n = norm_label(text)
        for c in self.choices:
            if any(norm_label(l) == n for l in c.labels):
                return c
        return None


@dataclass(frozen=True)
class TableDef:
    """Tableau imprimé.

    - `cols` : (code, libellé d'en-tête imprimé) dans l'ordre gauche -> droite
      (les doublons de libellé, ex. « Visite 1 » x2, sont résolus par l'ordre).
    - `rows` : un FieldDef par ligne (libellé = en-tête de ligne imprimé à gauche).
      Vide => tableau « en colonnes » : chaque colonne est un champ texte libre.
    - clé générée : `<table>.<col>.<row>` (instance = colonne) ou
      `<table>.<row>.<col>` si `instance="row"` ; `<col>` seul si pas de lignes.
    """
    key: str
    label_fr: str
    cols: tuple[tuple[str, str], ...]
    rows: tuple[FieldDef, ...] = ()
    instance: str = "col"
    col_aliases: dict = field(default_factory=dict)   # code -> autres libellés d'en-tête
    col_types: dict = field(default_factory=dict)     # instance="row" : code de colonne -> (type, unit, plausible)

    def cells(self) -> list[FieldDef]:
        out = []
        if not self.rows:
            for code, label in self.cols:
                out.append(FieldDef(code, label, "str", table=self.key, col=code,
                                    aliases=tuple(self.col_aliases.get(code, ()))))
            return out
        for code, label in self.cols:
            for r in self.rows:
                if self.instance == "col":
                    key = f"{self.key}.{code}.{r.key}" if self.key else f"{code}.{r.key}"
                    out.append(replace(r, key=key, table=self.key, col=code, row=r.key))
                else:
                    key = f"{self.key}.{r.key}.{code}" if self.key else f"{r.key}.{code}"
                    t, unit, plaus = self.col_types.get(code, ("str", None, None))
                    csv = r.csv_column if code == self.cols[0][0] else None   # ex. nombre d'avortements
                    out.append(replace(r, key=key, type=t, unit=unit, plausible=plaus, csv_column=csv,
                                       table=self.key, col=code, row=r.key))
        return out


@dataclass(frozen=True)
class SectionDef:
    key: str
    label_fr: str
    fields: tuple[FieldDef, ...] = ()
    tables: tuple[TableDef, ...] = ()

    def all_fields(self) -> list[FieldDef]:
        out = list(self.fields)
        for t in self.tables:
            out.extend(t.cells())
        return out


@dataclass(frozen=True)
class PageType:
    """Page type du formulaire spécimen (sert au manifeste et à la vérité terrain)."""
    key: str
    title_markers: tuple[str, ...]             # textes imprimés qui identifient la page
    sections: tuple[str, ...]
    keywords: tuple[str, ...] = ()             # mots-clés propres à la page (classification par texte lu)
    label_fr: str = ""


@dataclass
class Template:
    key: str
    label_fr: str
    sections: tuple[SectionDef, ...]
    page_types: tuple[PageType, ...] = ()
    fields: dict[str, FieldDef] = field(init=False)        # "section.clé" -> FieldDef (identifiants inclus)

    def __post_init__(self):
        self.fields = {}
        for s in self.sections:
            for f in s.all_fields():
                full = f"{s.key}.{f.key}"
                assert full not in self.fields, f"clé en double : {full}"
                self.fields[full] = f

    def section(self, key: str) -> SectionDef:
        return next(s for s in self.sections if s.key == key)

    def page_type(self, key: str) -> PageType:
        return next(p for p in self.page_types if p.key == key)

    def section_fields(self, section_keys: Iterable[str]) -> dict[str, FieldDef]:
        prefixes = tuple(f"{s}." for s in section_keys)
        return {k: f for k, f in self.fields.items() if k.startswith(prefixes)}

    @property
    def stored_fields(self) -> dict[str, FieldDef]:
        return {k: f for k, f in self.fields.items() if not f.identifiant}

    @property
    def identifier_fields(self) -> dict[str, FieldDef]:
        return {k: f for k, f in self.fields.items() if f.identifiant}
