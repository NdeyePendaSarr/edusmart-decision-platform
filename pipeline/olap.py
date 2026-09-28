"""
pipeline/olap.py — Exploration du cube EduSmart (Phase 10, Lot L7)
=================================================================

Exécute les requêtes de pipeline/sql/olap/01 à 06 (cube, roll up, drill down, slice, dice, pivot)
et rassemble leurs résultats dans data/reports/olap_<lot>.md.

Chaque fichier contient des blocs introduits par « -- @titre … » : un bloc = une instruction.
Les deux cubes (dw.cube_finance, dw.cube_pedagogie) sont matérialisés dans le DW.

    python -m pipeline.olap
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from common.config import get_settings
from common.logger import get_logger

logger = get_logger("olap")
SQL_OLAP = Path(__file__).resolve().parent / "sql" / "olap"
OPERATIONS = {"01_cube.sql": "Cube", "02_roll_up.sql": "Roll up", "03_drill_down.sql": "Drill down",
              "04_slice.sql": "Slice", "05_dice.sql": "Dice", "06_pivot.sql": "Pivot"}


def blocs(texte: str) -> list[tuple[str, str]]:
    """(titre, instruction SQL) pour chaque bloc « -- @titre » d'un fichier."""
    res = []
    for morceau in texte.split("-- @titre ")[1:]:
        titre, _, sql = morceau.partition("\n")
        instructions = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
        res += [(titre.strip(), i) for i in instructions]
    return res


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) or (hasattr(v, "is_finite") and v == v.to_integral_value() and abs(v) >= 1000):
        return f"{v:,.0f}".replace(",", " ")
    return str(v)


def executer(conn) -> list[tuple[str, str, list[str], list[tuple]]]:
    resultats = []
    with conn.cursor() as cur:
        for fichier, operation in OPERATIONS.items():
            for titre, sql in blocs((SQL_OLAP / fichier).read_text(encoding="utf-8")):
                cur.execute(sql)
                if cur.description:                              # une requête qui renvoie des lignes
                    resultats.append((operation, titre, [d[0] for d in cur.description], cur.fetchall()))
    conn.commit()
    return resultats


def ecrire(batch_id: str, resultats) -> str:
    md = [f"# Exploration du cube EduSmart — lot {batch_id}", "",
          f"*Phase 10 · généré le {datetime.now():%d/%m/%Y %H:%M} par `pipeline/olap.py` · montants en XOF*", ""]
    for operation, titre, colonnes, lignes in resultats:
        md += [f"## {operation} — {titre}", "", "| " + " | ".join(colonnes) + " |",
               "|" + "|".join("---" for _ in colonnes) + "|",
               *["| " + " | ".join(_fmt(v) for v in ligne) + " |" for ligne in lignes], ""]
    chemin = get_settings().paths.reports_dir / f"olap_{batch_id}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(md), encoding="utf-8")
    return str(chemin)


def main() -> int:
    import psycopg2
    from pipeline.kpi import dernier_lot_dw
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        batch_id = dernier_lot_dw(conn)
        resultats = executer(conn)
    finally:
        conn.close()
    for operation, titre, _, lignes in resultats:
        logger.info("[%s] %s : %d ligne(s)", operation, titre, len(lignes))
    logger.info("Exploration du cube : %s", ecrire(batch_id, resultats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
