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

SOURCE = "s5_redis"


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
