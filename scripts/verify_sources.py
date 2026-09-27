"""
scripts/verify_sources.py — Les 5 portes G1 en une commande (fin du volet A)
============================================================================

Exécute successivement la vérification G1 de chaque source et affiche un
récapitulatif. Prérequis : les 5 sources générées ET chargées.

Exécution : python -m scripts.verify_sources
Code de sortie : 0 si les 5 portes sont validées.
"""

from __future__ import annotations

import importlib
import sys
import time

from common.logger import get_logger

logger = get_logger("verify_sources")

SOURCES = (
    ("Source 1 - PostgreSQL", "sources.s1_postgresql.verify_source"),
    ("Source 2 - MySQL", "sources.s2_mysql.verify_source"),
    ("Source 3 - CSV RH", "sources.s3_csv.verify_source"),
    ("Source 4 - MongoDB", "sources.s4_mongodb.verify_source"),
    ("Source 5 - Redis", "sources.s5_redis.verify_source"),
)


def main() -> int:
    resultats = []
    for nom, module in SOURCES:
        debut = time.perf_counter()
        try:
            code = importlib.import_module(module).main()
        except Exception:
            logger.exception("%s : erreur inattendue", nom)
            code = 2
        resultats.append((nom, code, time.perf_counter() - debut))
    logger.info("=" * 60)
    for nom, code, duree in resultats:
        (logger.info if code == 0 else logger.error)("%-24s %s  (%.0f s)", nom, "G1 VALIDÉE" if code == 0 else "G1 NON VALIDÉE", duree)
    ok = all(code == 0 for _, code, _ in resultats)
    logger.info("Volet A : %d/5 sources validées. Rapports : data/reports/", sum(code == 0 for _, code, _ in resultats))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
