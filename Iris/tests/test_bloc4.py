"""Bloc 4 : vérification conversationnelle + liaison patiente, joué via des payloads webhook."""
import itertools
import json
import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (ExtractedField, FieldSource, FieldStatus, Midwife, Page, Patient, Record, RecordStatus)
from app.services import conversation as conv
from app.services import outbox
from eval.common import GT_DIR
from eval.evaluate import find_leaks
from scripts.demo_seed import seed
from tests.conftest import MIDWIFE, body_of, button_msg, image_msg, post_webhook, text_msg, wa_payload

_n = itertools.count(1)
S = RecordStatus


# ------------------------------------------------------------------ helpers
def _ts() -> int:
    return int(time.time()) + next(_n)


def press(client, bid: str):
    post_webhook(client, wa_payload(button_msg(f"wamid.b{uuid.uuid4().hex}", bid, _ts())))


def say(client, text: str):
    post_webhook(client, wa_payload(text_msg(f"wamid.t{uuid.uuid4().hex}", text, _ts())))


def ids(payload: dict) -> list[str]:
    if payload.get("type") != "interactive":
        return []
    inter = payload["interactive"]
    if inter["type"] == "button":
        return [b["reply"]["id"] for b in inter["action"]["buttons"]]
    return [r["id"] for sec in inter["action"]["sections"] for r in sec["rows"]]


def find_id(payload: dict, action: str) -> str:
    return next(i for i in ids(payload) if i.startswith(action + "|"))


def state() -> dict:
    with SessionLocal() as db:
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE))
        return conv.load_state(mw)


def flush(fake_wa):
    with SessionLocal() as db:
        outbox.flush_pending(db)


def seeded(fake_wa) -> str:
    """Démo : 2 patientes + un dossier A_REVISER (5 champs douteux) ; s'assure qu'il a une page."""
    rid = seed(MIDWIFE, send=False)
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        if not rec.pages:                     # data-defi absent (CI) : page factice
            from app.storage import get_store
            key, sha = get_store().save(b"\xff\xd8demo")
            rec.pages.append(Page(page_number=1, storage_key=key, sha256=sha, mime_type="image/jpeg",
                                  size_bytes=6, wa_message_id=f"demo-{rid}", captured_at=datetime.now(timezone.utc),
                                  page_type="grossesse_actuelle", identifiers_excluded='["examen_fait_par"]'))
            db.commit()
    flush(fake_wa)
    return rid


def current(rid: str) -> dict[str, ExtractedField]:
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        return {f"{f.section}.{f.field_key}": f for f in rec.fields if f.is_current}


def all_out(fake_wa) -> list[dict]:
    return list(fake_wa.sent)


V = "grossesse_actuelle.visites."


