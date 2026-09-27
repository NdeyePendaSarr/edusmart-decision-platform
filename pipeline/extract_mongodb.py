"""
pipeline/extract_mongodb.py — Extraction de la Source 4 MongoDB (Lot L4)
=======================================================================

Lit la collection events en flux (tri par _id) et conserve CHAQUE DOCUMENT
ENTIER en JSON étendu MongoDB (mode relaxed) :
    - une date reste une date  : {"$date": "2026-09-12T08:25:14Z"}
    - un texte reste un texte  : "12/09/2026 08:25:14"   (anomalie D08)
    - un nombre reste un nombre : 1757665514000
Le schéma flexible (champs présents ou absents selon le type) est donc
intégralement préservé ; il sera interprété en SQL dans la couche clean.
Colonnes de staging : _mongo_id, event_id (pour l'indexation), document (JSONB).

Exécution seule : python -m pipeline.extract_mongodb
"""

from __future__ import annotations

import sys

from common.config import get_settings
from pipeline.extract_common import extract_object
from pipeline.landing import Batch, new_batch_id
from pipeline.registry import get_object

SOURCE, COLLECTION = "s4_mongodb", "events"


def emplacement() -> str:
    c = get_settings().mongo
    return f"{c.host}:{c.port}/{c.database}.{COLLECTION}"


def document_json(doc: dict) -> str:
    from bson import json_util
    return json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS, ensure_ascii=False)


def extract(batch: Batch, meta=None, db=None) -> dict[str, int]:
    client = None
    if db is None:
        from pymongo import MongoClient
        cfg = get_settings().mongo
        client = MongoClient(cfg.uri(), serverSelectionTimeoutMS=5000)
        db = client[cfg.database]
    try:
        obj = get_object(SOURCE, COLLECTION)

        def rows():
            for doc in db[COLLECTION].find({}).sort("_id", 1).batch_size(5000):
                event_id = doc.get("event_id")
                yield [str(doc["_id"]), event_id if isinstance(event_id, str) else None, document_json(doc)]
        return {COLLECTION: extract_object(batch, obj, rows, emplacement(), meta)}
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    print(extract(Batch(new_batch_id())))
    sys.exit(0)
