"""
sources/s3_csv/verify_source.py — Porte G1 de la Source 3 (Lot L2-c)
===================================================================

Relit les 4 fichiers EXACTEMENT comme le fera l'ETL (encodage et séparateur
déclarés dans SCHEMAS), puis contrôle :

    V1  Volumes : departements = 12 ; les autres fichiers à ±5 % des cibles.
    V2  Anomalies : 19 types, mesure dans les fichiers = journal ; taux dans
        [2 %, 5 %] (sauf C08 et C09, fixés par conception).
    V3  Format : en-têtes conformes au PDF, nombre de champs constant, fins de
        ligne CRLF, encodage réel (les fichiers ISO-8859-1 ne sont PAS lisibles
        en UTF-8 : l'ETL devra déclarer l'encodage).
    V4  Règles métier : clés teacher_code valides ; « un salaire par mois »
        respecté hors doublons ; salaire_net = base + primes - retenues, sauf
        les anomalies C10 et C11 ; tous les mois et toutes les dates lisibles.
    V5  Inter-sources : les 120 enseignants du vivier commun, mêmes noms ;
        tous les responsables de classe de PostgreSQL existent dans le fichier ;
        les 8 départements canoniques sont présents.

Rapport : data/reports/s3_csv_G1.md — Code de sortie : 0 si G1 est validée.
Exécution : python -m sources.s3_csv.verify_source
"""

from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common.academic_catalog import DEPARTEMENTS, build_teacher_pool
from common.anomaly_journal import read_journal
from common.config import get_settings
from common.logger import get_logger
from sources.s3_csv.anomalies import (ANOMALY_TYPES, FIXED_BY_DESIGN, SOURCE, measure_anomalies,
                                      normalize_mois, parse_date)
from sources.s3_csv.create_source import FILE_ORDER, OUTPUT_DIR, SCHEMAS
from sources.s3_csv.generate_data import COLUMNS, EXACT_TARGETS, TARGETS, TOLERANCE

logger = get_logger("s3_verify")


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


def read_file(key: str, out_dir: Path = OUTPUT_DIR) -> tuple[list[dict], bytes]:
    """Lit un fichier avec l'encodage et le séparateur déclarés. Champ vide -> None."""
    schema = SCHEMAS[key]
    raw = (out_dir / schema.nom).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode(schema.encodage), newline=""), delimiter=schema.separateur)
    rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in reader]
    return rows, raw


def check_volumes(tables) -> list[Check]:
    checks = []
    for key, cible in TARGETS.items():
        n = len(tables[key])
        if key in EXACT_TARGETS:
            ok, detail = n == cible, f"{n} lignes (attendu {cible})"
        else:
            ok = abs(n - cible) <= TOLERANCE * cible
            detail = f"{n} lignes (cible ~{cible}, écart {100 * (n - cible) / cible:+.1f} %)"
        checks.append(Check("V1", f"Volume {SCHEMAS[key].nom}", ok, detail))
    return checks


def check_anomalies(tables, gen, journal_counts, summary):
    mesure = measure_anomalies(tables, COLUMNS, gen)
    checks, lignes = [], []
    for code, t in ANOMALY_TYPES.items():
        base = summary["anomalies"][code]["base"]
        n_j, n_m = journal_counts.get(code, 0), mesure[code]
        taux = n_m / base
        taux_ok = code in FIXED_BY_DESIGN or gen.taux_anomalie_min <= taux <= gen.taux_anomalie_max
        ok = n_j == n_m and n_m > 0 and taux_ok
        lignes.append({"code": code, "table": t.table, "colonne": t.colonne, "description": t.description,
                       "journal": n_j, "mesure": n_m, "taux": taux, "ok": ok})
        checks.append(Check("V2", f"Anomalie {code}", ok, f"fichier={n_m}, journal={n_j}, taux={100 * taux:.2f} %"))
    return checks, lignes