# ------------------------------------------------------------------ révision complète
def test_revision_complete_puis_liaison_code_exact(client, fake_wa):
    rid = seeded(fake_wa)
    summary = fake_wa.sent[-1]
    assert "5 à vérifier (environ 1 minute)" in body_of(summary) and "(s)" not in body_of(summary)
    assert "champs lus" in body_of(summary)
    assert [b.split("|")[0] for b in ids(summary)] == ["OKLU", "CORRLU", "MORE"]
    for b in summary["interactive"]["action"]["buttons"]:
        assert len(b["reply"]["title"]) <= 20
    lu = body_of(fake_wa.sent[-2])                                     # « Voici ce que j'ai lu »
    assert lu.startswith("Voici ce que j'ai lu (page 1 – Grossesse actuelle) :")
    assert "1. Couverture · N° de la fiche : A64125" in lu and "… et " in lu and "À vérifier : 5 –" in lu
    assert "Non enregistré (confidentialité) : nom du soignant" in lu

    press(client, find_id(summary, "OKLU"))
    queue = state()["queue"]
    assert len(queue) == 5 and queue[0] == "grossesse_actuelle.ddr"           # critiques d'abord
    assert queue[-1] in (V + "T2V3.poids_kg", V + "M8.age_probable_sa")

    for key in queue:
        q = fake_wa.sent[-1]
        assert key.split(".")[-1] and "Question" in body_of(q)
        if key == V + "T2V2.ta":                                              # 2 lectures concurrentes
            assert q["interactive"]["type"] == "list"
            titles = [r["title"] for r in q["interactive"]["action"]["sections"][0]["rows"]]
            assert titles[:2] == ["106/77 mmHg", "166/77 mmHg"] and "Autre valeur" in titles
            descs = [r["description"] for r in q["interactive"]["action"]["sections"][0]["rows"]]
            assert descs[:2] == ["Lecture 1", "Lecture 2"]
            assert "les deux lectures diffèrent" in body_of(q)
            assert all(len(t) <= 24 for t in titles)
            press(client, next(i for i in ids(q) if i.startswith("CAND|") and i.split("|")[2].endswith("#0")))
        elif key == V + "T1V2.hemoglobine":                # « illisible » mais une lecture existe
            assert "J'ai lu : 11.8 g/dL" in body_of(q) and "→ —" not in body_of(q)
            assert "écriture peu lisible" in body_of(q)
            assert [i.split("|")[0] for i in ids(q)] == ["CONF", "CORR", "ILL"]   # la valeur reste proposée
            press(client, find_id(q, "ILL"))
        elif key == "grossesse_actuelle.ddr":                                 # corriger : invalide puis valide
            assert "J'ai lu : 26/04/2025" in body_of(q) and "»" not in body_of(q)   # affiché une seule fois
            assert "incohérent avec la DPA" in body_of(q)
            press(client, find_id(q, "CORR"))
            assert "jj/mm/aaaa" in body_of(fake_wa.sent[-1])
            say(client, "31/02/2025")
            assert "Je n'ai pas compris" in body_of(fake_wa.sent[-1])
            say(client, "27/04/2025")
        else:
            press(client, find_id(q, "CONF"))

    final = fake_wa.sent[-1]
    assert "autres champs" in body_of(final)
    press(client, find_id(final, "VIEW"))
    view = fake_wa.sent[-1]
    assert body_of(view).count("\n") > 5 and len(body_of(view)) <= 1024 and "CORRIGER" in body_of(view)
    press(client, find_id(view, "ALLOK"))

    with SessionLocal() as db:
        assert db.get(Record, rid).status == S.VALIDE
    link = fake_wa.sent[-1]
    assert link["interactive"]["type"] == "list"
    rows = link["interactive"]["action"]["sections"][0]["rows"]
    assert rows[0]["description"].startswith("code A64125 – 3 visites, dernière 01/12")
    assert rows[1]["description"].startswith("code A64128 – 1 visite,")
    assert "A64128" in rows[1]["description"]                                 # code proche proposé aussi
    assert [r["title"] for r in rows[2:]] == ["Aucune, créer", "Je ne sais pas"]
    press(client, rows[0]["id"])

    f = current(rid)
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        assert rec.status == S.ENREGISTRE and db.get(Patient, rec.patient_id).code == "A64125"
        history = [x for x in rec.fields if x.section == "grossesse_actuelle" and x.field_key == "ddr"]
        assert len(history) == 2 and sum(x.is_current for x in history) == 1   # ancienne version gardée
    assert json.loads(f["grossesse_actuelle.ddr"].value_json) == "2025-04-27"
    assert f["grossesse_actuelle.ddr"].source == FieldSource.SAGE_FEMME
    assert json.loads(f[V + "T2V2.ta"].value_json) == {"sys": 106, "dia": 77}
    assert f[V + "T1V2.hemoglobine"].status == FieldStatus.ILLISIBLE
    assert all(x.source != FieldSource.IA for x in f.values())                # tout a été confirmé

    # confidentialité : aucun identifiant de la patiente fictive 1 (toutes pages) dans les messages
    idents = set()
    for p in GT_DIR.glob("specimen_p0[1-8].json"):
        idents |= {v for v in json.loads(p.read_text(encoding="utf-8"))["_identifiants"].values() if v}
    assert "Tazi Meryem" in idents
    assert find_leaks({"fields": {}, "messages": all_out(fake_wa)}, idents) == []


def test_bouton_perime_et_autre_dossier_ignores(client, fake_wa):
    seeded(fake_wa)
    rev = find_id(fake_wa.sent[-1], "OKLU")
    press(client, rev)
    q = fake_wa.sent[-1]
    press(client, rev)                                                      # déjà utilisé
    assert body_of(fake_wa.sent[-1]) == "Cette question n'est plus d'actualité."
    press(client, "CONF|deadbeef|grossesse_actuelle.ddr|" + rev.split("|")[3])
    assert body_of(fake_wa.sent[-1]) == "Cette question n'est plus d'actualité."
    assert state()["idx"] == 0                                              # rien n'a bougé
    press(client, find_id(q, "CONF"))
    assert state()["idx"] == 1


