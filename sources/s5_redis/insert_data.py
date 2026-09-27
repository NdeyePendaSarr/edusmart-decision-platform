"""
sources/s5_redis/insert_data.py — Chargement de la Source 5 (Lot L2-e)
=====================================================================

    1. FLUSHDB : la base Redis d'EduSmart est vidée (db dédiée, snapshot figé
       régénéré avant chaque extraction : décision validée).
    2. Écriture du snapshot par pipeline (HSET, SET, ZADD, RPUSH) + EXPIRE
       pour les clés ayant une durée de vie. Les sessions de l'anomalie E01
       n'ont PAS de TTL : elles ne disparaîtront jamais d'elles-mêmes.
    3. Contrôle : DBSIZE = nombre de clés du snapshot.

Les TTL courent à partir du chargement (heure réelle) : une session chargée
reste visible 24 h, largement de quoi exécuter l'ETL.

Exécution : python -m sources.s5_redis.insert_data   (conteneur redis démarré, ~2 s)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common.config import ConfigError, get_settings
from common.logger import get_logger, log_step
from sources.s5_redis.anomalies import SOURCE
from sources.s5_redis.create_source import flush
from sources.s5_redis.generate_data import SNAPSHOT_FILENAME

logger = get_logger("s5_insert")


class InsertError(Exception):
    """Erreur bloquante pendant le chargement."""


def load_snapshot(path: Path) -> dict:
    if not path.exists():
        raise InsertError(f"{path} introuvable (lancez d'abord generate_data)")
    return json.loads(path.read_text(encoding="utf-8"))


def load_into(client, snapshot: dict) -> int:
    """Charge le snapshot dans `client` (redis.Redis). Retourne le nombre de clés."""
    flush(client)
    pipe = client.pipeline(transaction=False)
    for key, item in snapshot.items():
        t, v = item["type"], item["value"]
        if t == "hash":
            pipe.hset(key, mapping=v)
        elif t == "string":
            pipe.set(key, v)
        elif t == "zset":
            pipe.zadd(key, v)
        elif t == "list":
            pipe.rpush(key, *v)                    # ordre conservé : index 0 = notification la plus récente
        else:
            raise InsertError(f"Type inconnu pour {key} : {t}")
        if item["ttl"]:
            pipe.expire(key, item["ttl"])
    pipe.execute()
    n = client.dbsize()
    if n != len(snapshot):
        raise InsertError(f"{n} clés dans Redis, {len(snapshot)} dans le snapshot")
    return n


def main() -> int:
    settings = get_settings()
    try:
        import redis
        snapshot = load_snapshot(settings.paths.generated_dir / SOURCE / SNAPSHOT_FILENAME)
        client = redis.Redis(**settings.redis.connect_kwargs())
        try:
            with log_step(logger, "Chargement du snapshot Redis"):
                n = load_into(client, snapshot)
        finally:
            client.close()
        logger.info("%d clés chargées dans Redis (db %d)", n, settings.redis.db)
        logger.info("Étape suivante : python -m sources.s5_redis.verify_source (porte G1)")
        return 0
    except (InsertError, ConfigError) as exc:
        logger.error("%s", exc)
        return 1
    except ImportError as exc:
        logger.error("Pilote manquant : %s (pip install -r requirements.txt)", exc)
        return 1
    except Exception:
        logger.exception("Échec du chargement de la Source 5")
        return 2


if __name__ == "__main__":
    sys.exit(main())