def check_format(raws: dict[str, bytes]) -> list[Check]:
    checks = []
    for key in FILE_ORDER:
        schema, raw = SCHEMAS[key], raws[key]
        texte = raw.decode(schema.encodage)
        lignes = texte.split("\r\n")
        entete = lignes[0].split(schema.separateur)
        checks.append(Check("V3", f"En-tête {schema.nom}", entete == schema.entetes,
                            f"{len(entete)} colonnes conformes au PDF" if entete == schema.entetes else f"{entete}"))
        nb_champs = {len(r) for r in csv.reader(io.StringIO(texte, newline=""), delimiter=schema.separateur)}
        checks.append(Check("V3", f"Séparateur '{schema.separateur}' {schema.nom}", nb_champs == {len(schema.entetes)},
                            f"nombre de champs par ligne : {sorted(nb_champs)}"))
        crlf = raw.count(b"\r\n") == raw.count(b"\n") and raw.endswith(b"\r\n")
        checks.append(Check("V3", f"Fins de ligne CRLF {schema.nom}", crlf, "CRLF (export Windows/Excel)"))
        if schema.encodage == "iso-8859-1":
            try:
                raw.decode("utf-8")
                ok, detail = False, "lisible en UTF-8 : l'encodage ISO-8859-1 n'est pas démontré"
            except UnicodeDecodeError:
                ok, detail = True, "ISO-8859-1 réel (illisible en UTF-8)"
        else:
            ok, detail = True, "UTF-8 valide"
        checks.append(Check("V3", f"Encodage {schema.nom}", ok, detail))
    return checks


def check_regles(tables, journal_counts) -> list[Check]:
    codes = {r["teacher_code"] for r in tables["enseignants"]}
    checks = []
    for key in ("salaires", "absences"):
        orphelins = sum(1 for r in tables[key] if r["teacher_code"] not in codes)
        checks.append(Check("V4", f"{key}.teacher_code -> enseignants", orphelins == 0, f"{orphelins} orphelin(s)"))
    mois = [normalize_mois(r["mois"]) for r in tables["salaires"]]
    checks.append(Check("V4", "Tous les mois sont lisibles", None not in mois,
                        f"{sum(m is None for m in mois)} mois illisible(s)"))
    cle = Counter((r["teacher_code"], r["annee"], m) for r, m in zip(tables["salaires"], mois))
    doublons = sum(n - 1 for n in cle.values() if n > 1)
    checks.append(Check("V4", "Un salaire par mois (hors doublons C12)", doublons == journal_counts.get("C12", 0),
                        f"{doublons} salaire(s) en trop (attendu {journal_counts.get('C12', 0)})"))
    ecarts = sum(1 for r in tables["salaires"]
                 if abs(float(r["salaire_base"]) + float(r["primes"]) - float(r["retenues"]) - float(r["salaire_net"])) > 0.01)
    attendu = journal_counts.get("C10", 0) + journal_counts.get("C11", 0)
    checks.append(Check("V4", "salaire_net = base + primes - retenues", ecarts == attendu,
                        f"{ecarts} écart(s) (attendu {attendu} = C10 + C11)"))
    dates = [r["date_naissance"] for r in tables["enseignants"]] + [r["date_embauche"] for r in tables["enseignants"]] \
        + [r["date_absence"] for r in tables["absences"]]
    illisibles = sum(1 for d in dates if parse_date(d)[0] is None)
    formats = Counter(parse_date(d)[1] for d in dates)
    checks.append(Check("V4", "Dates lisibles (3 formats du PDF)", illisibles == 0 and set(formats) == {"ISO", "FR", "US"},
                        f"{illisibles} illisible(s) ; formats : {dict(formats)}"))
    return checks