def test_pause_puis_reprise(client, fake_wa):
    seeded(fake_wa)
    press(client, find_id(fake_wa.sent[-1], "OKLU"))
    old = fake_wa.sent[-1]
    say(client, "plus tard")
    assert "REPRENDRE" in body_of(fake_wa.sent[-1]) and state()["paused"]
    say(client, "REPRENDRE")
    again = fake_wa.sent[-1]
    assert body_of(again) == body_of(old) and ids(again) != ids(old)        # même question, nouvelle version
    press(client, find_id(old, "CONF"))
    assert "plus d'actualité" in body_of(fake_wa.sent[-1])
    say(client, "OK")                                                       # OK = confirmer
    assert state()["idx"] == 1


def test_anglais_puis_francais(client, fake_wa):
    seeded(fake_wa)
    say(client, "EN")
    assert body_of(fake_wa.sent[-1]) == "Language: English."
    say(client, "CONTINUE")
    s = fake_wa.sent[-1]
    assert body_of(s).startswith("Reading done") and s["interactive"]["action"]["buttons"][0]["reply"]["title"] == "All correct"
    assert body_of(fake_wa.sent[-2]).startswith("Here is what I read (page 1")
    say(client, "AIDE")
    assert body_of(fake_wa.sent[-1]).startswith("Commands")
    say(client, "FR")
    assert body_of(fake_wa.sent[-1]) == "Langue : français."


def test_reprendre_la_photo(client, fake_wa):
    rid = seeded(fake_wa)
    say(client, "PHOTO")
    assert "Envoyez la nouvelle photo de la page 1" in body_of(fake_wa.sent[-1])
    fake_wa.media["m-new"] = b"\xff\xd8nouvelle photo"
    post_webhook(client, wa_payload(image_msg("wamid.newphoto", "m-new", _ts())))
    assert "Nouvelle photo reçue" in body_of(fake_wa.sent[-1])
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        assert rec.status == S.EN_ATTENTE_IA
        old, new = sorted(rec.pages, key=lambda p: p.page_number)
        assert old.replaced and not new.replaced and new.replaces_page == 1
    assert state()["mode"] == conv.IDLE


# ------------------------------------------------------------------ saisie manuelle
def _valid_answer(key: str) -> str:
    f = conv.T.fields[key]
    if f.type == "date":
        return "03/02/2026"
    if f.type == "bp":
        return "12/7"
    if f.type in ("int", "float"):
        return f"{f.plausible[0] + 1:g}" if f.plausible else "1"
    if f.type == "enum":
        return f.choices[0].label_fr
    if f.type == "bool":
        return "oui"
    if f.type == "checkbox_group":
        return "aucune"
    return "RAS"


def test_saisie_manuelle_puis_creation_patiente(client, fake_wa):
    from app.main import run_maintenance_cycle
    with SessionLocal() as db:
        mw = Midwife(wa_id=MIDWIFE)
        db.add(mw)
        db.flush()
        rec = Record(midwife_id=mw.id, status=S.ECHEC_TRAITEMENT, ai_attempts=3)
        db.add(rec)
        db.commit()
        rid = rec.id
    run_maintenance_cycle()
    intro = fake_wa.sent[-1]
    assert "saisie guidée" in body_of(intro)
    press(client, find_id(intro, "MAN"))
    queue = state()["queue"]
    assert len(queue) > 5 and all(conv.T.fields[k].table is None for k in queue)
    say(client, "n'importe quoi")                                           # 1re question : invalide
    assert "Je n'ai pas compris" in body_of(fake_wa.sent[-1])
    for i, key in enumerate(queue):
        say(client, "passer" if i % 2 else _valid_answer(key))
    assert "code de la patiente" in body_of(fake_wa.sent[-1])
    with SessionLocal() as db:
        assert db.get(Record, rid).status == S.VALIDE
    say(client, "B 99-999")
    none = fake_wa.sent[-1]
    assert "Aucune patiente" in body_of(none)
    assert [i.split("|")[0] for i in ids(none)] == ["LINKNEW", "FIXCODE", "LINKUNK"]
    press(client, find_id(none, "LINKNEW"))
    f = current(rid)
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        assert rec.status == S.ENREGISTRE and db.get(Patient, rec.patient_id).code == "B99999"
    assert f[queue[1]].status == FieldStatus.NON_FOURNI and f[queue[0]].status == FieldStatus.CONNU


