"""Page publique de politique de confidentialité (exigée par Meta pour publier l'app)."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter(tags=["public"])

_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Iris – Politique de confidentialité</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;line-height:1.55;color:#222}}
h1{{font-size:1.6rem}}h2{{font-size:1.15rem;margin-top:1.8rem}}</style></head><body>
<h1>Iris – Politique de confidentialité / Privacy Policy</h1>
<p><em>Prototype réalisé dans le cadre du hackathon CodeML 2026. Seules des données
synthétiques (fictives) sont utilisées ; aucune donnée réelle de patiente.</em></p>

<h2>1. Données traitées</h2>
<ul>
<li>Photos de pages de registre maternel envoyées via WhatsApp par une sage-femme.</li>
<li>Le numéro WhatsApp de la sage-femme, uniquement pour lui répondre.</li>
<li>Les champs médicaux extraits des photos (antécédents, grossesse, accouchement, postpartum).</li>
</ul>

<h2>2. Ce que nous ne stockons jamais</h2>
<p>Aucun identifiant direct de patiente : nom, nom du conjoint, téléphone, adresse,
numéro national. Ces informations sont ignorées lors de l'extraction. Les patientes
sont reliées par un code aléatoire attribué par la sage-femme.</p>

<h2>3. Traitement et sécurité</h2>
<ul>
<li>Toute l'analyse (lecture des photos par IA) est faite localement ; aucune donnée
n'est transmise à un service d'IA ou d'OCR tiers.</li>
<li>Les images d'origine sont chiffrées au repos et accessibles uniquement au personnel
autorisé ; chaque accès est journalisé.</li>
<li>WhatsApp (Meta) sert uniquement de canal de transmission des messages.</li>
</ul>

<h2>4. Conservation et partage</h2>
<p>Les données ne sont ni vendues ni partagées. Elles sont supprimées à la fin du hackathon.</p>

<h2 id="suppression">5. Suppression des données / Data deletion</h2>
<p>Pour demander la suppression de vos données, écrivez « SUPPRIMER » au numéro WhatsApp
du service{contact}. La demande est traitée sous 7 jours.</p>

<h2>English summary</h2>
<p>Iris is a hackathon prototype using synthetic data only. Registry photos sent via
WhatsApp are processed locally (no third-party AI). Direct patient identifiers are never
stored. Images are encrypted at rest with role-based, logged access. Data is not sold or
shared and is deleted after the event. To request deletion, send "SUPPRIMER" to the
service's WhatsApp number{contact_en}.</p>
</body></html>"""


@router.get("/confidentialite", response_class=HTMLResponse, include_in_schema=False)
@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy_policy():
    email = get_settings().contact_email
    return _PAGE.format(contact=f" ou contactez {email}" if email else "",
                        contact_en=f" or email {email}" if email else "")