def check_inter_sources(tables, gen) -> list[Check]:
    from common.referential import STATUT_LMS_ORPHELIN, load_referential
    from sources.s1_postgresql.generate_data import generate_clean as s1_clean

    pool = build_teacher_pool(seed=gen.seed)
    ens = {r["teacher_code"]: r for r in tables["enseignants"]}
    checks = [Check("V5", "Les 120 enseignants du vivier commun", set(ens) == {t.teacher_code for t in pool},
                    f"{len(set(ens) & {t.teacher_code for t in pool})}/{len(pool)} codes communs")]
    noms_ko = sum(1 for t in pool if (ens[t.teacher_code]["prenom"], ens[t.teacher_code]["nom"]) != (t.prenom, t.nom))
    checks.append(Check("V5", "Noms identiques au vivier", noms_ko == 0, f"{noms_ko} écart(s)"))

    etudiants_pg = [s for s in load_referential() if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    classes = s1_clean(etudiants_pg, gen)["classes"]
    responsables = {c["responsable"] for c in classes}
    noms_complets = {f"{r['prenom']} {r['nom']}" for r in tables["enseignants"]}
    checks.append(Check("V5", "Responsables de classe PostgreSQL -> enseignants.csv", responsables <= noms_complets,
                        f"{len(responsables & noms_complets)}/{len(responsables)} responsables retrouvés (par le nom)"))
    embauche = {f"{r['prenom']} {r['nom']}": parse_date(r["date_embauche"])[0] for r in tables["enseignants"]}
    trop_tard = sum(1 for c in classes if embauche.get(c["responsable"]) and
                    embauche[c["responsable"]] > gen.rentree(c["annee_academique"]))
    checks.append(Check("V5", "Responsables en poste à la rentrée de leur classe", trop_tard == 0,
                        f"{trop_tard} classe(s) dont le responsable est embauché après la rentrée"))
    noms_dep = {r["nom_departement"] for r in tables["departements"]}
    checks.append(Check("V5", "8 départements canoniques présents", set(DEPARTEMENTS) <= noms_dep,
                        f"{len(set(DEPARTEMENTS) & noms_dep)}/8"))
    return checks


def write_report(path, checks, anomalies, volumes) -> None:
    ok = all(c.ok for c in checks)
    lines = [
        "# Porte G1 — Source 3 : CSV Ressources humaines", "",
        f"*Rapport généré le {datetime.now():%Y-%m-%d %H:%M}*", "",
        f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** ({sum(c.ok for c in checks)}/{len(checks)} contrôles réussis)", "",
        "## Volumes", "", "| Fichier | Lignes |", "|---|---:|",
        *[f"| {SCHEMAS[k].nom} | {n:,} |".replace(",", " ") for k, n in volumes.items()], "",
        "## Anomalies (mesurées dans les fichiers)", "",
        "| Code | Fichier.colonne | Description | Journal | Fichier | Taux | OK |", "|---|---|---|---:|---:|---:|:-:|",
        *[f"| {a['code']} | {a['table']}.{a['colonne']} | {a['description']} | {a['journal']} | {a['mesure']} | "
          f"{100 * a['taux']:.2f} % | {'✅' if a['ok'] else '❌'} |" for a in anomalies], "",
        "## Tous les contrôles", "", "| Groupe | Contrôle | Détail | OK |", "|---|---|---|:-:|",
        *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(out_dir: Path = OUTPUT_DIR) -> tuple[list[Check], list[dict], dict[str, int]]:
    settings = get_settings()
    gen = settings.generation
    journal_counts = Counter(r.code for r in read_journal(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv"))
    summary = json.loads((settings.paths.generated_dir / SOURCE / "summary.json").read_text(encoding="utf-8"))
    tables, raws = {}, {}
    for key in FILE_ORDER:
        tables[key], raws[key] = read_file(key, out_dir)
    checks = check_volumes(tables)
    anomaly_checks, anomaly_rows = check_anomalies(tables, gen, journal_counts, summary)
    checks += anomaly_checks + check_format(raws) + check_regles(tables, journal_counts) + check_inter_sources(tables, gen)
    return checks, anomaly_rows, {k: len(v) for k, v in tables.items()}


def main() -> int:
    settings = get_settings()
    try:
        checks, anomaly_rows, volumes = run()
        for c in checks:
            (logger.info if c.ok else logger.error)("[%s] %s %-48s %s", "OK" if c.ok else "KO", c.code, c.libelle, c.detail)
        report = settings.paths.reports_dir / f"{SOURCE}_G1.md"
        write_report(report, checks, anomaly_rows, volumes)
        nb_ok = sum(c.ok for c in checks)
        logger.info("Porte G1 Source 3 : %d/%d contrôles réussis - rapport : %s", nb_ok, len(checks), report)
        return 0 if nb_ok == len(checks) else 1
    except FileNotFoundError as exc:
        logger.error("Fichier introuvable : %s (lancez create_source puis generate_data)", exc.filename)
        return 1
    except UnicodeDecodeError as exc:
        logger.error("Encodage inattendu : %s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la vérification G1 de la Source 3")
        return 2


if __name__ == "__main__":
    sys.exit(main())