# ------------------------------------------------------------------ liaison
def _validated_record(db, mw: Midwife, venue: str = "2026-01-18") -> Record:
    rec = Record(midwife_id=mw.id, status=S.VALIDE)
    db.add(rec)
    db.flush()
    conv.set_field(db, rec, V + "T1V1.venue_le", venue, FieldStatus.CONNU, FieldSource.SAGE_FEMME)
    conv.set_field(db, rec, V + "T1V1.poids_kg", 71.5, FieldStatus.CONNU, FieldSource.SAGE_FEMME)
    return rec


def _start_link(code: str, venue: str = "2026-01-18") -> str:
    with SessionLocal() as db:
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE))
        rec = _validated_record(db, mw, venue)
        st = conv._reset(conv.load_state(mw))
        conv.start_linking(db, mw, rec, st, conv.Out(db, mw), code=code)
        db.commit()
        return rec.id


def test_liaison_code_proche_puis_je_ne_sais_pas_puis_superviseur(client, fake_wa):
    from app.models import Role, Staff
    from app.security import hash_api_key
    seeded(fake_wa)
    say(client, "PLUS TARD")                                                # la démo attend
    rid = _start_link("A64I25")                                             # I lu à la place de 1
    flush(fake_wa)
    rows = fake_wa.sent[-1]["interactive"]["action"]["sections"][0]["rows"]
    assert rows[0]["description"].startswith("code A64125")                 # confusion I/1 : score 1
    assert rows[1]["description"].startswith("code A64128")                 # 1 caractère d'écart
    press(client, rows[3]["id"])                                            # Je ne sais pas
    assert any("superviseur" in body_of(m) for m in fake_wa.sent[-4:])
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        assert rec.status == S.VALIDE and rec.link_pending
        p = db.scalar(select(Patient).where(Patient.code == "A64125"))
        db.add(Staff(label="sup", role=Role.SUPERVISEUR, api_key_hash=hash_api_key("sup-k")))
        db.commit()
        pid = p.id
    tab = client.get("/api/tableau", headers={"X-API-Key": "sup-k"}).json()
    assert any(x["dossier"] == rid for x in tab["a_rattacher"])
    r = client.post(f"/api/records/{rid}/rattacher", json={"patient_id": pid}, headers={"X-API-Key": "sup-k"})
    assert r.status_code == 200 and r.json()["status"] == "ENREGISTRE"


def test_doublon_mettre_a_jour(client, fake_wa):
    seeded(fake_wa)
    say(client, "PLUS TARD")
    rid = _start_link("A64125", venue="2025-12-01")                         # même date qu'une visite connue
    flush(fake_wa)
    rows = fake_wa.sent[-1]["interactive"]["action"]["sections"][0]["rows"]
    press(client, rows[0]["id"])
    dup_msg = fake_wa.sent[-1]
    assert "ressemble à la visite du 01/12/2025" in body_of(dup_msg)
    assert [i.split("|")[0] for i in ids(dup_msg)] == ["DUPUPD", "DUPNEW", "DUPCANCEL"]
    with SessionLocal() as db:
        assert db.get(Record, rid).status == S.DOUBLON_SUSPECT
        dup_id = conv.load_state(db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE)))["dup_id"]
    press(client, find_id(dup_msg, "DUPUPD"))
    with SessionLocal() as db:
        assert db.get(Record, rid).status == S.ANNULE
        dup = db.get(Record, dup_id)
        poids = [f for f in dup.fields if f.field_key == "visites.T1V1.poids_kg" and f.is_current]
        assert json.loads(poids[0].value_json) == 71.5 and poids[0].source == FieldSource.SAGE_FEMME
    assert any("mise à jour" in body_of(m) for m in fake_wa.sent[-3:])


