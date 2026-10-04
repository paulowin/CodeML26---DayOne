"""Type de page parmi ceux du template (+ « inconnu »).

Une seule requête VLM sur la vignette : le modèle recopie les titres imprimés
lisibles ET propose un type (enum JSON). On décide d'abord par MOTS-CLÉS sur le
texte recopié (plus fiable qu'un choix direct) ; à défaut, on prend l'enum.
"""
from __future__ import annotations

from app.templates import get_template
from app.templates.base import Template, norm_label

UNKNOWN = "inconnu"


def classify_text(text: str, template: Template | None = None) -> str | None:
    """Type de page d'après le texte imprimé lu ; None si aucun mot-clé ou ex æquo."""
    t = template or get_template()
    n = norm_label(text)
    scores = {}
    for pt in t.page_types:
        title = sum(3 for m in pt.title_markers if norm_label(m) in n)
        kw = sum(1 for k in pt.keywords if norm_label(k) in n)
        scores[pt.key] = title + kw
    best = max(scores.values(), default=0)
    winners = [k for k, s in scores.items() if s == best]
    return winners[0] if best > 0 and len(winners) == 1 else None


def classify_prompt(template: Template) -> str:
    lines = [f"- {pt.key} : {pt.label_fr} (ex. « {pt.keywords[0] if pt.keywords else pt.title_markers[0]} »)"
             for pt in template.page_types]
    return (
        "Tu regardes la photo d'une page d'un carnet de suivi de grossesse marocain (formulaire imprimé "
        "rempli à la main).\n"
        "1. Dans \"titres\", recopie EXACTEMENT les titres et intitulés IMPRIMÉS les plus visibles "
        "(en-têtes, titres de tableaux, 8 au maximum). N'écris rien de manuscrit.\n"
        "2. Dans \"type\", choisis le type de page :\n" + "\n".join(lines) +
        f"\n- {UNKNOWN} : si ce n'est pas une page de ce carnet ou si tu ne peux pas décider.\n"
        "Réponds uniquement en JSON."
    )


def classify_schema(template: Template) -> dict:
    return {"type": "object",
            "properties": {"titres": {"type": "array", "items": {"type": "string"}},
                           "type": {"type": "string", "enum": [p.key for p in template.page_types] + [UNKNOWN]}},
            "required": ["titres", "type"]}


def classify(client, model: str, thumb: bytes, template: Template | None = None,
             use_cache: bool = True) -> tuple[str, str]:
    """-> (type de page, méthode : 'mots_cles' | 'vlm' | 'inconnu')."""
    t = template or get_template()
    res = client.generate(model, classify_prompt(t), [thumb], classify_schema(t), use_cache=use_cache,
                          num_predict=300)
    titles = res.data.get("titres") or []
    by_text = classify_text(" ".join(str(x) for x in titles), t)
    if by_text:
        return by_text, "mots_cles"
    vlm = res.data.get("type")
    if vlm in {p.key for p in t.page_types}:
        return vlm, "vlm"
    return UNKNOWN, "inconnu"
