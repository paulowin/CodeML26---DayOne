"""Page de vérification locale /verif."""
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import AccessLog, ExtractedField, FieldSource, FieldStatus, Midwife, Page, Record, RecordStatus
from app.storage import get_store
from eval.common import GT_DIR, load_manifest


@pytest.fixture
def local(client):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


def _record_p04(wrong: bool = True) -> str:
    """Dossier lu depuis la page spécimen 4 (patiente 1, accouchement) ; une valeur fausse « sûre »."""
    entry = next(e for e in load_manifest()["images"] if e["file"] == "dossiers_specimen_10_patientes-04.png")
    gt = json.loads((GT_DIR / "specimen_p04.json").read_text(encoding="utf-8"))
    with SessionLocal() as db:
        mw = Midwife(wa_id="2126000011")
        db.add(mw)
        db.flush()
        rec = Record(midwife_id=mw.id, status=RecordStatus.A_REVISER, extraction_model="qwen2.5vl:3b")
        db.add(rec)
        db.flush()
        key, _ = get_store().save(b"\xff\xd8image-p04")
        rec.pages.append(Page(page_number=1, storage_key=key, sha256=entry["sha256"], mime_type="image/png",
                              size_bytes=10, wa_message_id="wamid.verif", captured_at=datetime.now(timezone.utc),
                              page_type="accouchement"))
        for k, v in gt["fields"].items():
            if k == "accouchement.poids_naissance_g" and wrong:
                v = 3857                                            # faux mais affiché sûr
            section, fk = k.split(".", 1)
            rec.fields.append(ExtractedField(section=section, field_key=fk, value_json=json.dumps(v),
                                             raw_text=str(v), status=FieldStatus.CONNU, confidence=0.9,
                                             source=FieldSource.IA, page_number=1, is_current=True,
                                             details_json=json.dumps({"flags": ["lecture_cv"]})
                                             if isinstance(v, (bool, list)) else None))
        db.commit()
        return rec.id


def test_refuse_via_ngrok_et_hors_poste_local(client, local):
    assert local.get("/verif", headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 403
    assert client.get("/verif").status_code == 403                  # hôte « testclient » : pas le poste local
    assert local.get("/verif").status_code == 200


def test_cle_du_personnel_acceptee_meme_a_distance(client):
    from app.models import Role, Staff
    from app.security import hash_api_key
    with SessionLocal() as db:
        db.add(Staff(label="sup", role=Role.SUPERVISEUR, api_key_hash=hash_api_key("sup-verif")))
        db.commit()
    r = client.get("/verif?key=sup-verif", headers={"X-Forwarded-For": "203.0.113.7"})
    assert r.status_code == 200
    assert client.get("/verif?key=mauvaise").status_code == 401


def test_page_dossier_avec_attendu_et_sans_nom(local):
    rid = _record_p04()
    r = local.get(f"/verif/{rid}")
    assert r.status_code == 200
    page = r.text
    assert "Tazi" not in page and "Meryem" not in page              # le nom n'apparaît nulle part
    assert "Attendu" in page and "page du défi : dossiers_specimen_10_patientes-04.png" in page
    assert "Erreurs silencieuses (faux mais affiché sûr) : <b>1</b>" in page
    assert "class='faux'" in page and "class='juste'" in page
    assert "Poids à la naissance" in page and ">case<" in page and ">ia<" in page
    assert f"/verif/{rid}/pages/1/image" in page
    liste = local.get("/verif").text
    assert rid[:8] in liste and "A_REVISER" in liste


def test_image_dechiffree_et_tracee(local):
    rid = _record_p04()
    r = local.get(f"/verif/{rid}/pages/1/image")
    assert r.status_code == 200 and r.content == b"\xff\xd8image-p04" and r.headers["cache-control"] == "no-store"
    with SessionLocal() as db:
        actions = [a.action for a in db.scalars(select(AccessLog).where(AccessLog.record_id == rid))]
    assert actions == ["verif_image"]                                # chaque image affichée est tracée


def test_bandeau_rouge_des_alertes_sur_valeurs_confirmees(local):
    rid = _record_p04()
    assert "Signes d'alerte" not in local.get(f"/verif/{rid}").text
    with SessionLocal() as db:
        rec = db.get(Record, rid)
        rec.fields.append(ExtractedField(section="grossesse_actuelle", field_key="visites.M8.hemoglobine",
                                         value_json="10.9", status=FieldStatus.CONNU, confidence=1.0,
                                         source=FieldSource.SAGE_FEMME, page_number=1, is_current=True))
        db.commit()
    page = local.get(f"/verif/{rid}").text
    assert "class='alerte'" in page and "anémie (Hb 10,9 g/dL)" in page
    assert "Aide à la décision, pas un diagnostic" in page
