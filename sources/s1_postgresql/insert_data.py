"""
sources/s1_postgresql/insert_data.py — Chargement de la Source 1 (Lot L2-a)
==========================================================================

Enchaînement
    1. create_database.sql  : (re)création des 5 tables (PK + UNIQUE sûrs).
    2. COPY de chaque CSV   : chargement en masse, dans l'ordre des FK.
    3. Contrôle des volumes : nombre de lignes en base = nombre de lignes CSV.
       -> Les étapes 1 à 3 forment UNE transaction : en cas d'erreur, rien
          n'est conservé (pas de base à moitié chargée).
    4. add_constraints.sql  : CHECK et FK ajoutés en NOT VALID (+ validation
       des contraintes non concernées par les anomalies).

Pourquoi COPY ?
    C'est le mécanisme de chargement en masse natif de PostgreSQL : environ
    70 000 lignes en quelques secondes, contre plusieurs minutes avec des
    INSERT ligne à ligne.

Prérequis : conteneur pg_source démarré, docker/.env renseigné, CSV générés
(python -m sources.s1_postgresql.generate_data).

Exécution : python -m sources.s1_postgresql.insert_data [--skip-constraints]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from common.config import ConfigError, get_settings
from common.logger import get_logger, log_step
from sources.s1_postgresql.anomalies import SOURCE
from sources.s1_postgresql.generate_data import COLUMNS, TABLE_ORDER

logger = get_logger("s1_insert")

SQL_DIR = Path(__file__).resolve().parent
CREATE_SQL = SQL_DIR / "create_database.sql"
CONSTRAINTS_SQL = SQL_DIR / "add_constraints.sql"


class InsertError(Exception):
    """Erreur bloquante pendant le chargement."""


def _count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1  # sans l'en-tête (gère les retours ligne cités)


def _check_inputs(data_dir: Path) -> dict[str, Path]:
    files = {t: data_dir / f"{t}.csv" for t in TABLE_ORDER}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise InsertError("CSV manquants (lancez d'abord generate_data) : " + ", ".join(missing))
    for sql_file in (CREATE_SQL, CONSTRAINTS_SQL):
        if not sql_file.exists():
            raise InsertError(f"Script SQL introuvable : {sql_file}")
    return files


def load(skip_constraints: bool = False, data_dir: Path | None = None) -> dict[str, int]:
    """Charge la Source 1 et retourne le nombre de lignes par table."""
    import psycopg2
    from psycopg2 import sql

    settings = get_settings()
    data_dir = data_dir or settings.paths.generated_dir / SOURCE
    files = _check_inputs(data_dir)
    expected = {t: _count_csv_rows(p) for t, p in files.items()}

    conn = psycopg2.connect(**settings.pg_source.connect_kwargs())
    try:
        conn.set_client_encoding("UTF8")

        # --- Étapes 1 à 3 : une seule transaction --------------------------
        with log_step(logger, "Création des tables + chargement COPY"):
            with conn.cursor() as cur:
                cur.execute(CREATE_SQL.read_text(encoding="utf-8"))
                for table in TABLE_ORDER:
                    copy_stmt = sql.SQL(
                        "COPY {tbl} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '', ENCODING 'UTF8')"
                    ).format(tbl=sql.Identifier(table),
                             cols=sql.SQL(", ").join(map(sql.Identifier, COLUMNS[table])))
                    with files[table].open(encoding="utf-8", newline="") as handle:
                        cur.copy_expert(copy_stmt.as_string(conn), handle)
                    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
                    loaded = cur.fetchone()[0]
                    if loaded != expected[table]:
                        raise InsertError(f"{table} : {loaded} lignes en base, {expected[table]} dans le CSV")
                    logger.info("%-13s %6d lignes chargées", table, loaded)
            conn.commit()

        # --- Étape 4 : contraintes (le script gère sa propre transaction) ---
        if skip_constraints:
            logger.warning("Contraintes CHECK/FK NON ajoutées (--skip-constraints).")
        else:
            with log_step(logger, "Ajout des contraintes (NOT VALID + validations sûres)"):
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(CONSTRAINTS_SQL.read_text(encoding="utf-8"))
        return expected
    except Exception:
        if not conn.autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chargement de la Source 1 (PostgreSQL)")
    parser.add_argument("--skip-constraints", action="store_true",
                        help="ne pas exécuter add_constraints.sql (débogage)")
    args = parser.parse_args(argv)
    try:
        counts = load(skip_constraints=args.skip_constraints)
        logger.info("Chargement terminé : %s", counts)
        logger.info("Étape suivante : python -m sources.s1_postgresql.verify_source (porte G1)")
        return 0
    except (InsertError, ConfigError) as exc:
        logger.error("%s", exc)
        return 1
    except ImportError as exc:
        logger.error("Pilote manquant : %s (pip install -r requirements.txt)", exc)
        return 1
    except Exception:
        logger.exception("Échec du chargement. Une erreur pendant la création ou le COPY annule "
                         "toute la transaction ; une erreur pendant les contraintes laisse les données chargées.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
