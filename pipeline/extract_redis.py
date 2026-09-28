"""
pipeline/extract_redis.py — Extraction de la Source 5 Redis (Lot L4)
===================================================================

Redis est volatile : l'extraction FIGE son contenu au moment du lot.
Une ligne par clé : cle, type_redis, valeur (JSON), ttl (secondes restantes, -1 = aucun).
    string -> "COURSE-154"              hash -> {"status": "ONLINE", ...}
    list   -> ["msg récent", ...]       zset -> [["LMS-000145", 98.0], ...] (score décroissant)
À exécuter juste après sources.s5_redis.insert_data (snapshot régénéré, TTL de 24 h).

Exécution seule : python -m pipeline.extract_redis
"""

from __future__ import annotations

import json
import sys

from common.config import get_settings
from pipeline.extract_common import extract_object
from pipeline.landing import Batch, new_batch_id
from pipeline.registry import get_object
from common.logger import get_logger

SOURCE = "s5_redis"
logger = get_logger("extract_redis")
# Clés à durée de vie courte : leur absence signale un snapshot trop ancien (C24)
CLES_TEMOINS = {"statistics:today": 3600, "online_users": None}


def controler_fraicheur(client) -> list[str]:
    """
    Avertissements (non bloquants) si le snapshot a commencé à expirer.
    Le pipeline ne régénère JAMAIS une source : il signale, et l'on relance
    python -m sources.s5_redis.insert_data juste avant le pipeline.
    """
    alertes = []
    for cle, ttl_initial in CLES_TEMOINS.items():
        ttl = client.ttl(cle)
        if ttl == -2:
            alertes.append(f"clé {cle} absente : expirée depuis la génération du snapshot")
        elif ttl_initial and 0 <= ttl < ttl_initial // 4:
            alertes.append(f"clé {cle} expire dans {ttl} s")
    return alertes


def emplacement() -> str:
    c = get_settings().redis
    return f"{c.host}:{c.port}/db{c.db}"


def valeur(client, cle: str, type_redis: str):
    if type_redis == "string":
        return client.get(cle)
    if type_redis == "hash":
        return client.hgetall(cle)
    if type_redis == "list":
        return client.lrange(cle, 0, -1)
    if type_redis == "zset":
        return [[m, s] for m, s in client.zrevrange(cle, 0, -1, withscores=True)]
    if type_redis == "set":
        return sorted(client.smembers(cle))
    return None


def extract(batch: Batch, meta=None, client=None) -> dict[str, int]:
    propre = client is None
    if propre:
        import redis
        client = redis.Redis(**get_settings().redis.connect_kwargs())
    try:
        obj = get_object(SOURCE, "keys")
        for alerte in controler_fraicheur(client):
            logger.warning("Snapshot Redis périmé : %s. Relancez python -m sources.s5_redis.insert_data "
                           "juste avant le pipeline pour une porte G3 complète.", alerte)
        cles = sorted(client.scan_iter(count=1000))                     # ordre stable

        def rows():
            for cle in cles:
                t = client.type(cle)
                if t == "none":                                         # expirée entre le SCAN et la lecture
                    continue
                yield [cle, t, json.dumps(valeur(client, cle, t), ensure_ascii=False, sort_keys=True),
                       str(client.ttl(cle))]
        return {"keys": extract_object(batch, obj, rows, emplacement(), meta)}
    finally:
        if propre:
            client.close()


if __name__ == "__main__":
    print(extract(Batch(new_batch_id())))
    sys.exit(0)
