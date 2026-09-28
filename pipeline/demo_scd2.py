"""
pipeline/demo_scd2.py — Démonstration SCD 2 : « un étudiant change de ville » (Phase 9, Lot L6)
==============================================================================================

Scénario (validé en Étape 2 : environ 2 % de déménagements, puis un second chargement) :
    1. 200 étudiants (2 %), tirés avec une graine fixe parmi ceux dont la ville est
       déjà canonique, déménagent vers une ville d'une AUTRE région.
       La modification est faite DANS LA SOURCE PostgreSQL, comme dans la vraie vie ;
    2. le pipeline tourne pour la Source 1 : extraction, staging, G2, clean, G3, DW, G4 ;
    3. contrôles : 2 versions pour chaque étudiant déplacé, l'ancienne fermée la veille
       de la date d'effet, la nouvelle courante ; les paiements passés restent rattachés
       à l'ANCIENNE région (l'historique n'est pas réécrit).

La liste des déménagements est conservée : --restaurer remet les villes d'origine dans la source.
Pour repartir d'un DW sans historique : python -m pipeline.load_dw --reset

    python -m pipeline.demo_scd2               # démonstration complète
    python -m pipeline.demo_scd2 --restaurer   # remet les villes d'origine dans la source
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import datetime

from common import senegalese_data as sn
from common.config import get_settings
from common.logger import get_logger

logger = get_logger("demo_scd2")
TAUX = 0.02
GRAINE = 2026


def fichier_demenagements():
    return get_settings().paths.reports_dir / "demo_scd2_demenagements.csv"


def choisir_demenagements(etudiants: list[tuple[str, str, str, str]], taux: float = TAUX, graine: int = GRAINE) -> list[dict]:
    """
    etudiants : (id_etudiant, matricule, ville, sexe) triés. Fonction PURE et déterministe.
    Candidats : ville canonique (pas d'interférence avec l'anomalie A05) ET sexe M/F :
    la contrainte CHECK ... NOT VALID de la source tolère les anciennes lignes A01,
    mais s'applique à toute ligne MODIFIÉE (leçon du volet A).
    La nouvelle ville est dans une AUTRE région, pour rendre le changement visible.
    """
    rng = random.Random(graine)
    candidats = [e for e in etudiants if e[2] in sn.CITY_TO_REGION and e[3] in ("M", "F")]
    choisis = rng.sample(candidats, round(len(etudiants) * taux))
    villes = sorted(sn.CITY_TO_REGION)
    res = []
    for id_etudiant, matricule, ville, _ in sorted(choisis, key=lambda e: e[1]):
        region = sn.CITY_TO_REGION[ville]
        nouvelle = rng.choice([v for v in villes if sn.CITY_TO_REGION[v] != region])
        res.append({"id_etudiant": id_etudiant, "matricule": matricule, "ancienne_ville": ville, "ancienne_region": region,
                    "nouvelle_ville": nouvelle, "nouvelle_region": sn.CITY_TO_REGION[nouvelle]})
    return res


def modifier_source(demenagements: list[dict], sens: str = "aller") -> int:
    import psycopg2
    conn = psycopg2.connect(**get_settings().pg_source.connect_kwargs())
    try:
        with conn, conn.cursor() as cur:
            for d in demenagements:
                v, r = ((d["nouvelle_ville"], d["nouvelle_region"]) if sens == "aller"
                        else (d["ancienne_ville"], d["ancienne_region"]))
                cur.execute("UPDATE etudiants SET ville = %s, region = %s WHERE id_etudiant = %s", (v, r, d["id_etudiant"]))
        return len(demenagements)
    finally:
        conn.close()


def controler(demenagements: list[dict]) -> list[tuple[str, bool, str]]:
    import psycopg2
    ids = [d["id_etudiant"] for d in demenagements]
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    res = []
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(DISTINCT etudiant_id) FROM dw.dim_etudiant
                           WHERE etudiant_id = ANY(%s) AND version = 2 AND est_courant""", (ids,))
            n2 = cur.fetchone()[0]
            res.append(("Chaque étudiant déplacé a une version 2 courante", n2 == len(ids), f"{n2}/{len(ids)}"))
            cur.execute("""SELECT COUNT(*) FROM dw.dim_etudiant v1 JOIN dw.dim_etudiant v2
                               ON v1.etudiant_id = v2.etudiant_id AND v1.version = 1 AND v2.version = 2
                           WHERE v1.etudiant_id = ANY(%s) AND NOT v1.est_courant AND v1.date_fin = v2.date_debut - 1""", (ids,))
            nf = cur.fetchone()[0]
            res.append(("Version 1 fermée la veille de la date d'effet", nf == len(ids), f"{nf}/{len(ids)}"))
            attendu = {d["id_etudiant"]: (d["nouvelle_ville"], d["ancienne_ville"]) for d in demenagements}
            cur.execute("""SELECT v2.etudiant_id, v2.ville, v1.ville FROM dw.dim_etudiant v1 JOIN dw.dim_etudiant v2
                               ON v1.etudiant_id = v2.etudiant_id AND v1.version = 1 AND v2.version = 2
                           WHERE v1.etudiant_id = ANY(%s)""", (ids,))
            justes = sum(1 for i, nv, av in cur.fetchall() if attendu[i] == (nv, av))
            res.append(("Ancienne et nouvelle villes exactes", justes == len(ids), f"{justes}/{len(ids)}"))
            cur.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE d.version = 1)
                           FROM dw.fact_paiements f JOIN dw.dim_etudiant d USING (etudiant_key)
                           WHERE d.etudiant_id = ANY(%s)""", (ids,))
            total, v1 = cur.fetchone()
            res.append(("Paiements passés rattachés à l'ancienne version (histoire préservée)", total == v1 and total > 0,
                        f"{v1}/{total} paiements sur la version 1"))
            cur.execute("SELECT COUNT(*) FROM dw.dim_etudiant WHERE est_courant AND etudiant_key <> -1")
            n = cur.fetchone()[0]
            res.append(("Toujours 10 500 étudiants courants", n == 10_500, str(n)))
    finally:
        conn.close()
    return res


def main(argv: list[str] | None = None) -> int:
    import psycopg2
    parser = argparse.ArgumentParser(description="Démonstration SCD 2 (déménagements)")
    parser.add_argument("--restaurer", action="store_true", help="remettre les villes d'origine dans la source")
    args = parser.parse_args(argv)
    chemin = fichier_demenagements()

    if args.restaurer:
        with chemin.open(encoding="utf-8", newline="") as h:
            demenagements = list(csv.DictReader(h))
        logger.info("%d étudiants remis dans leur ville d'origine (source PostgreSQL)", modifier_source(demenagements, "retour"))
        return 0

    conn = psycopg2.connect(**get_settings().pg_source.connect_kwargs())
    with conn.cursor() as cur:
        cur.execute("SELECT id_etudiant::TEXT, matricule, ville, sexe FROM etudiants ORDER BY matricule")
        etudiants = cur.fetchall()
    conn.close()
    demenagements = choisir_demenagements(etudiants)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(demenagements[0]))
        w.writeheader()
        w.writerows(demenagements)
    logger.info("%d déménagements écrits dans la source (liste : %s)", modifier_source(demenagements), chemin)

    from pipeline.run_pipeline import main as pipeline
    code = pipeline(["--sources", "s1_postgresql"])
    if code != 0:
        logger.error("Le second chargement a échoué (code %d)", code)
        return code
    resultats = controler(demenagements)
    lignes = [f"# Démonstration SCD 2 — {datetime.now():%d/%m/%Y %H:%M}", "",
              f"{len(demenagements)} étudiants ({TAUX:.0%}) ont changé de ville et de région dans la source, "
              "puis le pipeline a été relancé.", "", "| Contrôle | Résultat | OK |", "|---|---|:-:|",
              *[f"| {l} | {d} | {'✅' if ok else '❌'} |" for l, ok, d in resultats], "",
              "Exemples :", "", "| Matricule | Avant | Après |", "|---|---|---|",
              *[f"| {d['matricule']} | {d['ancienne_ville']} ({d['ancienne_region']}) | {d['nouvelle_ville']} ({d['nouvelle_region']}) |"
                for d in demenagements[:5]], ""]
    rapport = get_settings().paths.reports_dir / "demo_scd2.md"
    rapport.write_text("\n".join(lignes), encoding="utf-8")
    for l, ok, d in resultats:
        (logger.info if ok else logger.error)("[%s] %s : %s", "OK" if ok else "KO", l, d)
    logger.info("Rapport : %s", rapport)
    return 0 if all(ok for _, ok, _ in resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
