"""
sources/s4_mongodb/create_source.py — Structure de la Source 4 (Lot L2-d)
========================================================================

Base edusmart_mobile, collection events (PDF Source 4).

Ce module définit :
    1. Les 14 types d'événements et le SCHÉMA FLEXIBLE du PDF : chaque type
       a ses champs de contexte (module/cours/quiz) et ses métadonnées propres
       (LOGIN n'a pas de quiz_code ; QUIZ_SUBMITTED porte score et attempt ;
       VIDEO_STARTED porte video_quality et buffer_time).
    2. Un VALIDATEUR $jsonSchema appliqué comme la contrainte NOT VALID de
       PostgreSQL :
         validationLevel = "moderate", validationAction = "error"
         + chargement initial avec bypass_document_validation=True
       -> les anomalies pédagogiques sont chargées, mais toute NOUVELLE
          insertion invalide est refusée.
    3. Les index (event_id NON unique, car des doublons sont volontaires).
    4. violates_schema(doc) : l'équivalent Python EXACT du validateur. La
       porte G1 compare le nombre de documents invalides selon MongoDB et
       selon Python : s'ils diffèrent, le validateur est mal écrit.

Exécution : python -m sources.s4_mongodb.create_source   (conteneur mongo démarré)
"""

from __future__ import annotations

import re
import sys
from datetime import datetime

from common.config import ConfigError, get_settings
from common.logger import get_logger

logger = get_logger("s4_create")

SOURCE = "s4_mongodb"
COLLECTION = "events"

EVENT_TYPES: tuple[str, ...] = (
    "LOGIN", "LOGOUT", "COURSE_OPENED", "COURSE_COMPLETED", "VIDEO_STARTED", "VIDEO_FINISHED",
    "QUIZ_STARTED", "QUIZ_SUBMITTED", "RESOURCE_DOWNLOADED", "SEARCH", "PROFILE_UPDATED",
    "PAYMENT_STARTED", "PAYMENT_SUCCESS", "PAYMENT_FAILED",
)

# Champs présents dans TOUS les documents propres (ordre du PDF, hors _id et contexte)
STANDARD_FIELDS: tuple[str, ...] = (
    "event_id", "student_code", "timestamp", "event_type", "device", "operating_system", "app_version",
    "ip_address", "city", "country", "session_id", "duration_seconds", "success", "metadata",
)

# Schéma flexible : champs de contexte selon le type d'événement
CONTEXT_FIELDS: dict[str, tuple[str, ...]] = {
    **{t: () for t in ("LOGIN", "LOGOUT", "SEARCH", "PROFILE_UPDATED",
                       "PAYMENT_STARTED", "PAYMENT_SUCCESS", "PAYMENT_FAILED")},
    **{t: ("module_code", "course_code") for t in ("COURSE_OPENED", "COURSE_COMPLETED", "VIDEO_STARTED",
                                                   "VIDEO_FINISHED", "RESOURCE_DOWNLOADED")},
    "QUIZ_STARTED": ("module_code", "course_code", "quiz_code"),
    "QUIZ_SUBMITTED": ("module_code", "course_code", "quiz_code"),
}

# Métadonnées spécifiques (en plus de "network", présent partout)
METADATA_FIELDS: dict[str, tuple[str, ...]] = {
    "LOGIN": ("method",), "LOGOUT": (), "COURSE_OPENED": ("progress",), "COURSE_COMPLETED": ("progress",),
    "VIDEO_STARTED": ("video_quality", "buffer_time"), "VIDEO_FINISHED": ("watched_percent",),
    "QUIZ_STARTED": ("attempt",), "QUIZ_SUBMITTED": ("score", "attempt"),
    "RESOURCE_DOWNLOADED": ("resource_type", "size_mb"), "SEARCH": ("query", "results_count"),
    "PROFILE_UPDATED": ("field",),
    "PAYMENT_STARTED": ("amount", "currency", "method", "reference", "tranche"),
    "PAYMENT_SUCCESS": ("amount", "currency", "method", "reference", "tranche"),
    "PAYMENT_FAILED": ("amount", "currency", "method", "reference", "tranche", "error"),
}

