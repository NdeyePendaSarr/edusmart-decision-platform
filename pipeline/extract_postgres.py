"""
pipeline/extract_postgres.py — Extraction de la Source 1 PostgreSQL (Lot L4)
===========================================================================

Lit les 5 tables de edusmart_academic dans UNE transaction en lecture seule
(REPEATABLE READ) : les 5 tables sont extraites au même instant logique, même
si la base est modifiée pendant l'extraction. Les valeurs sont converties en
texte PAR POSTGRESQL (col::text) : c'est sa représentation brute qui arrive en
staging (booléens « true/false », montants « 350000.00 »...).
Curseur serveur : les 40 150 paiements ne sont jamais tous en mémoire.

Exécution seule : python -m pipeline.extract_postgres   (crée un lot sans journal)
"""

from __future__ import annotations

import sys

from common.config import get_settings
from pipeline.extract_common import extract_object
from pipeline.landing import Batch, new_batch_id
from pipeline.registry import objects_of

SOURCE = "s1_postgresql"


def emplacement() -> str:
    c = get_settings().pg_source
    return f"{c.host}:{c.port}/{c.database}"


def extract(batch: Batch, meta=None, conn=None) -> dict[str, int]:
    import psycopg2
    from psycopg2 import sql

    propre = conn is None
    conn = conn or psycopg2.connect(**get_settings().pg_source.connect_kwargs())
    try:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)
        resultats = {}
        for obj in objects_of(SOURCE):
            def rows(obj=obj):
                requete = sql.SQL("SELECT {cols} FROM {tbl} ORDER BY {cle}").format(
                    cols=sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in obj.colonnes),
                    tbl=sql.Identifier(obj.objet), cle=sql.Identifier(obj.cle_ordre))
                with conn.cursor(name=f"extract_{obj.objet}") as cur:     # curseur côté serveur
                    cur.itersize = 5000
                    cur.execute(requete)
                    for row in cur:
                        yield list(row)
            resultats[obj.objet] = extract_object(batch, obj, rows, emplacement(), meta)
        conn.rollback()                                                  # lecture seule : rien à valider
        return resultats
    finally:
        if propre:
            conn.close()


if __name__ == "__main__":
    print(extract(Batch(new_batch_id())))
    sys.exit(0)
