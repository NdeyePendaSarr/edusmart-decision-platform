"""
sources/s2_mysql/insert_data.py — Chargement de la Source 2 (Lot L2-b)
=====================================================================

Enchaînement
    1. create_database.sql : (re)création des 6 tables, contraintes incluses
       (CHECK ENFORCED / NOT ENFORCED, FOREIGN KEY).
    2. Chargement de chaque CSV avec FOREIGN_KEY_CHECKS = 0 (session) :
       les orphelins volontaires (B07) sont acceptés. Méthode :
       - LOAD DATA LOCAL INFILE (rapide : ~420 000 lignes en quelques secondes) ;
       - repli automatique sur des INSERT groupés si le client ou le serveur
         refuse LOAD DATA LOCAL (sécurité MySQL).
    3. Contrôles : nombre de lignes en base = nombre de lignes CSV, et AUCUN
       avertissement MySQL (un avertissement signalerait une valeur tronquée
       ou convertie silencieusement).
    4. FOREIGN_KEY_CHECKS = 1 : les FK protègent de nouveau les nouvelles lignes.

Différence avec PostgreSQL : en MySQL, chaque instruction DDL valide
implicitement la transaction. Le chargement n'est donc pas « tout ou rien » :
en cas d'erreur, il suffit de relancer (le script est idempotent).

Exécution : python -m sources.s2_mysql.insert_data [--force-inserts]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from common.config import ConfigError, get_settings
from common.logger import get_logger, log_step
from sources.s2_mysql.anomalies import SOURCE
from sources.s2_mysql.generate_data import COLUMNS, NULL, TABLE_ORDER

logger = get_logger("s2_insert")

SQL_DIR = Path(__file__).resolve().parent
CREATE_SQL = SQL_DIR / "create_database.sql"
BATCH_SIZE = 5_000

# Erreurs MySQL signifiant « LOAD DATA LOCAL interdit » -> repli sur INSERT
LOCAL_INFILE_ERRORS = {1148, 2068, 3948, 3950}


class InsertError(Exception):
    """Erreur bloquante pendant le chargement."""


def _split_sql(script: str) -> list[str]:
    """Découpe un script SQL en instructions (commentaires '--' retirés)."""
    sans_commentaires = re.sub(r"--[^\n]*", "", script)
    return [s.strip() for s in sans_commentaires.split(";") if s.strip()]


def _count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


def _load_data_local(cur, table: str, path: Path) -> None:
    cols = ", ".join(f"`{c}`" for c in COLUMNS[table])
    # Chemin en '/' : fonctionne aussi sous Windows et évite l'échappement des '\'
    cur.execute(
        f"LOAD DATA LOCAL INFILE %s INTO TABLE `{table}` CHARACTER SET utf8mb4 "
        "FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY '\\\\' "
        f"LINES TERMINATED BY '\\n' IGNORE 1 LINES ({cols})",
        (path.resolve().as_posix(),),
    )


def _insert_batches(cur, table: str, path: Path) -> None:
    cols = ", ".join(f"`{c}`" for c in COLUMNS[table])
    placeholders = ", ".join(["%s"] * len(COLUMNS[table]))
    sql = f"INSERT INTO `{table}` ({cols}) VALUES ({placeholders})"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        batch = []
        for row in reader:
            batch.append([None if v == NULL else v for v in row])
            if len(batch) >= BATCH_SIZE:
                cur.executemany(sql, batch)
                batch.clear()
        if batch:
            cur.executemany(sql, batch)


def load(force_inserts: bool = False, data_dir: Path | None = None) -> dict[str, int]:
    import pymysql

    settings = get_settings()
    data_dir = data_dir or settings.paths.generated_dir / SOURCE
    files = {t: data_dir / f"{t}.csv" for t in TABLE_ORDER}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise InsertError("CSV manquants (lancez d'abord generate_data) : " + ", ".join(missing))
    expected = {t: _count_csv_rows(p) for t, p in files.items()}

    conn = pymysql.connect(**settings.mysql.connect_kwargs(), local_infile=True, autocommit=False)
    use_local_infile = not force_inserts
    try:
        with conn.cursor() as cur:
            with log_step(logger, "Création des tables (create_database.sql)"):
                for statement in _split_sql(CREATE_SQL.read_text(encoding="utf-8")):
                    cur.execute(statement)

            cur.execute("SET SESSION FOREIGN_KEY_CHECKS = 0")
            with log_step(logger, "Chargement des 6 tables"):
                for table in TABLE_ORDER:
                    if use_local_infile:
                        try:
                            _load_data_local(cur, table, files[table])
                            methode = "LOAD DATA LOCAL"
                        except pymysql.err.OperationalError as exc:
                            if exc.args[0] not in LOCAL_INFILE_ERRORS:
                                raise
                            logger.warning("LOAD DATA LOCAL refusé (%s) : repli sur INSERT groupés.", exc.args[1])
                            conn.rollback()
                            use_local_infile = False
                    if not use_local_infile:
                        _insert_batches(cur, table, files[table])
                        methode = "INSERT groupés"

                    cur.execute("SHOW COUNT(*) WARNINGS")
                    nb_warnings = cur.fetchone()[0]
                    if nb_warnings:
                        cur.execute("SHOW WARNINGS LIMIT 5")
                        raise InsertError(f"{table} : {nb_warnings} avertissement(s) MySQL, "
                                          f"ex. {cur.fetchall()}")
                    cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                    loaded = cur.fetchone()[0]
                    if loaded != expected[table]:
                        raise InsertError(f"{table} : {loaded} lignes en base, {expected[table]} dans le CSV")
                    conn.commit()
                    logger.info("%-16s %7d lignes chargées (%s)", table, loaded, methode)
            cur.execute("SET SESSION FOREIGN_KEY_CHECKS = 1")
        return expected
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chargement de la Source 2 (MySQL)")
    parser.add_argument("--force-inserts", action="store_true",
                        help="ne pas utiliser LOAD DATA LOCAL (plus lent, toujours autorisé)")
    args = parser.parse_args(argv)
    try:
        counts = load(force_inserts=args.force_inserts)
        logger.info("Chargement terminé : %s", counts)
        logger.info("Étape suivante : python -m sources.s2_mysql.verify_source (porte G1)")
        return 0
    except (InsertError, ConfigError) as exc:
        logger.error("%s", exc)
        return 1
    except ImportError as exc:
        logger.error("Pilote manquant : %s (pip install -r requirements.txt)", exc)
        return 1
    except Exception:
        logger.exception("Échec du chargement de la Source 2 (relancer : le script est idempotent)")
        return 2


if __name__ == "__main__":
    sys.exit(main())
