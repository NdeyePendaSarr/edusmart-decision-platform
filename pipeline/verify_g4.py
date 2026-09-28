"""
pipeline/verify_g4.py — Porte G4 : le Data Warehouse est-il juste ? (Lot L6)
===========================================================================

    G4.1 Clés étrangères valides : aucun fait ne pointe hors de sa dimension
    G4.2 Grain respecté : aucune ligne en double sur le grain déclaré de chaque fait
    G4.3 Complétude : chaque fait contient exactement les lignes de sa table clean
    G4.4 Mesures réconciliées : sommes du DW = sommes de la couche clean
    G4.5 SCD 2 : une seule version courante par étudiant, périodes sans chevauchement
         ni trou, 10 500 étudiants courants (définition L3)
    G4.6 Membres « Inconnu » : aucun fait sans étudiant ni sans date (information pour les autres dimensions)

Rapport : data/reports/G4_<lot>.md
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime

from common.config import get_settings
from common.logger import get_logger

logger = get_logger("verify_g4")


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


FK = {  # fait -> [(colonne, dimension, clé)]
    "fact_paiements": [("date_key", "dim_temps", "date_key"), ("etudiant_key", "dim_etudiant", "etudiant_key"),
                       ("formation_key", "dim_formation", "formation_key"), ("region_key", "dim_region", "region_key")],
    "fact_inscriptions": [("date_key", "dim_temps", "date_key"), ("etudiant_key", "dim_etudiant", "etudiant_key"),
                          ("formation_key", "dim_formation", "formation_key"), ("region_key", "dim_region", "region_key")],
    "fact_notes": [("date_key", "dim_temps", "date_key"), ("etudiant_key", "dim_etudiant", "etudiant_key"),
                   ("quiz_key", "dim_quiz", "quiz_key"), ("module_key", "dim_module", "module_key")],
    "fact_quiz_activite": [("date_key", "dim_temps", "date_key"), ("etudiant_key", "dim_etudiant", "etudiant_key"),
                           ("quiz_key", "dim_quiz", "quiz_key"), ("module_key", "dim_module", "module_key"),
                           ("region_key", "dim_region", "region_key")],
    "fact_connexions": [("date_key", "dim_temps", "date_key"), ("etudiant_key", "dim_etudiant", "etudiant_key")],
    "fact_progression": [("date_key", "dim_temps", "date_key"), ("etudiant_key", "dim_etudiant", "etudiant_key"),
                         ("module_key", "dim_module", "module_key")],
    "fact_salaires": [("date_key", "dim_temps", "date_key"), ("enseignant_key", "dim_enseignant", "enseignant_key")],
    "fact_absences": [("date_key", "dim_temps", "date_key"), ("enseignant_key", "dim_enseignant", "enseignant_key")],
}
GRAIN = {"fact_paiements": "id_paiement", "fact_inscriptions": "id_inscription", "fact_notes": "id_note",
         "fact_quiz_activite": "event_id", "fact_connexions": "id_connexion",
         "fact_progression": "etudiant_id, module_key", "fact_salaires": "enseignant_key, date_key",
         "fact_absences": "id_absence"}
SOURCE_CLEAN = {"fact_paiements": "SELECT COUNT(*) FROM clean.paiements", "fact_inscriptions": "SELECT COUNT(*) FROM clean.inscriptions",
                "fact_notes": "SELECT COUNT(*) FROM clean.notes",
                "fact_quiz_activite": "SELECT COUNT(*) FROM clean.evenements WHERE event_type IN ('QUIZ_STARTED', 'QUIZ_SUBMITTED')",
                "fact_connexions": "SELECT COUNT(*) FROM clean.temps_connexion", "fact_progression": "SELECT COUNT(*) FROM clean.progression",
                "fact_salaires": "SELECT COUNT(*) FROM clean.salaires", "fact_absences": "SELECT COUNT(*) FROM clean.absences"}
MESURES = [("Montant des paiements", "SELECT SUM(montant) FROM dw.fact_paiements", "SELECT SUM(montant) FROM clean.paiements"),
           ("Chiffre d'affaires (VALIDE, non négatif)", "SELECT SUM(montant_ca) FROM dw.fact_paiements",
            "SELECT SUM(montant) FROM clean.paiements WHERE statut = 'VALIDE' AND NOT montant_negatif"),
           ("Masse salariale nette", "SELECT SUM(salaire_net) FROM dw.fact_salaires", "SELECT SUM(salaire_net) FROM clean.salaires"),
           ("Durée totale de connexion (s)", "SELECT SUM(duree_secondes) FROM dw.fact_connexions",
            "SELECT SUM(duree_secondes) FROM clean.temps_connexion"),
           ("Somme des scores", "SELECT SUM(score) FROM dw.fact_notes", "SELECT SUM(score) FROM clean.notes")]


def _v(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def verify(conn) -> list[Check]:
    checks = []
    with conn.cursor() as cur:
        for fait, fks in FK.items():
            for col, dim, cle in fks:
                n = _v(cur, f"SELECT COUNT(*) FROM dw.{fait} f WHERE NOT EXISTS (SELECT 1 FROM dw.{dim} d WHERE d.{cle} = f.{col})")
                checks.append(Check("G4.1", f"{fait}.{col} -> {dim}", n == 0, f"{n} clé(s) orpheline(s)"))
        for fait, grain in GRAIN.items():
            n = _v(cur, f"SELECT COUNT(*) - COUNT(DISTINCT ({grain})) FROM dw.{fait}")
            checks.append(Check("G4.2", f"Grain de {fait} ({grain})", n == 0, f"{n} doublon(s) sur le grain"))
        for fait, sql in SOURCE_CLEAN.items():
            n_dw, n_clean = _v(cur, f"SELECT COUNT(*) FROM dw.{fait}"), _v(cur, sql)
            checks.append(Check("G4.3", f"Lignes de {fait}", n_dw == n_clean, f"DW={n_dw}, clean={n_clean}"))
        for libelle, sql_dw, sql_clean in MESURES:
            a, b = _v(cur, sql_dw), _v(cur, sql_clean)
            checks.append(Check("G4.4", libelle, a == b, f"DW={a}, clean={b}"))
        courants = _v(cur, "SELECT COUNT(*) FROM dw.dim_etudiant WHERE est_courant AND etudiant_key <> -1")
        plusieurs = _v(cur, "SELECT COUNT(*) FROM (SELECT etudiant_id FROM dw.dim_etudiant WHERE est_courant GROUP BY 1 HAVING COUNT(*) > 1) x")
        chevauch = _v(cur, """SELECT COUNT(*) FROM dw.dim_etudiant a JOIN dw.dim_etudiant b ON a.etudiant_id = b.etudiant_id
                              AND a.etudiant_key < b.etudiant_key AND a.date_debut <= b.date_fin AND b.date_debut <= a.date_fin""")
        trous = _v(cur, """SELECT COUNT(*) FROM (SELECT date_debut, lag(date_fin) OVER (PARTITION BY etudiant_id ORDER BY version) AS fin_prec
                           FROM dw.dim_etudiant) x WHERE fin_prec IS NOT NULL AND date_debut <> fin_prec + 1""")
        cur.execute("SELECT rapprochement, COUNT(*) FROM dw.dim_etudiant WHERE est_courant AND etudiant_key <> -1 GROUP BY 1 ORDER BY 1")
        repartition = dict(cur.fetchall())
        versions = _v(cur, "SELECT COUNT(*) FROM dw.dim_etudiant WHERE version > 1")
        checks += [Check("G4.5", "10 500 étudiants courants (définition L3)", courants == 10_500, f"{courants} : {repartition}"),
                   Check("G4.5", "Une seule version courante par étudiant", plusieurs == 0, f"{plusieurs} étudiant(s) en défaut"),
                   Check("G4.5", "Périodes de validité sans chevauchement", chevauch == 0, f"{chevauch} chevauchement(s)"),
                   Check("G4.5", "Versions contiguës (sans trou)", trous == 0, f"{trous} trou(s) ; {versions} version(s) > 1")]
        for fait, col in (("fact_paiements", "etudiant_key"), ("fact_notes", "etudiant_key"), ("fact_connexions", "etudiant_key"),
                          ("fact_quiz_activite", "etudiant_key"), ("fact_inscriptions", "etudiant_key")):
            n = _v(cur, f"SELECT COUNT(*) FROM dw.{fait} WHERE {col} = -1 OR date_key = -1")
            checks.append(Check("G4.6", f"{fait} : étudiant et date connus", n == 0, f"{n} fait(s) rattaché(s) à « Inconnu »"))
        n = _v(cur, "SELECT COUNT(*) FROM dw.fact_quiz_activite WHERE quiz_key = -1")
        checks.append(Check("G4.6", "fact_quiz_activite : quiz non résolu (information)", True,
                            f"{n} événements dont le code QUIZ-n est absent de mapping_courses (5 % voulus)"))
    return checks


def write_report(checks: list[Check], batch_id: str) -> str:
    ok = all(c.ok for c in checks)
    lignes = [f"# Porte G4 — Data Warehouse, lot {batch_id}", "", f"*Rapport du {datetime.now():%d/%m/%Y %H:%M}*", "",
              f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** ({sum(c.ok for c in checks)}/{len(checks)} contrôles)", "",
              "| Contrôle | Libellé | Détail | OK |", "|---|---|---|:-:|",
              *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], ""]
    path = get_settings().paths.reports_dir / f"G4_{batch_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lignes), encoding="utf-8")
    return str(path)


def main() -> int:
    import psycopg2
    from pipeline.transform import batch_en_staging
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        checks, batch_id = verify(conn), batch_en_staging(conn)
    finally:
        conn.close()
    for c in checks:
        (logger.info if c.ok else logger.error)("[%s] %s %-48s %s", "OK" if c.ok else "KO", c.code, c.libelle, c.detail)
    logger.info("Porte G4 : %d/%d - %s", sum(c.ok for c in checks), len(checks), write_report(checks, batch_id))
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
