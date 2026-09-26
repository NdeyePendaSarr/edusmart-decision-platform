"""
scripts/check_infrastructure.py — Point de contrôle G0 (Lot L0)
===============================================================

Vérifie, depuis Windows (machine hôte), que les 5 services de données
répondent et respectent les versions minimales exigées :

    Service     Version min.  Vérification complémentaire
    pg_source   15            base edusmart_academic joignable
    pg_dw       15            5 schémas présents (staging, clean, dw, meta, quality)
    mysql       8.0.16        CHECK appliqués / NOT ENFORCED disponible
    mongo       6.0           commande ping
    redis       7.0           commande PING

Chaque contrôle est isolé (try/except) : une panne n'empêche pas de tester
les autres services. Code de sortie 0 si tout est vert, 1 sinon.

Exécution (depuis la racine du projet, conteneurs démarrés) :
    python -m scripts.check_infrastructure
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from common.config import ConfigError, get_settings
from common.logger import get_logger

logger = get_logger("check_infrastructure")

DW_SCHEMAS = ("staging", "clean", "dw", "meta", "quality")


@dataclass
class CheckResult:
    service: str
    ok: bool
    detail: str


def _version_tuple(version: str) -> tuple[int, ...]:
    """'8.0.36' -> (8, 0, 36) ; '15.6 (Debian...)' -> (15, 6)."""
    numbers = []
    for part in version.split()[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers)


def _is_at_least(version: str, minimum: tuple[int, ...]) -> bool:
    return _version_tuple(version) >= minimum


# -----------------------------------------------------------------------------
# Contrôles
# -----------------------------------------------------------------------------
def _check_postgres(cfg, check_schemas: bool) -> CheckResult:
    import psycopg2  # import local : un pilote manquant n'empêche pas les autres contrôles

    # Attention : « with psycopg2.connect() » ne ferme PAS la connexion
    # (il ne gère que la transaction) ; d'où le close() explicite.
    conn = psycopg2.connect(**cfg.connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0]
            if not _is_at_least(version, (15,)):
                return CheckResult(cfg.service, False, f"version {version} < 15")
            detail = f"PostgreSQL {version} - base {cfg.database}"
            if check_schemas:
                cur.execute(
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)",
                    (list(DW_SCHEMAS),),
                )
                present = {row[0] for row in cur.fetchall()}
                missing = sorted(set(DW_SCHEMAS) - present)
                if missing:
                    return CheckResult(cfg.service, False,
                                       f"{detail} - schémas manquants : {missing} "
                                       f"(le script d'init ne s'exécute qu'au 1er démarrage)")
                detail += " - 5 schémas OK"
    finally:
        conn.close()
    return CheckResult(cfg.service, True, detail)


def check_pg_source() -> CheckResult:
    return _check_postgres(get_settings().pg_source, check_schemas=False)


def check_pg_dw() -> CheckResult:
    return _check_postgres(get_settings().pg_dw, check_schemas=True)


def check_mysql() -> CheckResult:
    import pymysql

    cfg = get_settings().mysql
    conn = pymysql.connect(**cfg.connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
    finally:
        conn.close()
    if not _is_at_least(version, (8, 0, 16)):
        return CheckResult("mysql", False, f"version {version} < 8.0.16 (CHECK non appliqués)")
    return CheckResult("mysql", True, f"MySQL {version} - base {cfg.database}")


def check_mongo() -> CheckResult:
    from pymongo import MongoClient

    cfg = get_settings().mongo
    client = MongoClient(cfg.uri(), serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        version = client.server_info()["version"]
    finally:
        client.close()
    if not _is_at_least(version, (6,)):
        return CheckResult("mongo", False, f"version {version} < 6.0")
    return CheckResult("mongo", True, f"MongoDB {version} - {cfg.safe_uri()}")


def check_redis() -> CheckResult:
    import redis

    cfg = get_settings().redis
    client = redis.Redis(**cfg.connect_kwargs())
    try:
        if not client.ping():
            return CheckResult("redis", False, "PING sans réponse")
        version = client.info("server")["redis_version"]
    finally:
        client.close()
    if not _is_at_least(version, (7,)):
        return CheckResult("redis", False, f"version {version} < 7.0")
    return CheckResult("redis", True, f"Redis {version} - db {cfg.db}")


CHECKS: dict[str, Callable[[], CheckResult]] = {
    "pg_source": check_pg_source,
    "pg_dw": check_pg_dw,
    "mysql": check_mysql,
    "mongo": check_mongo,
    "redis": check_redis,
}


def run_checks() -> list[CheckResult]:
    results = []
    for service, check in CHECKS.items():
        try:
            result = check()
        except ConfigError as exc:
            result = CheckResult(service, False, f"configuration : {exc}")
        except ImportError as exc:
            result = CheckResult(service, False, f"pilote Python manquant : {exc} (pip install -r requirements.txt)")
        except Exception as exc:  # connexion refusée, authentification, délai...
            result = CheckResult(service, False, f"{type(exc).__name__} : {str(exc).strip()[:200]}")
        level = logger.info if result.ok else logger.error
        level("[%s] %-10s %s", "OK" if result.ok else "KO", service, result.detail)
        results.append(result)
    return results


def main() -> int:
    logger.info("Point de contrôle G0 - vérification des 5 services")
    results = run_checks()
    nb_ok = sum(r.ok for r in results)
    logger.info("Résultat G0 : %d/%d services opérationnels", nb_ok, len(results))
    if nb_ok != len(results):
        logger.error("G0 NON VALIDÉ. Vérifiez 'docker compose ps' et docker/.env.")
        return 1
    logger.info("G0 VALIDÉ côté Python. Reste à tester la connexion Power BI (voir README).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
