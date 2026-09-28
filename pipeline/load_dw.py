"""
pipeline/load_dw.py — Chargement du Data Warehouse (Lot L6, Phases 7 à 9)
========================================================================

    1. DDL : 8 dimensions et 8 faits (constellation), membres « Inconnu » (-1) ;
    2. dimensions : chargement INCRÉMENTAL (SCD 1 ; SCD 2 pour la localisation de l'étudiant) ;
    3. faits : rechargement complet, rattachés à la version de l'étudiant valable à leur date.

Date d'effet d'une nouvelle version SCD 2 = date d'extraction du lot présent en staging
(paramètre de session edusmart.date_effet). Tout se fait dans UNE transaction.

    python -m pipeline.load_dw            # chargement (incrémental pour les dimensions)
    python -m pipeline.load_dw --reset    # supprime le schéma dw et repart de zéro (perd l'historique SCD 2)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from common.config import get_settings
from common.logger import get_logger, log_step

logger = get_logger("load_dw")
SQL_DW = Path(__file__).resolve().parent / "sql" / "dw"
FICHIERS = ("01_dimensions.sql", "02_faits.sql", "10_charger_dimensions.sql", "20_charger_faits.sql")
DIMENSIONS = ("dim_temps", "dim_region", "dim_formation", "dim_module", "dim_quiz", "dim_enseignant", "dim_etudiant")
FAITS = ("fact_paiements", "fact_inscriptions", "fact_notes", "fact_quiz_activite", "fact_connexions",
         "fact_progression", "fact_salaires", "fact_absences")


def date_effet(conn) -> date:
    """Date d'extraction du lot PostgreSQL présent en staging."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(_extracted_at)::DATE FROM staging.stg_pg_etudiants")
        d = cur.fetchone()[0]
    if d is None:
        raise RuntimeError("Staging vide : lancez d'abord le pipeline (extract, load, transform)")
    return d


def charger(conn, reset: bool = False, effet: date | None = None) -> dict[str, int]:
    effet = effet or date_effet(conn)
    try:
        with conn.cursor() as cur:
            cur.execute("SET lock_timeout = '30s'; SET statement_timeout = '15min'")
            if reset:
                cur.execute("DROP SCHEMA IF EXISTS dw CASCADE")
            cur.execute("SELECT set_config('edusmart.date_effet', %s, false)", (effet.isoformat(),))
            for nom in FICHIERS:
                with log_step(logger, f"DW {nom}"):
                    cur.execute((SQL_DW / nom).read_text(encoding="utf-8"))
            comptes = {}
            for t in DIMENSIONS + FAITS:
                cur.execute(f"SELECT COUNT(*) FROM dw.{t}")
                comptes[t] = cur.fetchone()[0]
        conn.commit()
        return comptes
    except Exception:
        conn.rollback()
        raise


def main(argv: list[str] | None = None) -> int:
    import psycopg2
    parser = argparse.ArgumentParser(description="Chargement du Data Warehouse EduSmart")
    parser.add_argument("--reset", action="store_true", help="repartir d'un schéma dw vide (perd l'historique SCD 2)")
    args = parser.parse_args(argv)
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        comptes = charger(conn, args.reset)
        for t, n in comptes.items():
            logger.info("%-20s %8d lignes", t, n)
        return 0
    except Exception:
        logger.exception("Échec du chargement du DW")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
