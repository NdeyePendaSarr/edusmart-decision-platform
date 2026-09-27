"""
pipeline/extract_mysql.py — Extraction de la Source 2 MySQL (Lot L4)
===================================================================

Lit les 6 tables de edusmart_learning dans une transaction
« WITH CONSISTENT SNAPSHOT, READ ONLY ». Les valeurs sont converties en texte
PAR MYSQL (CAST(... AS CHAR)) : valeurs exactes, casse comprise. La collation
utf8mb4_unicode_ci n'intervient pas, puisqu'aucun GROUP BY ni DISTINCT n'est
fait ici (piège documenté en L2-b). Curseur non bufferisé : les 299 049 notes
sont lues en flux.

Exécution seule : python -m pipeline.extract_mysql
"""

from __future__ import annotations

import sys

from common.config import get_settings
from pipeline.extract_common import extract_object
from pipeline.landing import Batch, new_batch_id
from pipeline.registry import objects_of

SOURCE = "s2_mysql"


def emplacement() -> str:
    c = get_settings().mysql
    return f"{c.host}:{c.port}/{c.database}"


def extract(batch: Batch, meta=None, conn=None) -> dict[str, int]:
    import pymysql

    propre = conn is None
    conn = conn or pymysql.connect(**get_settings().mysql.connect_kwargs(), autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        resultats = {}
        for obj in objects_of(SOURCE):
            def rows(obj=obj):
                colonnes = ", ".join(f"CAST(`{c}` AS CHAR)" for c in obj.colonnes)
                with conn.cursor(pymysql.cursors.SSCursor) as cur:        # lecture en flux
                    cur.execute(f"SELECT {colonnes} FROM `{obj.objet}` ORDER BY `{obj.cle_ordre}`")
                    for row in cur:
                        yield list(row)
            resultats[obj.objet] = extract_object(batch, obj, rows, emplacement(), meta)
        conn.rollback()
        return resultats
    finally:
        if propre:
            conn.close()


if __name__ == "__main__":
    print(extract(Batch(new_batch_id())))
    sys.exit(0)
