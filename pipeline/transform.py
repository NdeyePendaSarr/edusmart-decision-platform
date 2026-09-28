"""
pipeline/transform.py — Transformation staging -> clean + contrôle qualité (Lot L5)
==================================================================================

Enchaînement (tout s'exécute DANS l'entrepôt, en SQL : principe ELT) :
    1. schémas quality et clean, fonctions, catalogue des 89 règles (quality.regles) ;
    2. référentiels (villes, synonymes, correspondances) ;
    3. un script SQL par source, dans l'ordre des dépendances :
         S1 PostgreSQL, S2 MySQL, S3 CSV, S4 MongoDB, puis S5 Redis
         (Redis a besoin de MongoDB et de MySQL, déjà nettoyés) ;
    4. synthèse et rapport qualité : pipeline/rapport_qualite.py (appelé par run_pipeline, étape « qualite »).

Chaque source est une transaction : en cas d'erreur, les tables clean et les
constats de cette source restent dans leur état précédent. Chaque étape est
tracée dans meta.etl_execution_log (étape TRANSFORM).

Paramètres de session transmis au SQL :
    edusmart.batch_id        lot présent en staging
    edusmart.date_reference  15/09/2026 (C20) : aucune donnée métier après cette date
    edusmart.redis_snapshot  15/09/2026 23:00 (C24) : instant du snapshot Redis

Exécution : python -m pipeline.transform   (sur le lot présent en staging)
"""

from __future__ import annotations

import sys
from pathlib import Path

from common.config import get_settings
from common.logger import get_logger, log_step
from pipeline.qualite_regles import REGLES

logger = get_logger("transform")

SQL_DIR = Path(__file__).resolve().parent / "sql"
SQL_INIT = (SQL_DIR / "quality" / "01_quality_tables.sql", SQL_DIR / "clean" / "00_fonctions.sql")
SQL_SOURCES = {
    "s1_postgresql": SQL_DIR / "clean" / "10_s1_postgresql.sql",
    "s2_mysql": SQL_DIR / "clean" / "20_s2_mysql.sql",
    "s3_csv": SQL_DIR / "clean" / "30_s3_csv.sql",
    "s4_mongodb": SQL_DIR / "clean" / "40_s4_mongodb.sql",
    "s5_redis": SQL_DIR / "clean" / "50_s5_redis.sql",
}
REDIS_SNAPSHOT = "2026-09-15 23:00:00"          # convention C24


class TransformError(Exception):
    """Aucun lot en staging, ou lots incohérents."""


def batch_en_staging(conn) -> str:
    """
    Lot le plus récent présent en staging, parmi LES 17 TABLES.
    Correctif L6 : seules les tables PostgreSQL et MySQL étaient consultées. Une relance ciblée
    (--sources s5_redis) enregistrait alors les constats sous l'ancien lot, et G3 ne les trouvait pas.
    """
    from pipeline.registry import OBJECTS, STAGING_SCHEMA
    union = " UNION ".join(f"SELECT DISTINCT _batch_id FROM {STAGING_SCHEMA}.{o.stg_table}" for o in OBJECTS)
    with conn.cursor() as cur:
        cur.execute(union)
        lots = sorted(r[0] for r in cur.fetchall())
    if not lots:
        raise TransformError("Staging vide : lancez d'abord python -m pipeline.run_pipeline")
    return lots[-1]


def _parametres(conn, batch_id: str) -> None:
    gen = get_settings().generation
    with conn.cursor() as cur:
        # Une session interrompue peut laisser des verrous : on échoue proprement au lieu d'attendre indéfiniment
        cur.execute("SET lock_timeout = '30s'; SET statement_timeout = '10min'")
        cur.execute("SELECT set_config('edusmart.batch_id', %s, false), set_config('edusmart.date_reference', %s, false),"
                    " set_config('edusmart.redis_snapshot', %s, false)",
                    (batch_id, gen.date_reference.isoformat(), REDIS_SNAPSHOT))


def initialiser(conn) -> None:
    from pipeline import referentiels
    with conn.cursor() as cur:
        for path in SQL_INIT:
            cur.execute(path.read_text(encoding="utf-8"))
        for r in REGLES:
            cur.execute("""INSERT INTO quality.regles VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (code_regle) DO UPDATE SET dimension = EXCLUDED.dimension,
                               code_source = EXCLUDED.code_source, table_cible = EXCLUDED.table_cible,
                               colonne = EXCLUDED.colonne, action = EXCLUDED.action,
                               anomalies = EXCLUDED.anomalies, description = EXCLUDED.description""",
                        (r.code, r.dimension, r.source, r.table, r.colonne, r.action, list(r.anomalies), r.description))
    comptes = referentiels.charger(conn)
    conn.commit()
    logger.info("Référentiels : %s", comptes)


def transformer_source(conn, source: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_SOURCES[source].read_text(encoding="utf-8"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def transform(sources: list[str] | None = None, meta=None, conn=None) -> str:
    """Transforme les sources demandées (par défaut les 5). Retourne le batch_id traité."""
    import psycopg2
    propre = conn is None
    conn = conn or psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        conn.autocommit = False
        batch_id = batch_en_staging(conn)
        _parametres(conn, batch_id)
        with log_step(logger, "Initialisation (qualité, fonctions, règles, référentiels)"):
            initialiser(conn)
        for source in sources or list(SQL_SOURCES):
            with log_step(logger, f"TRANSFORM {source}"):
                if meta is None:
                    transformer_source(conn, source)
                else:
                    with meta.step(batch_id, "TRANSFORM", source, "*") as step:
                        transformer_source(conn, source)
                        step.nb_lignes = compter_clean(conn, source)
        return batch_id
    finally:
        if propre:
            conn.close()


TABLES_CLEAN = {
    "s1_postgresql": ("etudiants", "filieres", "classes", "inscriptions", "paiements"),
    "s2_mysql": ("modules", "cours", "quiz", "notes", "progression", "temps_connexion", "comptes_lms"),
    "s3_csv": ("enseignants", "departements", "salaires", "absences"),
    "s4_mongodb": ("evenements",),
    "s5_redis": ("redis_sessions", "redis_last_course", "redis_last_quiz", "redis_progress",
                 "redis_notifications", "redis_leaderboard", "redis_compteurs"),
}


def compter_clean(conn, source: str) -> int:
    total = 0
    with conn.cursor() as cur:
        for t in TABLES_CLEAN[source]:
            cur.execute(f"SELECT COUNT(*) FROM clean.{t}")
            total += cur.fetchone()[0]
    return total


def main() -> int:
    try:
        batch_id = transform()
        logger.info("Couche clean construite pour le lot %s", batch_id)
        return 0
    except TransformError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Échec de la transformation")
        return 2


if __name__ == "__main__":
    sys.exit(main())
