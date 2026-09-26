"""
Test d'intégration — Source 4 sur une VRAIE base MongoDB (conteneur edusmart_mongo).
Désactivé par défaut. Pour l'exécuter :
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s4_mongodb_integration.py -v
ATTENTION : recharge entièrement la collection events (~1 min).
"""
import os
from datetime import datetime

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def loaded():
    from common.referential import main as build_ref
    from sources.s4_mongodb import generate_data, insert_data
    assert build_ref() == 0
    assert generate_data.main() == 0
    assert insert_data.main() == 0


@pytest.fixture
def collection(loaded):
    from pymongo import MongoClient
    from common.config import get_settings
    cfg = get_settings().mongo
    client = MongoClient(cfg.uri(), serverSelectionTimeoutMS=5000)
    yield client[cfg.database]["events"]
    client[cfg.database]["events"].delete_many({"event_id": {"$regex": "^TEST-"}})
    client.close()


def _doc_valide(**modifs):
    doc = {"event_id": "TEST-1", "student_code": "LMS-000001", "timestamp": datetime(2026, 9, 15, 10, 0),
           "event_type": "LOGIN", "device": "Tecno Spark 10", "operating_system": "Android", "app_version": "2.4.1",
           "ip_address": "197.210.15.24", "city": "Dakar", "country": "Sénégal", "session_id": "TEST-SESSION",
           "duration_seconds": 3, "success": True, "metadata": {"network": "4G"}}
    doc.update(modifs)
    return doc


def test_porte_g1(loaded):
    from sources.s4_mongodb import verify_source
    assert verify_source.main() == 0


def test_document_valide_accepte(collection):
    collection.insert_one(_doc_valide())
    assert collection.count_documents({"event_id": "TEST-1"}) == 1


@pytest.mark.parametrize("modifs", [
    {"operating_system": "ANDROID"},     # D06
    {"app_version": "v2.4"},             # D05
    {"duration_seconds": -5},            # D11
    {"timestamp": "2026-09-15T10:00:00"},  # D08
    {"student_code": None},              # D07
])
def test_nouveau_document_invalide_refuse(collection, modifs):
    """Comme NOT VALID en PostgreSQL : l'existant est toléré, le nouveau invalide est refusé."""
    from pymongo.errors import WriteError
    with pytest.raises(WriteError) as exc:
        collection.insert_one(_doc_valide(event_id="TEST-2", **modifs))
    assert exc.value.code == 121  # DocumentValidationFailure


def test_rechargement_idempotent(loaded):
    from sources.s4_mongodb import insert_data, verify_source
    assert insert_data.main() == 0
    assert verify_source.main() == 0
