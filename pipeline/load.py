"""
pipeline/load.py — Chargement en staging (Lot L4)
================================================

Pour chaque objet du lot (manifeste) :
    TRUNCATE staging.<table> ; COPY depuis data/landing/<batch>/<source>/<objet>.csv
dans UNE transaction par table : si le COPY échoue, la table garde son
contenu précédent (jamais de table à moitié chargée).
Contrôle bloquant : lignes en staging = lignes extraites (manifeste).

Politique : le staging ne contient que le DERNIER lot (TRUNCATE). L'historique
des lots reste disponible dans data/landing/ et dans meta.etl_execution_log.
Recharger le même lot donne le même résultat (idempotence).

Exécution seule (dernier lot extrait) : python -m pipeline.load
"""

from __future__ import annotations

import sys

from common.config import get_settings
from common.logger import get_logger
from pipeline.landing import Batch, latest_batch, read_manifest
from pipeline.registry import NULL_MARKER, STAGING_SCHEMA, get_object

logger = get_logger("load")


class LoadError(Exception):
    """Écart entre les lignes extraites et les lignes chargées."""


def load_object(conn, batch: Batch, source: str, objet: str, attendu: int) -> int:
    from psycopg2 import sql
    obj = get_object(source, objet)
    table = sql.Identifier(STAGING_SCHEMA, obj.stg_table)
    copy = sql.SQL("COPY {t} ({c}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL {n}, ENCODING 'UTF8')").format(
        t=table, c=sql.SQL(", ").join(map(sql.Identifier, obj.toutes_colonnes)), n=sql.Literal(NULL_MARKER))
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("TRUNCATE {}").format(table))
            with batch.path(obj).open(encoding="utf-8", newline="") as handle:
                cur.copy_expert(copy.as_string(conn), handle)
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {} WHERE _batch_id = %s").format(table), (batch.batch_id,))
            charge = cur.fetchone()[0]
            if charge != attendu:
                raise LoadError(f"{source}.{objet} : {charge} lignes en staging, {attendu} extraites")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    logger.info("[LOAD]    %-14s %-16s %7d lignes -> staging.%s", source, objet, charge, obj.stg_table)
    return charge


def load(batch: Batch, sources: list[str] | None = None, meta=None, conn=None) -> dict[str, int]:
    """Charge les objets du manifeste (filtrés par source). Retourne {source.objet: lignes}."""
    import psycopg2
    manifest = read_manifest(batch)
    propre = conn is None
    conn = conn or psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        conn.set_client_encoding("UTF8")
        resultats = {}
        for cle, info in sorted(manifest["objets"].items()):
            if sources and info["source"] not in sources:
                continue
            if meta is None:
                resultats[cle] = load_object(conn, batch, info["source"], info["objet"], info["nb_lignes"])
            else:
                with meta.step(batch.batch_id, "LOAD", info["source"], info["objet"]) as step:
                    step.nb_lignes = load_object(conn, batch, info["source"], info["objet"], info["nb_lignes"])
                    resultats[cle] = step.nb_lignes
        return resultats
    finally:
        if propre:
            conn.close()


if __name__ == "__main__":
    lot = latest_batch()
    print(lot.batch_id, load(lot))
    sys.exit(0)
