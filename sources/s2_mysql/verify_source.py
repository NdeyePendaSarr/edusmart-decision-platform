"""
sources/s2_mysql/verify_source.py — Porte G1 de la Source 2 (Lot L2-b)
=====================================================================

Interroge directement edusmart_learning :

    V1  Volumes : modules = 300 ; les 5 autres tables à ±5 % des cibles validées.
    V2  Anomalies : 16 types, mesure en base = journal, taux dans [2 %, 5 %].
    V3  Contraintes : CHECK actives / NOT ENFORCED conformes, 4 FK déclarées.
    V4  Relations : cours -> modules, quiz -> cours, notes -> quiz sans orphelin ;
        progression -> modules : uniquement les orphelins volontaires (B07).
    V5  Identifiants :
        - les student_code valides en base = les 9 500 comptes LMS du référentiel
          (9 000 APPARIE + 500 LMS_ORPHELIN), aucun code inconnu ;
          (les 1 000 étudiants SANS_LMS n'ont pas de compte) ;
        - chaque compte LMS a au moins une progression ;
        - mapping_courses.csv : identifiants MySQL existants, 95 % des cours
          et quiz présents, tous les modules présents.

Rapport : data/reports/s2_mysql_G1.md — Code de sortie : 0 si G1 est validée.
Exécution : python -m sources.s2_mysql.verify_source
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
from common.referential import (MAPPING_COURSES_FILENAME, MAPPING_ETUDIANTS_FILENAME, STATUT_APPARIE,
                                STATUT_LMS_ORPHELIN, load_referential)
from sources.s2_mysql.anomalies import ANOMALY_TYPES, SOURCE, STUDENT_CODE_RE, measure_anomalies
from sources.s2_mysql.generate_data import EXACT_TARGETS, TARGETS, TAUX_ABSENTS_MAPPING, TOLERANCE

logger = get_logger("s2_verify")

EXPECTED_CHECKS = {  # nom -> ENFORCED attendu
    "ck_modules_duree": "YES", "ck_cours_ordre": "YES", "ck_cours_duree": "YES",
    "ck_quiz_nb_questions": "YES", "ck_quiz_score_max": "YES", "ck_notes_score": "YES",
    "ck_quiz_duree": "NO", "ck_progression_pourcentage": "NO", "ck_temps_connexion_duree": "NO",
}
EXPECTED_FKS = {"fk_cours_module", "fk_quiz_cours", "fk_notes_quiz", "fk_progression_module"}

MEASURE_QUERIES = {
    "modules": "SELECT id_module, categorie, actif FROM modules",
    "cours": "SELECT id_cours, id_module, titre FROM cours",
    "quiz": "SELECT id_quiz, id_cours, nb_questions, score_max, duree_minutes FROM quiz",
    "notes": "SELECT id_note, id_quiz, student_code, tentative, date_passage, score FROM notes",
    "progression": "SELECT id_progression, student_code, id_module, pourcentage FROM progression",
    "temps_connexion": ("SELECT id_connexion, student_code, date_deconnexion, duree_minutes, appareil, "
                        "navigateur, adresse_ip FROM temps_connexion"),
}


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


def _fetch_tables(conn) -> dict[str, list[dict]]:
    import pymysql
    tables = {}
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        for table, query in MEASURE_QUERIES.items():
            cur.execute(query)
            tables[table] = list(cur.fetchall())
    return tables


def check_volumes(tables) -> list[Check]:
    checks = []
    for table, cible in TARGETS.items():
        n = len(tables[table])
        if table in EXACT_TARGETS:
            ok, detail = n == cible, f"{n} lignes (attendu {cible})"
        else:
            ok = abs(n - cible) <= TOLERANCE * cible
            detail = f"{n} lignes (cible ~{cible}, écart {100 * (n - cible) / cible:+.1f} %)"
        checks.append(Check("V1", f"Volume {table}", ok, detail))
    return checks


def check_anomalies(tables, gen, journal_counts, summary):
    mesure = measure_anomalies(tables)
    checks, lignes = [], []
    for code, t in ANOMALY_TYPES.items():
        base = summary["anomalies"][code]["base"]
        n_j, n_b = journal_counts.get(code, 0), mesure[code]
        taux = n_b / base
        ok = n_j == n_b and n_b > 0 and gen.taux_anomalie_min <= taux <= gen.taux_anomalie_max
        lignes.append({"code": code, "table": t.table, "colonne": t.colonne, "description": t.description,
                       "journal": n_j, "base": n_b, "taux": taux, "ok": ok})
        checks.append(Check("V2", f"Anomalie {code}", ok, f"base={n_b}, journal={n_j}, taux={100 * taux:.2f} %"))
    return checks, lignes


def check_constraints(conn) -> list[Check]:
    with conn.cursor() as cur:
        cur.execute("""SELECT CONSTRAINT_NAME, ENFORCED FROM information_schema.TABLE_CONSTRAINTS
                       WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'CHECK'""")
        checks_state = dict(cur.fetchall())
        cur.execute("""SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS
                       WHERE CONSTRAINT_SCHEMA = DATABASE()""")
        fks = {r[0] for r in cur.fetchall()}
    checks = []
    for name, attendu in sorted(EXPECTED_CHECKS.items()):
        etat = checks_state.get(name, "absente")
        checks.append(Check("V3", f"CHECK {name}", etat == attendu,
                            f"ENFORCED={etat} (attendu {attendu})"))
    checks.append(Check("V3", "Clés étrangères déclarées", EXPECTED_FKS <= fks,
                        f"{len(EXPECTED_FKS & fks)}/{len(EXPECTED_FKS)} : {sorted(fks)}"))
    return checks


def check_relations(tables, journal_counts) -> list[Check]:
    ids = {t: {r[k] for r in tables[t]} for t, k in
           (("modules", "id_module"), ("cours", "id_cours"), ("quiz", "id_quiz"))}
    cas = {
        "cours -> modules": (sum(1 for c in tables["cours"] if c["id_module"] not in ids["modules"]), 0),
        "quiz -> cours": (sum(1 for q in tables["quiz"] if q["id_cours"] not in ids["cours"]), 0),
        "notes -> quiz": (sum(1 for n in tables["notes"] if n["id_quiz"] not in ids["quiz"]), 0),
        "progression -> modules": (sum(1 for p in tables["progression"] if p["id_module"] not in ids["modules"]),
                                   journal_counts.get("B07", 0)),
    }
    return [Check("V4", f"Relation {k}", n == att, f"{n} orphelin(s) (attendu {att})") for k, (n, att) in cas.items()]


def check_identifiants(tables, settings) -> list[Check]:
    ref = load_referential()
    lms = {s.student_code for s in ref if s.statut_correspondance in (STATUT_APPARIE, STATUT_LMS_ORPHELIN)}
    orphelins = {s.student_code for s in ref if s.statut_correspondance == STATUT_LMS_ORPHELIN}
    en_base = {r["student_code"] for t in ("notes", "progression", "temps_connexion") for r in tables[t]
               if STUDENT_CODE_RE.match(r["student_code"])}
    checks = [
        Check("V5", "student_code = 9 500 comptes LMS", en_base == lms,
              f"{len(en_base & lms)} communs, {len(en_base - lms)} inconnus, {len(lms - en_base)} absents"),
        Check("V5", "500 comptes LMS orphelins présents", orphelins <= en_base,
              f"{len(orphelins & en_base)}/{len(orphelins)}"),
    ]
    avec_progression = {p["student_code"] for p in tables["progression"]}
    checks.append(Check("V5", "Chaque compte LMS a une progression", lms <= avec_progression,
                        f"{len(lms & avec_progression)}/{len(lms)} comptes avec au moins une progression"))
    with (settings.paths.mappings_dir / MAPPING_ETUDIANTS_FILENAME).open(encoding="utf-8", newline="") as h:
        codes_mapping = {r["student_code"] for r in csv.DictReader(h)}
    checks.append(Check("V5", "mapping_etudiants -> MySQL", codes_mapping <= en_base,
                        f"{len(codes_mapping & en_base)}/{len(codes_mapping)} codes du mapping trouvés"))

    with (settings.paths.mappings_dir / MAPPING_COURSES_FILENAME).open(encoding="utf-8", newline="") as h:
        mapping = list(csv.DictReader(h))
    ids = {"MODULE": {m["id_module"] for m in tables["modules"]},
           "COURSE": {c["id_cours"] for c in tables["cours"]},
           "QUIZ": {q["id_quiz"] for q in tables["quiz"]}}
    inconnus = sum(1 for r in mapping if r["id_mysql"] not in ids[r["type_objet"]])
    checks.append(Check("V5", "mapping_courses -> identifiants MySQL", inconnus == 0,
                        f"{inconnus} identifiant(s) introuvable(s) sur {len(mapping)}"))
    codes = [r["code_externe"] for r in mapping]
    checks.append(Check("V5", "mapping_courses : codes uniques", len(codes) == len(set(codes)),
                        f"{len(codes)} codes, {len(set(codes))} distincts"))
    for type_objet in ("MODULE", "COURSE", "QUIZ"):
        n_map = sum(1 for r in mapping if r["type_objet"] == type_objet)
        total = len(ids[type_objet])
        attendu = total if type_objet == "MODULE" else total - round(TAUX_ABSENTS_MAPPING * total)
        checks.append(Check("V5", f"mapping_courses : {type_objet}", n_map == attendu,
                            f"{n_map}/{total} présents (attendu {attendu})"))
    return checks


def write_report(path, checks, anomalies, volumes) -> None:
    ok = all(c.ok for c in checks)
    lines = [
        "# Porte G1 — Source 2 : MySQL « Plateforme pédagogique »", "",
        f"*Rapport généré le {datetime.now():%Y-%m-%d %H:%M}*", "",
        f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** "
        f"({sum(c.ok for c in checks)}/{len(checks)} contrôles réussis)", "",
        "## Volumes", "", "| Table | Lignes |", "|---|---:|",
        *[f"| {t} | {n:,} |".replace(",", " ") for t, n in volumes.items()], "",
        "## Anomalies (mesurées en base)", "",
        "| Code | Table.colonne | Description | Journal | En base | Taux | OK |", "|---|---|---|---:|---:|---:|:-:|",
        *[f"| {a['code']} | {a['table']}.{a['colonne']} | {a['description']} | {a['journal']} | {a['base']} | "
          f"{100 * a['taux']:.2f} % | {'✅' if a['ok'] else '❌'} |" for a in anomalies], "",
        "## Tous les contrôles", "", "| Groupe | Contrôle | Détail | OK |", "|---|---|---|:-:|",
        *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    import pymysql

    settings = get_settings()
    gen = settings.generation
    try:
        journal_counts: dict[str, int] = {}
        for r in read_journal(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv"):
            journal_counts[r.code] = journal_counts.get(r.code, 0) + 1
        summary = json.loads((settings.paths.generated_dir / SOURCE / "summary.json").read_text(encoding="utf-8"))

        conn = pymysql.connect(**settings.mysql.connect_kwargs())
        try:
            tables = _fetch_tables(conn)
            checks = check_volumes(tables)
            anomaly_checks, anomaly_rows = check_anomalies(tables, gen, journal_counts, summary)
            checks += anomaly_checks + check_constraints(conn)
        finally:
            conn.close()
        checks += check_relations(tables, journal_counts) + check_identifiants(tables, settings)

        for c in checks:
            (logger.info if c.ok else logger.error)("[%s] %s %-40s %s", "OK" if c.ok else "KO",
                                                    c.code, c.libelle, c.detail)
        report = settings.paths.reports_dir / f"{SOURCE}_G1.md"
        write_report(report, checks, anomaly_rows, {t: len(v) for t, v in tables.items()})
        nb_ok = sum(c.ok for c in checks)
        logger.info("Porte G1 Source 2 : %d/%d contrôles réussis - rapport : %s", nb_ok, len(checks), report)
        return 0 if nb_ok == len(checks) else 1
    except FileNotFoundError as exc:
        logger.error("Fichier introuvable : %s (lancez generate_data puis insert_data)", exc.filename)
        return 1
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la vérification G1 de la Source 2")
        return 2


if __name__ == "__main__":
    sys.exit(main())