def test_un_seul_dossier_a_la_fois(client, fake_wa):
    seeded(fake_wa)
    with SessionLocal() as db:
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE))
        other = Record(midwife_id=mw.id, status=S.A_REVISER)
        db.add(other)
        db.flush()
        conv.on_record_ready(db, other)
        db.commit()
    flush(fake_wa)
    assert "après le dossier en cours" in body_of(fake_wa.sent[-1])


def test_garde_valide_accepte_illisible_confirme(client):
    from app.state_machine import InvalidTransition, transition
    with SessionLocal() as db:
        mw = Midwife(wa_id="2120000")
        db.add(mw)
        db.flush()
        rec = Record(midwife_id=mw.id, status=S.A_REVISER)
        db.add(rec)
        db.flush()
        conv.set_field(db, rec, V + "T1V1.bcf", None, FieldStatus.ILLISIBLE, FieldSource.IA, 0.3)
        with pytest.raises(InvalidTransition):
            transition(db, rec, S.VALIDE, f"midwife:{mw.id}")
        conv.set_field(db, rec, V + "T1V1.bcf", None, FieldStatus.ILLISIBLE, FieldSource.SAGE_FEMME)
        transition(db, rec, S.VALIDE, f"midwife:{mw.id}")
        assert rec.status == S.VALIDE


def test_limites_whatsapp_et_textes_bilingues():
    from app.i18n import MESSAGES
    assert set(MESSAGES["fr"]) == set(MESSAGES["en"])
    for lang in ("fr", "en"):
        for k, v in MESSAGES[lang].items():
            if k.startswith("btn_"):
                assert len(v) <= 20, (lang, k, v)
            if k.startswith("row_") and not k.endswith("_d") and "{" not in v:
                assert len(v) <= 24, (lang, k, v)



def test_affichage_valeur_lue_et_raisons():
    from app.services.conversation import Out, accentue, doubt_reason, field_label, read_line
    f_ta = conv.T.fields[V + "T1V1.ta"]

    class O(Out):
        def __init__(self):
            self.lang = "fr"
    o = O()
    assert read_line(f_ta, "106/77", {"sys": 106, "dia": 77}, o) == "J'ai lu : 106/77 mmHg"
    assert read_line(f_ta, "11/7", {"sys": 110, "dia": 70}, o) == "J'ai lu : « 11/7 » → 110/70 mmHg"
    hb = conv.T.fields[V + "T1V1.hemoglobine"]
    assert read_line(hb, "11.8 g/dL", 11.8, o) == "J'ai lu : 11.8 g/dL"
    assert read_line(hb, "13,2 g/dl", 13.2, o) == "J'ai lu : 13.2 g/dL"
    assert read_line(hb, "illisible ??", None, o) == "J'ai lu : « illisible ?? »"      # jamais « → — »
    assert field_label(V + "T1V1.age_probable_sa").endswith("· Âge probable")
    assert accentue("Etat des lochies") == "État des lochies" and accentue("A domicile") == "À domicile"
    assert accentue("A") == "A"                                                   # groupe sanguin intact
    ef = ExtractedField(section="grossesse_actuelle", field_key="visites.T1V1.poids_kg", status=FieldStatus.A_REVISER,
                        details_json=json.dumps({"flags": ["hors_plage"]}))
    assert doubt_reason(V + "T1V1.poids_kg", conv.T.fields[V + "T1V1.poids_kg"], ef, False, "fr") == \
        "valeur hors plage habituelle"


@pytest.mark.parametrize("raw,key,value", [
    ("11.8 g/dL", "hemoglobine", 11.8), ("13,2 g/dl", "hemoglobine", 13.2), ("0.8 g/L", "glycemie", 80.0),
    ("247k", "plaquettes", 247000.0), ("12,5", "hemoglobine", 12.5), ("120/80 mmHg", "ta", {"sys": 120, "dia": 80}),
    ("12/8 mm Hg", "ta", {"sys": 120, "dia": 80}), ("93 mg/dL", "glycemie", 93.0),
])
def test_normalisation_unites_avec_barre(raw, key, value):
    from app.templates.normalize import interpret
    assert interpret(conv.T.fields[V + "T1V1." + key], raw).value == value


