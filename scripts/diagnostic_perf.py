"""
scripts/diagnostic_perf.py — Diagnostic de performance de l'entrepôt (Lot L6)
============================================================================

Répond objectivement à trois questions :
    1. Les réglages de docker/docker-compose.perf.yml sont-ils actifs ?
    2. Les tables staging et clean sont-elles bien UNLOGGED ?
    3. Quelles instructions SQL d'une transformation sont lentes ? (option --profil)

Le profil exécute le script clean d'une source instruction par instruction, en
les chronométrant, DANS UNE TRANSACTION ANNULÉE à la fin : rien n'est modifié.
Il affiche aussi le plan (EXPLAIN) de l'instruction la plus lente.

    python -m scripts.diagnostic_perf
    python -m scripts.diagnostic_perf --profil s2_mysql
"""

from __future__ import annotations

import argparse
import sys
import time

from common.config import get_settings

REGLAGES = ("server_version", "shared_buffers", "work_mem", "maintenance_work_mem", "max_wal_size",
            "checkpoint_timeout", "wal_compression", "synchronous_commit")
ATTENDU_PERF = {"shared_buffers": "512MB", "max_wal_size": "4GB", "synchronous_commit": "off"}


def decouper(sql: str) -> list[str]:
    """Découpe un script en instructions (respecte '…', $$…$$ et $q$…$q$)."""
    instructions, courant, i, dollar, quote = [], [], 0, None, False
    while i < len(sql):
        c = sql[i]
        if dollar:
            if sql.startswith(dollar, i):
                courant.append(dollar); i += len(dollar); dollar = None; continue
        elif quote:
            if c == "'":
                quote = False
        elif c == "'":
            quote = True
        elif c == "-" and sql.startswith("--", i):
            fin = sql.find("\n", i)
            i = len(sql) if fin < 0 else fin
            continue
        elif c == "$":
            j = sql.find("$", i + 1)
            balise = sql[i:j + 1] if j > 0 else ""
            if balise and all(ch.isalnum() or ch == "_" for ch in balise[1:-1]):
                dollar = balise; courant.append(balise); i = j + 1; continue
        elif c == ";":
            instr = "".join(courant).strip()
            if instr:
                instructions.append(instr)
            courant, i = [], i + 1
            continue
        courant.append(c)
        i += 1
    reste = "".join(courant).strip()
    if reste:
        instructions.append(reste)
    return instructions


def etat(cur) -> None:
    print("\n1. Réglages de PostgreSQL (entrepôt)")
    for r in REGLAGES:
        cur.execute(f"SHOW {r}")
        v = cur.fetchone()[0]
        attendu = ATTENDU_PERF.get(r)
        marque = "" if attendu is None else ("   ✅ perf.yml actif" if v == attendu else f"   ❌ attendu {attendu} : perf.yml NON appliqué")
        print(f"   {r:<22} {v}{marque}")
    print("\n2. Tables UNLOGGED (u) ou journalisées (p)")
    # Les 4 référentiels clean.ref_* sont journalisés VOLONTAIREMENT : minuscules, et ce sont des données de référence
    cur.execute("""SELECT CASE WHEN n.nspname = 'clean' AND c.relname LIKE 'ref\\_%' THEN 'clean.ref_*' ELSE n.nspname END,
                          c.relpersistence, COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relkind = 'r' AND n.nspname IN ('staging', 'clean', 'dw') GROUP BY 1, 2 ORDER BY 1, 2""")
    for schema, p, n in cur.fetchall():
        attendu = {"staging": "u", "clean": "u", "clean.ref_*": "p", "dw": "p"}[schema]
        print(f"   {schema:<12} {'UNLOGGED' if p == 'u' else 'journalisée':<12} {n:>3} table(s)   {'✅' if p == attendu else '❌'}")
    print("\n3. Checkpoints depuis le démarrage (« demandés » élevé = WAL trop petit)")
    try:
        cur.execute("SELECT num_timed, num_requested FROM pg_stat_checkpointer")          # PostgreSQL 17+
    except Exception:
        cur.connection.rollback()
        cur.execute("SELECT checkpoints_timed, checkpoints_req FROM pg_stat_bgwriter")   # PostgreSQL 15-16
    timed, req = cur.fetchone()
    print(f"   programmés : {timed}   demandés (WAL plein) : {req}")


def profil(conn, source: str, top: int = 8) -> None:
    from pipeline.transform import SQL_SOURCES, _parametres, batch_en_staging
    instructions = decouper(SQL_SOURCES[source].read_text(encoding="utf-8"))
    conn.autocommit = False
    _parametres(conn, batch_en_staging(conn))
    mesures = []
    print(f"\n4. Profil de {source} ({len(instructions)} instructions, transaction annulée à la fin)")
    t_total = time.perf_counter()
    try:
        with conn.cursor() as cur:
            for instr in instructions:
                t0 = time.perf_counter()
                cur.execute(instr)
                mesures.append((time.perf_counter() - t0, instr))
            lente = max(mesures)[1]
            plan = None
            if lente.upper().startswith(("CREATE", "SELECT", "INSERT")) and " AS\n" in lente or lente.upper().startswith("SELECT"):
                requete = lente.split(" AS\n", 1)[1] if lente.upper().startswith("CREATE") else lente
                cur.execute("EXPLAIN " + requete)
                plan = [r[0] for r in cur.fetchall()]
    finally:
        conn.rollback()
    print(f"   durée totale : {time.perf_counter() - t_total:.1f} s")
    for d, instr in sorted(mesures, reverse=True)[:top]:
        print(f"   {d:8.2f} s  {' '.join(instr.split())[:110]}")
    if plan:
        print("\n   Plan de l'instruction la plus lente (« Nested Loop » sur de gros volumes = mauvais plan) :")
        for ligne in plan[:15]:
            print("     " + ligne)


def main(argv: list[str] | None = None) -> int:
    import psycopg2
    from pipeline.transform import SQL_SOURCES
    parser = argparse.ArgumentParser(description="Diagnostic de performance de l'entrepôt")
    parser.add_argument("--profil", choices=list(SQL_SOURCES), help="chronométrer le script clean d'une source")
    args = parser.parse_args(argv)
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        with conn.cursor() as cur:
            etat(cur)
        conn.rollback()
        if args.profil:
            profil(conn, args.profil)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
