"""
sources/s1_postgresql/verify_source.py — Porte G1 de la Source 1 (Lot L2-a)
==========================================================================

Répond à l'étape 4 du document de cadrage (« Vérifier la cohérence de la
source ») en interrogeant DIRECTEMENT la base edusmart_academic :

    V1  Volumes : 10 000 / 25 / 150 exacts ; inscriptions et paiements à ±5 %
        des cibles validées (18 000 et 40 000).
    V2  Anomalies : pour chacun des 16 types, le nombre MESURÉ en base est
        égal au journal, et le taux est compris entre 2 % et 5 % (sauf A07,
        fixé par le catalogue).
    V3  Contraintes : les 4 contraintes « anomalies » sont NON validées, les
        7 autres sont validées (lecture de pg_constraint).
    V4  Relations internes : aucune classe, inscription ou paiement orphelin,
        hormis les paiements orphelins volontaires (A16).
    V5  Référentiel : les étudiants en base sont exactement les 10 000
        étudiants PostgreSQL du référentiel maître, et les 9 000 matricules
        de mapping_etudiants.csv existent en base.

Produit un rapport Markdown : data/reports/s1_postgresql_G1.md
Code de sortie : 0 si G1 est validée, 1 sinon.

Exécution : python -m sources.s1_postgresql.verify_source
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime

from common.anomaly_journal import read_journal
from common.config import ConfigError, get_settings
from common.logger import get_logger
from common.referential import MAPPING_ETUDIANTS_FILENAME, STATUT_LMS_ORPHELIN, load_referential
from sources.s1_postgresql.anomalies import ANOMALY_TYPES, FIXED_BY_DESIGN, SOURCE, measure_anomalies
from sources.s1_postgresql.generate_data import TARGETS, TOLERANCE

logger = get_logger("s1_verify")

EXPECTED_NOT_VALIDATED = {"ck_etudiants_sexe", "ck_inscriptions_reduction",
                          "ck_paiements_montant", "fk_paiements_inscription"}
EXPECTED_VALIDATED = {"ck_etudiants_date_naissance", "ck_filieres_duree", "ck_filieres_cout",
                      "ck_classes_capacite", "fk_classes_filiere", "fk_inscriptions_etudiant",
                      "fk_inscriptions_classe"}

# Colonnes nécessaires à la mesure des anomalies (on évite SELECT *)
MEASURE_QUERIES = {
    "etudiants": "SELECT id_etudiant, matricule, sexe, telephone, adresse, ville, nom FROM etudiants",
    "filieres": "SELECT id_filiere, nom_filiere FROM filieres",
    "classes": "SELECT id_classe, code_classe, salle, annee_academique FROM classes",
    "inscriptions": "SELECT id_inscription, id_etudiant, id_classe, reduction, date_inscription FROM inscriptions",
    "paiements": "SELECT id_paiement, id_inscription, reference, montant, mode_paiement FROM paiements",
}


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


def _fetch_tables(conn) -> dict[str, list[dict]]:
    from psycopg2.extras import RealDictCursor
    tables = {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for table, query in MEASURE_QUERIES.items():
            cur.execute(query)
            tables[table] = [dict(r) for r in cur.fetchall()]
    return tables


def _scalar(conn, query: str):
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchone()[0]


def check_volumes(tables) -> list[Check]:
    checks = []
    for table, cible in TARGETS.items():
        n = len(tables[table])
        if table in ("inscriptions", "paiements"):
            ok = abs(n - cible) <= TOLERANCE * cible
            detail = f"{n} lignes (cible ~{cible}, écart {100 * (n - cible) / cible:+.1f} %)"
        else:
            ok = n == cible
            detail = f"{n} lignes (attendu {cible})"
        checks.append(Check("V1", f"Volume {table}", ok, detail))
    return checks


def check_anomalies(tables, gen, journal_counts, summary) -> tuple[list[Check], list[dict]]:
    mesure = measure_anomalies(tables, gen)
    checks, lignes = [], []
    for code, t in ANOMALY_TYPES.items():
        base = summary["anomalies"][code]["base"]
        n_journal, n_base = journal_counts.get(code, 0), mesure[code]
        taux = n_base / base
        taux_ok = code in FIXED_BY_DESIGN or gen.taux_anomalie_min <= taux <= gen.taux_anomalie_max
        ok = n_journal == n_base and n_base > 0 and taux_ok
        lignes.append({"code": code, "table": t.table, "colonne": t.colonne, "description": t.description,
                       "journal": n_journal, "base": n_base, "taux": taux, "ok": ok})
        checks.append(Check("V2", f"Anomalie {code}", ok,
                            f"base={n_base}, journal={n_journal}, taux={100 * taux:.2f} %"))
    return checks, lignes


def check_constraints(conn) -> list[Check]:
    with conn.cursor() as cur:
        cur.execute("""SELECT conname, convalidated FROM pg_constraint
                       WHERE connamespace = 'public'::regnamespace AND contype IN ('c', 'f')""")
        state = dict(cur.fetchall())
    checks = []
    for name in sorted(EXPECTED_NOT_VALIDATED | EXPECTED_VALIDATED):
        attendu = name in EXPECTED_VALIDATED
        present = name in state
        ok = present and state[name] == attendu
        etat = "absente" if not present else ("validée" if state[name] else "NOT VALID")
        checks.append(Check("V3", f"Contrainte {name}", ok,
                            f"{etat} (attendu : {'validée' if attendu else 'NOT VALID'})"))
    return checks


def check_relations(conn, journal_counts) -> list[Check]:
    requetes = {
        "classes -> filieres": ("""SELECT COUNT(*) FROM classes c
                                   WHERE NOT EXISTS (SELECT 1 FROM filieres f WHERE f.id_filiere = c.id_filiere)""", 0),
        "inscriptions -> etudiants": ("""SELECT COUNT(*) FROM inscriptions i
                                   WHERE NOT EXISTS (SELECT 1 FROM etudiants e WHERE e.id_etudiant = i.id_etudiant)""", 0),
        "inscriptions -> classes": ("""SELECT COUNT(*) FROM inscriptions i
                                   WHERE NOT EXISTS (SELECT 1 FROM classes c WHERE c.id_classe = i.id_classe)""", 0),
        "paiements -> inscriptions": ("""SELECT COUNT(*) FROM paiements p
                                   WHERE NOT EXISTS (SELECT 1 FROM inscriptions i WHERE i.id_inscription = p.id_inscription)""",
                                      journal_counts.get("A16", 0)),
        "étudiants sans inscription": ("""SELECT COUNT(*) FROM etudiants e
                                   WHERE NOT EXISTS (SELECT 1 FROM inscriptions i WHERE i.id_etudiant = e.id_etudiant)""", 0),
    }
    checks = []
    for libelle, (query, attendu) in requetes.items():
        n = _scalar(conn, query)
        checks.append(Check("V4", f"Relation {libelle}", n == attendu, f"{n} orphelin(s) (attendu {attendu})"))
    return checks


def check_referential(tables, settings) -> list[Check]:
    ref = [s for s in load_referential() if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    attendu = {(s.id_etudiant, s.matricule) for s in ref}
    en_base = {(str(e["id_etudiant"]), e["matricule"]) for e in tables["etudiants"]}
    checks = [Check("V5", "Étudiants = référentiel maître", attendu == en_base,
                    f"{len(en_base & attendu)} communs, {len(en_base - attendu)} inconnus, "
                    f"{len(attendu - en_base)} manquants")]
    mapping_path = settings.paths.mappings_dir / MAPPING_ETUDIANTS_FILENAME
    with mapping_path.open(encoding="utf-8", newline="") as handle:
        mapping = {row["matricule"] for row in csv.DictReader(handle)}
    matricules = {e["matricule"] for e in tables["etudiants"]}
    checks.append(Check("V5", "mapping_etudiants -> etudiants", mapping <= matricules,
                        f"{len(mapping & matricules)}/{len(mapping)} matricules du mapping trouvés en base"))
    return checks


def write_report(path, checks, anomalies, volumes) -> None:
    ok = all(c.ok for c in checks)
    lines = [
        "# Porte G1 — Source 1 : PostgreSQL « Gestion académique »", "",
        f"*Rapport généré le {datetime.now():%Y-%m-%d %H:%M}*", "",
        f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** "
        f"({sum(c.ok for c in checks)}/{len(checks)} contrôles réussis)", "",
        "## Volumes", "", "| Table | Lignes |", "|---|---:|",
        *[f"| {t} | {n:,} |".replace(",", " ") for t, n in volumes.items()], "",
        "## Anomalies (mesurées en base)", "",
        "| Code | Table.colonne | Description | Journal | En base | Taux | OK |",
        "|---|---|---|---:|---:|---:|:-:|",
        *[f"| {a['code']} | {a['table']}.{a['colonne']} | {a['description']} | {a['journal']} | "
          f"{a['base']} | {100 * a['taux']:.2f} % | {'✅' if a['ok'] else '❌'} |" for a in anomalies], "",
        "## Tous les contrôles", "", "| Groupe | Contrôle | Détail | OK |", "|---|---|---|:-:|",
        *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    import psycopg2

    settings = get_settings()
    gen = settings.generation
    journal_path = settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv"
    summary_path = settings.paths.generated_dir / SOURCE / "summary.json"
    try:
        journal_counts: dict[str, int] = {}
        for r in read_journal(journal_path):
            journal_counts[r.code] = journal_counts.get(r.code, 0) + 1
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

        conn = psycopg2.connect(**settings.pg_source.connect_kwargs())
        try:
            tables = _fetch_tables(conn)
            checks = check_volumes(tables)
            anomaly_checks, anomaly_rows = check_anomalies(tables, gen, journal_counts, summary)
            checks += anomaly_checks
            checks += check_constraints(conn)
            checks += check_relations(conn, journal_counts)
            checks += check_referential(tables, settings)
        finally:
            conn.close()

        for c in checks:
            (logger.info if c.ok else logger.error)("[%s] %s %-40s %s", "OK" if c.ok else "KO", c.code,
                                                    c.libelle, c.detail)
        report = settings.paths.reports_dir / f"{SOURCE}_G1.md"
        write_report(report, checks, anomaly_rows, {t: len(v) for t, v in tables.items()})
        nb_ok = sum(c.ok for c in checks)
        logger.info("Porte G1 Source 1 : %d/%d contrôles réussis - rapport : %s", nb_ok, len(checks), report)
        return 0 if nb_ok == len(checks) else 1
    except FileNotFoundError as exc:
        logger.error("Fichier introuvable : %s (lancez generate_data puis insert_data)", exc.filename)
        return 1
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la vérification G1")
        return 2


if __name__ == "__main__":
    sys.exit(main())