def test_bonjour_alors_qu_un_dossier_attend(client, fake_wa):
    seeded(fake_wa)
    say(client, "bonjour")
    g = fake_wa.sent[-1]
    assert body_of(g) == "Bonjour ! Un dossier attend votre vérification (5 questions)."
    assert [i.split("|")[0] for i in ids(g)] == ["GO", "LATER"]
    press(client, find_id(g, "GO"))
    assert "Question 1/5" in body_of(fake_wa.sent[-1])
    say(client, "salut")                                                    # en pleine révision
    assert "(5 questions)" in body_of(fake_wa.sent[-1])
    press(client, find_id(fake_wa.sent[-1], "GO"))
    assert "Question 1/5" in body_of(fake_wa.sent[-1])


def test_page_difficile_a_lire(client, fake_wa):
    with SessionLocal() as db:
        mw = Midwife(wa_id=MIDWIFE)
        db.add(mw)
        db.flush()
        rec = Record(midwife_id=mw.id, status=S.A_REVISER)
        db.add(rec)
        db.flush()
        keys = [k for k in conv.T.stored_fields if k.startswith(V)][:30]
        for k in keys[:24]:                                                 # 24 incertains sur 30 = 80 %
            conv.set_field(db, rec, k, None, FieldStatus.A_REVISER, FieldSource.IA, 0.4, raw_text="?")
        for k in keys[24:]:
            conv.set_field(db, rec, k, "RAS", FieldStatus.CONNU, FieldSource.IA, 0.9)
        conv.on_record_ready(db, rec)
        db.commit()
    flush(fake_wa)
    m = fake_wa.sent[-1]
    assert "difficile à lire automatiquement (6 champs lus avec certitude)" in body_of(m)
    assert "les 10 questions les plus importantes" in body_of(m) and "24" not in body_of(m)
    assert [i.split("|")[0] for i in ids(m)] == ["REV", "PHOTO", "LATER"]   # 80 % pile : pas encore
    with SessionLocal() as db:
        rec = db.scalar(select(Record).where(Record.status == S.A_REVISER))
        conv.set_field(db, rec, keys[-1], None, FieldStatus.A_REVISER, FieldSource.IA, 0.4, raw_text="?")
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE))
        mw.conversation_state = None
        conv.on_record_ready(db, rec)
        db.commit()
    flush(fake_wa)
    m = fake_wa.sent[-1]
    assert [i.split("|")[0] for i in ids(m)] == ["PHOTO", "REV", "LATER"]   # > 80 % : photo d'abord
    assert "photo bien droite, page entière, bonne lumière." in body_of(m).lower()