OPERATING_SYSTEMS = ("Android", "iOS")          # PDF : « Android, iOS »
APP_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_APP_VERSION_RE = re.compile(APP_VERSION_PATTERN)

# -----------------------------------------------------------------------------
# Validateur MongoDB ($jsonSchema)
# -----------------------------------------------------------------------------
JSON_SCHEMA: dict = {
    "bsonType": "object",
    "required": list(STANDARD_FIELDS),
    "properties": {
        "event_id": {"bsonType": "string"},
        "student_code": {"bsonType": "string"},
        "timestamp": {"bsonType": "date"},
        "event_type": {"enum": list(EVENT_TYPES)},
        "module_code": {"bsonType": "string"},
        "course_code": {"bsonType": "string"},
        "quiz_code": {"bsonType": "string"},
        "device": {"bsonType": "string"},
        "operating_system": {"enum": list(OPERATING_SYSTEMS)},
        "app_version": {"bsonType": "string", "pattern": APP_VERSION_PATTERN},
        "ip_address": {"bsonType": "string"},
        "city": {"bsonType": "string"},
        "country": {"bsonType": "string"},
        "session_id": {"bsonType": "string"},
        "duration_seconds": {"bsonType": ["int", "long"], "minimum": 0},
        "success": {"bsonType": "bool"},
        "metadata": {"bsonType": "object"},
    },
}
VALIDATOR = {"$jsonSchema": JSON_SCHEMA}

INDEXES: tuple[tuple[str, list[tuple[str, int]]], ...] = (
    ("idx_event_id", [("event_id", 1)]),                       # NON unique : doublons volontaires (D09)
    ("idx_student_timestamp", [("student_code", 1), ("timestamp", 1)]),
    ("idx_session", [("session_id", 1)]),
    ("idx_event_type", [("event_type", 1)]),
    ("idx_timestamp", [("timestamp", 1)]),
)


def violates_schema(doc: dict) -> bool:
    """Équivalent Python EXACT de JSON_SCHEMA (utilisé par G1 pour contrôler le validateur)."""
    if any(f not in doc for f in STANDARD_FIELDS):
        return True
    strings = ("event_id", "student_code", "device", "ip_address", "city", "country", "session_id",
               "module_code", "course_code", "quiz_code")
    if any(f in doc and not isinstance(doc[f], str) for f in strings):
        return True
    if not isinstance(doc["timestamp"], datetime):
        return True
    if doc["event_type"] not in EVENT_TYPES or doc["operating_system"] not in OPERATING_SYSTEMS:
        return True
    if not isinstance(doc["app_version"], str) or not _APP_VERSION_RE.match(doc["app_version"]):
        return True
    d = doc["duration_seconds"]
    if isinstance(d, bool) or not isinstance(d, int) or d < 0:
        return True
    return not isinstance(doc["success"], bool) or not isinstance(doc["metadata"], dict)


def create_collection(db, with_validator: bool = True):
    """(Re)crée la collection events et ses index. `with_validator=False` : tests avec mongomock."""
    if COLLECTION in db.list_collection_names():
        db.drop_collection(COLLECTION)
    if with_validator:
        db.create_collection(COLLECTION, validator=VALIDATOR, validationLevel="moderate", validationAction="error")
    else:
        db.create_collection(COLLECTION)
    collection = db[COLLECTION]
    for name, keys in INDEXES:
        collection.create_index(keys, name=name)
    return collection


def main() -> int:
    try:
        from pymongo import MongoClient
        cfg = get_settings().mongo
        client = MongoClient(cfg.uri(), serverSelectionTimeoutMS=5000)
        try:
            create_collection(client[cfg.database])
            logger.info("Collection %s.%s créée : validateur (moderate / error) + %d index",
                        cfg.database, COLLECTION, len(INDEXES))
        finally:
            client.close()
        return 0
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Création de la collection impossible")
        return 2


if __name__ == "__main__":
    sys.exit(main())
