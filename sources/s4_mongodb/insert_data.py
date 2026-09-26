"""
sources/s4_mongodb/insert_data.py — Chargement de la Source 4 (Lot L2-d)
=======================================================================

Enchaînement
    1. (Re)création de la collection events : validateur $jsonSchema
       (validationLevel "moderate", validationAction "error") + index.
    2. Insertion par lots de 10 000 avec bypass_document_validation=True :
       les anomalies pédagogiques sont acceptées au chargement initial.
    3. Contrôle : nombre de documents en base = nombre de lignes du fichier.

Résultat équivalent au NOT VALID de PostgreSQL : l'existant n'est pas
vérifié, mais toute nouvelle insertion invalide est refusée (démontré par le
test d'intégration).

_id : laissé à MongoDB (ObjectId). L'identifiant métier est event_id ; un
doublon (D09) a le même event_id mais un _id différent.

Exécution : python -m sources.s4_mongodb.insert_data   (~30 s, conteneur mongo démarré)
"""

from __future__ import annotations

import sys
from pathlib import Path

from common.config import ConfigError, get_settings
from common.logger import get_logger, log_step
from sources.s4_mongodb.anomalies import SOURCE
from sources.s4_mongodb.create_source import COLLECTION, create_collection
from sources.s4_mongodb.generate_data import EVENTS_FILENAME, read_events

logger = get_logger("s4_insert")
BATCH_SIZE = 10_000


class InsertError(Exception):
    """Erreur bloquante pendant le chargement."""


def load_into(db, path: Path, with_validator: bool = True) -> int:
    """Charge le fichier dans `db` (vraie base ou mongomock). Retourne le nombre de documents."""
    if not path.exists():
        raise InsertError(f"{path} introuvable (lancez d'abord generate_data)")
    collection = create_collection(db, with_validator=with_validator)
    total, batch = 0, []
    for doc in read_events(path):
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            collection.insert_many(batch, ordered=False, bypass_document_validation=True)
            total += len(batch)
            batch = []
    if batch:
        collection.insert_many(batch, ordered=False, bypass_document_validation=True)
        total += len(batch)
    en_base = collection.count_documents({})
    if en_base != total:
        raise InsertError(f"{en_base} documents en base, {total} dans le fichier")
    return total


def main() -> int:
    settings = get_settings()
    try:
        from pymongo import MongoClient
        cfg = settings.mongo
        client = MongoClient(cfg.uri(), serverSelectionTimeoutMS=5000)
        try:
            with log_step(logger, f"Chargement de {COLLECTION} ({cfg.safe_uri()})"):
                n = load_into(client[cfg.database], settings.paths.generated_dir / SOURCE / EVENTS_FILENAME)
        finally:
            client.close()
        logger.info("%d documents chargés dans %s.%s", n, cfg.database, COLLECTION)
        logger.info("Étape suivante : python -m sources.s4_mongodb.verify_source (porte G1)")
        return 0
    except (InsertError, ConfigError) as exc:
        logger.error("%s", exc)
        return 1
    except ImportError as exc:
        logger.error("Pilote manquant : %s (pip install -r requirements.txt)", exc)
        return 1
    except Exception:
        logger.exception("Échec du chargement de la Source 4 (relancer : le script est idempotent)")
        return 2


if __name__ == "__main__":
    sys.exit(main())