# ------------------------------------------------------------------ aperçu de la zone douteuse
def _page_png() -> bytes:
    """Fausse page 600x1000 : rouge partout (pour vérifier le masquage)."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (600, 1000), (220, 20, 20)).save(buf, "PNG")
    return buf.getvalue()


def test_apercu_joint_a_la_question_avec_identites_masquees(client, fake_wa):
    import io
    from PIL import Image
    from app.storage import get_store
    with SessionLocal() as db:
        mw = Midwife(wa_id=MIDWIFE)
        db.add(mw)
        db.flush()
        rec = Record(midwife_id=mw.id, status=S.A_REVISER)
        db.add(rec)
        db.flush()
        key, sha = get_store().save(_page_png())
        rec.pages.append(Page(page_number=1, storage_key=key, sha256=sha, mime_type="image/png", size_bytes=10,
                              wa_message_id="wamid.apercu", captured_at=datetime.now(timezone.utc),
                              page_type="grossesse_actuelle"))
        db.flush()
        ef = conv.set_field(db, rec, V + "T1V1.hemoglobine", None, FieldStatus.ILLISIBLE, FieldSource.IA, 0.3,
                            raw_text="11.8 g/dL", details={"zone": [0.6296, 1.0]})
        ef.page_number = 1
        conv.set_field(db, rec, V + "T1V1.poids_kg", 60.0, FieldStatus.A_REVISER, FieldSource.IA, 0.5)  # sans zone
        conv.on_record_ready(db, rec)
        db.commit()
    flush(fake_wa)
    press(client, find_id(fake_wa.sent[-1], "REV"))
    preview, question = fake_wa.sent[-2], fake_wa.sent[-1]
    assert preview["type"] == "image" and preview["image"]["id"] == "media.1"
    assert preview["image"]["caption"].startswith("Zone où j'ai un doute : Grossesse actuelle")
    assert "_preview" not in preview                                      # référence interne jamais envoyée
    assert "Question 1/2" in body_of(question)
    img = Image.open(io.BytesIO(fake_wa.uploads[0])).convert("RGB")
    w, h = img.size
    # bande 0.63-1.0 (+ marge 3 %) : la ligne « Examen fait par » (0.82-0.91) est masquée en gris
    top = 0.6296 - 0.03
    y_mask = int((0.86 - top) / (1 - top) * h)
    assert img.getpixel((w // 2, y_mask))[0] < 160 and abs(img.getpixel((w // 2, y_mask))[1] - 120) < 20
    assert img.getpixel((w // 2, 5))[0] > 180                              # hors zone d'identité : intact
    # question suivante : champ sans zone connue -> pas d'aperçu
    n_uploads = len(fake_wa.uploads)
    press(client, find_id(question, "CONF"))
    assert fake_wa.sent[-1]["type"] == "interactive" and len(fake_wa.uploads) == n_uploads


def test_apercu_reference_seule_en_base_et_desactivable(client, fake_wa, monkeypatch):
    from app.config import get_settings
    from app.models import OutboundMessage
    seeded(fake_wa)
    with SessionLocal() as db:                          # la démo donne une zone à chaque champ douteux
        rec = db.scalar(select(Record).where(Record.status == S.A_REVISER))
        for f in rec.fields:
            if f.is_current and f.source == FieldSource.IA and f.status != FieldStatus.CONNU:
                f.page_number = 1
        db.commit()
    press(client, find_id(fake_wa.sent[-1], "OKLU"))
    assert fake_wa.sent[-2]["type"] == "image" and len(fake_wa.uploads) == 1
    with SessionLocal() as db:
        stored = [json.loads(m.payload_json) for m in db.scalars(select(OutboundMessage)).all()
                  if json.loads(m.payload_json)["type"] == "image"]
    assert stored and set(stored[0]["_preview"]) == {"record_id", "page_number", "zone"}
    assert "id" not in stored[0]["image"] and len(json.dumps(stored[0])) < 600   # aucune image en base
    monkeypatch.setattr(get_settings(), "whatsapp_apercus", False)
    n = len(fake_wa.sent)
    press(client, find_id(fake_wa.sent[-1], "CONF"))
    assert all(m["type"] != "image" for m in fake_wa.sent[n:])



# ------------------------------------------------------------------ résumé lisible (« Voici ce que j'ai lu »)
def _record_from_gt(pages: list[int], removed: dict[int, list[str]] | None = None) -> str:
    """Dossier A_REVISER construit comme par l'ai_worker depuis la vérité terrain (champs CONNU),
    avec un doute sur le premier champ texte de la dernière page."""
    from app.services.ai_worker import excluded_identifiers
    from app.storage import get_store
    from app.templates.normalize import interpret
    with SessionLocal() as db:
        mw = db.scalar(select(Midwife).where(Midwife.wa_id == MIDWIFE)) or Midwife(wa_id=MIDWIFE)
        db.add(mw)
        db.flush()
        rec = Record(midwife_id=mw.id, status=S.A_REVISER)
        db.add(rec)
        db.flush()
        for n, pdf_page in enumerate(pages, 1):
            gt = json.loads((GT_DIR / f"specimen_p{pdf_page:02d}.json").read_text(encoding="utf-8"))
            key, sha = get_store().save(b"\xff\xd8" + bytes([n]))
            rec.pages.append(Page(page_number=n, storage_key=key, sha256=sha, mime_type="image/jpeg", size_bytes=3,
                                  wa_message_id=f"gt-{uuid.uuid4().hex}", captured_at=datetime.now(timezone.utc),
                                  page_type=gt["page_type"], identifiers_excluded=json.dumps(
                                      excluded_identifiers(gt["page_type"], (removed or {}).get(n, [])))))
            for k, v in gt["fields"].items():
                f = conv.T.fields[k]
                raw = gt["raw"].get(k)
                value = interpret(f, raw).value if raw is not None and not f.is_checkbox else v
                ef = conv.set_field(db, rec, k, value, FieldStatus.CONNU, FieldSource.IA, 0.9, raw_text=raw)
                ef.page_number = n
        doubt = next(k for k in gt["fields"] if conv.T.fields[k].type == "int")
        ef = conv.set_field(db, rec, doubt, None, FieldStatus.A_REVISER, FieldSource.IA, 0.4, raw_text="?")
        ef.page_number = len(pages)
        db.flush()
        conv.on_record_ready(db, rec)
        db.commit()
        return rec.id


def test_resume_lisible_patiente4_sans_nom(client, fake_wa):
    rid = _record_from_gt([25, 26], removed={1: ["couverture.nom_parturiente"]})
    flush(fake_wa)
    texts = [body_of(m) for m in fake_wa.sent if m["type"] == "text"]
    p1 = next(t for t in texts if t.startswith("Voici ce que j'ai lu (page 1 – Couverture)"))
    for expected in ("N° de la fiche : 2026-995-004", "Province : Azilal",
                     "Nom de l'établissement sanitaire : CSCA Ait Mhamed",
                     "Type de l'établissement sanitaire : CSCA", "Mode de la couverture : Fixe",
                     "Grossesse classée à risque : non cochée",
                     "Non enregistré (confidentialité) : nom de la patiente"):
        assert expected in p1, expected
    assert p1.index("N° de la fiche") < p1.index("Province")                 # priorité clinique
    p2 = next(t for t in texts if t.startswith("Voici ce que j'ai lu (page 2 – Identification et antécédents)"))
    assert "Âge : 26 ans" in p2 and "Antécédents obstétricaux · Gestation : 5" in p2
    assert "Antécédents de la femme · Médicaux : RAS" in p2
    assert len(p2.splitlines()) <= 1 + 15 + 3 and "… et " in p2              # 15 lignes max + « … et N autres »
    assert "Non enregistré (confidentialité) : CIN, adresse, téléphone, nom du mari" in p2
    assert "À vérifier : 1 –" in p2
    assert all(len(t) <= 4096 for t in texts)
    buttons = fake_wa.sent[-1]
    assert [i.split("|")[0] for i in ids(buttons)] == ["OKLU", "CORRLU", "MORE"]
    # le nom (et les autres identifiants) n'apparaissent NULLE PART
    idents = set()
    for n in (25, 26, 27, 28):
        idents |= {v for v in json.loads((GT_DIR / f"specimen_p{n:02d}.json").read_text(encoding="utf-8"))[
            "_identifiants"].values() if v}
    assert "Benali Nadia" in idents
    assert find_leaks({"fields": {}, "messages": fake_wa.sent}, idents) == []
    assert all("Benali" not in json.dumps(m, ensure_ascii=False) for m in fake_wa.sent)

    # Voir plus : les lignes suivantes, numérotation continue
    press(client, find_id(buttons, "MORE"))
    more = body_of(fake_wa.sent[-2])
    first_num = int(more.splitlines()[1].split(".")[0])
    assert more.startswith("Voici ce que j'ai lu (page 2") and first_num > 16
    # Corriger une ligne : numéro -> nouvelle valeur -> retour au résumé
    press(client, find_id(fake_wa.sent[-1], "CORRLU"))
    assert "numéro de la ligne" in body_of(fake_wa.sent[-1])
    say(client, "2")                                                          # ligne 2 = Région
    assert "Tapez la bonne valeur pour : Couverture · Région" in body_of(fake_wa.sent[-1])
    say(client, "Béni Mellal-Khénifra")
    assert [i.split("|")[0] for i in ids(fake_wa.sent[-1])][:2] == ["OKLU", "CORRLU"]
    # Tout est juste : les lignes montrées sont confirmées, puis la question restante
    press(client, find_id(fake_wa.sent[-1], "OKLU"))
    assert "Question 1/1" in body_of(fake_wa.sent[-1])
    f = current(rid)
    assert f["couverture.region"].source == FieldSource.SAGE_FEMME
    assert json.loads(f["couverture.region"].value_json) == "Béni Mellal-Khénifra"
    assert f["couverture.province"].source == FieldSource.SAGE_FEMME              # montrée -> confirmée
    # commande RESUME : renvoie ce que j'ai lu
    say(client, "RESUME")
    assert any(body_of(m).startswith("Voici ce que j'ai lu (page 1") for m in fake_wa.sent[-3:])
