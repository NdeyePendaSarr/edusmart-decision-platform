"""
pipeline/run_pipeline.py — Orchestration du pipeline ELT (Lot L4)
================================================================

Un lancement = un LOT (batch_id) :
    0. initialisation : schémas meta et staging (idempotent), catalogue des 17 objets ;
    1. EXTRACT : les 5 sources -> data/landing/<batch_id>/ ;
    2. LOAD    : data/landing/<batch_id>/ -> edusmart_dw.staging ;
    3. VERIFY    : porte G2 (complétude, fidélité, traçabilité) ;
    4. TRANSFORM : staging -> clean, 89 règles qualité (lot L5) ;
    5. QUALITE   : rapport qualité (Phase 5) et porte G3 (toutes les anomalies traitées) ;
    6. DW        : dimensions (SCD 1 / SCD 2) et 8 faits, porte G4 (lot L6).

Politique d'erreur : l'échec d'une source n'empêche pas les autres d'être
extraites. Il est tracé (statut ECHEC dans le journal), la source n'est pas
chargée, et le code de sortie vaut 1.

Exemples :
    python -m pipeline.run_pipeline                              # tout
    python -m pipeline.run_pipeline --sources s3_csv s5_redis    # deux sources
    python -m pipeline.run_pipeline --steps load verify          # rechargement du dernier lot
"""

from __future__ import annotations

import argparse
import importlib
import sys

from common.config import ConfigError, get_settings
from common.logger import get_logger, log_step
from pipeline.landing import Batch, latest_batch, new_batch_id
from pipeline.meta import MetaStore
from pipeline.registry import SOURCES

logger = get_logger("pipeline")

EXTRACTEURS = {"s1_postgresql": "pipeline.extract_postgres", "s2_mysql": "pipeline.extract_mysql",
               "s3_csv": "pipeline.extract_csv", "s4_mongodb": "pipeline.extract_mongodb",
               "s5_redis": "pipeline.extract_redis"}
ETAPES = ("extract", "load", "verify", "transform", "qualite", "dw")


def emplacements() -> dict[str, str]:
    res = {}
    for source, module in EXTRACTEURS.items():
        mod = importlib.import_module(module)
        res[source] = mod.emplacement() if hasattr(mod, "emplacement") else "sources/s3_csv/output/"
    return res


def run(sources: list[str], etapes: list[str]) -> int:
    import psycopg2
    from pipeline import load as load_mod
    from pipeline import verify_g2

    settings = get_settings()
    conn_meta = psycopg2.connect(**settings.pg_dw.connect_kwargs())
    meta = MetaStore(conn_meta)
    code_retour = 0
    try:
        with log_step(logger, "Initialisation (schémas meta et staging, catalogue des sources)"):
            meta.init_schema()
            meta.sync_sources(emplacements())

        if "extract" in etapes:
            batch = Batch(new_batch_id())
            logger.info("Nouveau lot : %s", batch.batch_id)
            reussies = []
            for source in sources:
                try:
                    with log_step(logger, f"EXTRACT {source}"):
                        importlib.import_module(EXTRACTEURS[source]).extract(batch, meta)
                    reussies.append(source)
                except Exception as exc:
                    logger.error("Extraction de %s en échec : %s (source ignorée pour ce lot)", source, exc)
                    meta.record_failure(batch.batch_id, "EXTRACT", source, f"{type(exc).__name__}: {exc}")
                    code_retour = 1
            sources = reussies
        else:
            batch = latest_batch()
            logger.info("Lot existant : %s", batch.batch_id)

        if "load" in etapes and sources:
            with log_step(logger, "LOAD (staging)"):
                load_mod.load(batch, sources, meta)

        if "verify" in etapes and sources:
            with log_step(logger, "VERIFY (porte G2)"):
                checks = verify_g2.verify(batch, sources)
                rapport = verify_g2.write_report(batch, checks)
            for c in checks:
                if not c.ok:
                    logger.error("[KO] %s %s %s : %s", c.code, c.objet, c.libelle, c.detail)
            n_ok = sum(c.ok for c in checks)
            logger.info("Porte G2 : %d/%d contrôles réussis — %s", n_ok, len(checks), rapport)
            if n_ok != len(checks):
                code_retour = 1
        if "transform" in etapes:
            from pipeline import transform as transform_mod
            with log_step(logger, "TRANSFORM (couche clean, 5 sources)"):
                transform_mod.transform(None, meta)

        if "qualite" in etapes:
            code_retour = max(code_retour, qualite(batch.batch_id, meta))

        if "dw" in etapes:
            code_retour = max(code_retour, entrepot(batch.batch_id, meta))
        logger.info("Lot %s terminé (code %d). Journal : meta.etl_execution_log", batch.batch_id, code_retour)
        return code_retour
    finally:
        conn_meta.close()


def qualite(batch_id: str, meta) -> int:
    """Rapport qualité (Phase 5) + porte G3. Retourne 0 si G3 est validée."""
    import psycopg2
    from pipeline import rapport_qualite, verify_g3
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        with log_step(logger, "QUALITE (rapport Phase 5 et porte G3)"):
            with meta.step(batch_id, "VERIFY", "*", "G3") as step:
                lignes, dims = rapport_qualite.calculer(conn, batch_id)
                logger.info("Rapport qualité : %s", rapport_qualite.ecrire_rapport(conn, batch_id, lignes, dims))
                resultats = verify_g3.verify(conn, batch_id)
                step.nb_lignes = sum(r.traitees for r in resultats)
        rapport = verify_g3.write_report(batch_id, resultats)
    finally:
        conn.close()
    for r in resultats:
        if not r.ok:
            logger.error("[KO] G3 %s : %d/%d anomalies traitées", r.code, r.traitees, r.total)
    ok = sum(r.ok for r in resultats)
    non_extraites = sum(r.non_extraites for r in resultats)
    if non_extraites:
        logger.warning("G3 : %d anomalie(s) Redis non extraite(s) (clé expirée avant l'extraction) — "
                       "relancez python -m sources.s5_redis.insert_data avant le pipeline", non_extraites)
    logger.info("Porte G3 : %d/%d types d'anomalies traités à 100 %% (%d anomalies) — %s", ok, len(resultats),
                sum(r.traitees for r in resultats), rapport)
    return 0 if ok == len(resultats) else 1


def entrepot(batch_id: str, meta) -> int:
    """Chargement du Data Warehouse + porte G4. Retourne 0 si G4 est validée."""
    import psycopg2
    from pipeline import load_dw, verify_g4
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        with log_step(logger, "DW (dimensions, faits, porte G4)"):
            with meta.step(batch_id, "DW", "*", "dw") as step:
                comptes = load_dw.charger(conn)
                step.nb_lignes = sum(n for t, n in comptes.items() if t.startswith("fact_"))
            checks = verify_g4.verify(conn)
        rapport = verify_g4.write_report(checks, batch_id)
    finally:
        conn.close()
    for c in checks:
        if not c.ok:
            logger.error("[KO] %s %s : %s", c.code, c.libelle, c.detail)
    logger.info("Porte G4 : %d/%d contrôles réussis — %s", sum(c.ok for c in checks), len(checks), rapport)
    return 0 if all(c.ok for c in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline ELT EduSmart (L4 : extraction, chargement, porte G2)")
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(SOURCES))
    parser.add_argument("--steps", nargs="+", choices=ETAPES, default=list(ETAPES))
    args = parser.parse_args(argv)
    try:
        return run(args.sources, args.steps)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Échec du pipeline")
        return 2


if __name__ == "__main__":
    sys.exit(main())
