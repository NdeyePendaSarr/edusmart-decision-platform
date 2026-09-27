"""
pipeline/verify_g2.py — Porte G2 : extraction et chargement (Lot L4)
===================================================================

Pour chaque objet du lot, trois questions de la Phase 15 :

    G2.1  Toutes les lignes ont-elles été EXTRAITES ?
          lignes dans la source (recomptées maintenant) = lignes extraites (manifeste)
    G2.2  Toutes les lignes ont-elles été CHARGÉES ?
          lignes en staging (pour ce lot) = lignes extraites
    G2.3  Des valeurs ont-elles été ALTÉRÉES ?
          empreinte MD5 des valeurs du fichier d'atterrissage = empreinte recalculée
          EN SQL sur le staging (même ordre, même représentation des NULL).
          Pour MongoDB et Redis (JSONB normalise le texte) : mêmes event_id / clés.

et deux contrôles de traçabilité (Phase 6) :
    G2.4  une ligne SUCCES dans meta.etl_execution_log pour EXTRACT et LOAD ;
    G2.5  meta.metadata_sources à jour (dernier lot, nombre de lignes, statut).

Rapport : data/reports/G2_<batch_id>.md
Exécution seule (dernier lot) : python -m pipeline.verify_g2
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime

from common.config import get_settings
from common.logger import get_logger
from pipeline.landing import SEP_CHAMP, SEP_LIGNE, Batch, latest_batch, read_landing, read_manifest
from pipeline.registry import NULL_MARKER, STAGING_SCHEMA, get_object

logger = get_logger("verify_g2")


@dataclass
class Check:
    code: str
    objet: str
    libelle: str
    ok: bool
    detail: str


# -----------------------------------------------------------------------------
# Recomptage dans les sources
# -----------------------------------------------------------------------------
def compter_source(source: str, objet: str) -> int:
    s = get_settings()
    if source == "s1_postgresql":
        import psycopg2
        from psycopg2 import sql
        with psycopg2.connect(**s.pg_source.connect_kwargs()) as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(objet)))
            n = cur.fetchone()[0]
        conn.close()
        return n
    if source == "s2_mysql":
        import pymysql
        conn = pymysql.connect(**s.mysql.connect_kwargs())
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM `{objet}`")
                return cur.fetchone()[0]
        finally:
            conn.close()
    if source == "s3_csv":
        from pipeline.extract_csv import lire_csv
        from sources.s3_csv.create_source import OUTPUT_DIR, SCHEMAS
        return sum(1 for _ in lire_csv(OUTPUT_DIR / SCHEMAS[objet].nom, objet))
    if source == "s4_mongodb":
        from pymongo import MongoClient
        client = MongoClient(s.mongo.uri(), serverSelectionTimeoutMS=5000)
        try:
            return client[s.mongo.database][objet].count_documents({})
        finally:
            client.close()
    if source == "s5_redis":
        import redis
        client = redis.Redis(**s.redis.connect_kwargs())
        try:
            return client.dbsize()
        finally:
            client.close()
    raise KeyError(source)


# -----------------------------------------------------------------------------
# Empreintes
# -----------------------------------------------------------------------------
def empreinte_staging(conn, batch_id: str, source: str, objet: str) -> str:
    """Même calcul que pipeline.landing.Empreinte, mais en SQL sur le staging."""
    from psycopg2 import sql
    obj = get_object(source, objet)
    valeurs = sql.SQL(", ").join(
        sql.SQL("COALESCE({}::text, {})").format(sql.Identifier(c), sql.Literal(NULL_MARKER)) for c in obj.colonnes)
    requete = sql.SQL("""SELECT COALESCE(md5(string_agg(concat_ws({us}, {vals}), {rs} ORDER BY _row_number)), md5(''))
                         FROM {t} WHERE _batch_id = %s""").format(
        us=sql.Literal(SEP_CHAMP), rs=sql.Literal(SEP_LIGNE), vals=valeurs,
        t=sql.Identifier(STAGING_SCHEMA, obj.stg_table))
    with conn.cursor() as cur:
        cur.execute(requete, (batch_id,))
        return cur.fetchone()[0]


def identifiants_staging(conn, batch_id: str, source: str, objet: str, colonne: str) -> list:
    from psycopg2 import sql
    obj = get_object(source, objet)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT {c} FROM {t} WHERE _batch_id = %s ORDER BY _row_number").format(
            c=sql.Identifier(colonne), t=sql.Identifier(STAGING_SCHEMA, obj.stg_table)), (batch_id,))
        return [r[0] for r in cur.fetchall()]


# -----------------------------------------------------------------------------
# Porte G2
# -----------------------------------------------------------------------------
def verify(batch: Batch, sources: list[str] | None = None, conn=None, recompter=compter_source) -> list[Check]:
    import psycopg2
    manifest = read_manifest(batch)
    propre = conn is None
    conn = conn or psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    checks: list[Check] = []
    try:
        conn.autocommit = True
        for cle, info in sorted(manifest["objets"].items()):
            source, objet, extrait = info["source"], info["objet"], info["nb_lignes"]
            if sources and source not in sources:
                continue
            obj = get_object(source, objet)
            try:
                n_source = recompter(source, objet)
                checks.append(Check("G2.1", cle, "Toutes les lignes extraites", n_source == extrait,
                                    f"source={n_source}, extraites={extrait}"))
            except Exception as exc:
                checks.append(Check("G2.1", cle, "Toutes les lignes extraites", False, f"source injoignable : {exc}"))

            with conn.cursor() as cur:
                from psycopg2 import sql
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {} WHERE _batch_id = %s").format(
                    sql.Identifier(STAGING_SCHEMA, obj.stg_table)), (batch.batch_id,))
                n_stg = cur.fetchone()[0]
            checks.append(Check("G2.2", cle, "Toutes les lignes chargées", n_stg == extrait,
                                f"staging={n_stg}, extraites={extrait}"))

            if obj.colonnes_json:
                colonne = "event_id" if source == "s4_mongodb" else "cle"
                idx = obj.colonnes.index(colonne)
                fichier = [row[idx] for row in read_landing(batch, obj)]
                base = identifiants_staging(conn, batch.batch_id, source, objet, colonne)
                checks.append(Check("G2.3", cle, "Aucune valeur altérée", fichier == base,
                                    f"{len(base)} {colonne} identiques et dans le même ordre" if fichier == base
                                    else "écart entre le fichier et le staging"))
            else:
                e_stg = empreinte_staging(conn, batch.batch_id, source, objet)
                checks.append(Check("G2.3", cle, "Aucune valeur altérée", e_stg == info["empreinte"],
                                    f"empreinte {e_stg[:12]}… {'=' if e_stg == info['empreinte'] else '≠'} "
                                    f"{info['empreinte'][:12]}…"))

            with conn.cursor() as cur:
                cur.execute("""SELECT etape, statut FROM meta.etl_execution_log
                               WHERE batch_id = %s AND code_source = %s AND objet = %s""", (batch.batch_id, source, objet))
                etapes = {(e, s) for e, s in cur.fetchall()}
                cur.execute("""SELECT dernier_batch_id, derniere_nb_lignes, dernier_statut FROM meta.metadata_sources
                               WHERE code_source = %s AND objet = %s""", (source, objet))
                meta_src = cur.fetchone()
            ok_log = {("EXTRACT", "SUCCES"), ("LOAD", "SUCCES")} <= etapes
            checks.append(Check("G2.4", cle, "Journal d'exécution (EXTRACT, LOAD)", ok_log,
                                ", ".join(sorted(f"{e}={s}" for e, s in etapes)) or "aucune trace"))
            ok_meta = meta_src == (batch.batch_id, extrait, "SUCCES")
            checks.append(Check("G2.5", cle, "metadata_sources à jour", ok_meta, f"{meta_src}"))
        return checks
    finally:
        if propre:
            conn.close()


def write_report(batch: Batch, checks: list[Check]) -> str:
    path = get_settings().paths.reports_dir / f"G2_{batch.batch_id}.md"
    ok = all(c.ok for c in checks)
    lignes = [f"# Porte G2 — Lot {batch.batch_id}", "",
              f"*Extraction du {batch.extracted_at:%d/%m/%Y %H:%M:%S} — rapport du {datetime.now():%d/%m/%Y %H:%M}*", "",
              f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** ({sum(c.ok for c in checks)}/{len(checks)} contrôles)", "",
              "| Contrôle | Objet | Libellé | Détail | OK |", "|---|---|---|---|:-:|",
              *[f"| {c.code} | {c.objet} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lignes), encoding="utf-8")
    return str(path)


def main() -> int:
    try:
        lot = latest_batch()
        checks = verify(lot)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    for c in checks:
        (logger.info if c.ok else logger.error)("[%s] %s %-28s %-36s %s", "OK" if c.ok else "KO", c.code, c.objet, c.libelle, c.detail)
    logger.info("Porte G2 (%s) : %d/%d - rapport : %s", lot.batch_id, sum(c.ok for c in checks), len(checks),
                write_report(lot, checks))
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
