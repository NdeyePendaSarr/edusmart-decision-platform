"""
sources/s4_mongodb/verify_source.py — Porte G1 de la Source 4 (Lot L2-d)
=======================================================================

Relit TOUTE la collection events et contrôle :

    V1  Volume : ~300 000 (±5 %), dans l'intervalle du PDF (200 000 à 500 000).
    V2  Anomalies : 11 types, mesure en base = journal, taux dans [2 %, 5 %].
    V3  Structure :
        - validateur en place (moderate / error) et index présents ;
        - MongoDB et Python rejettent EXACTEMENT les mêmes documents
          (contrôle du validateur lui-même) ;
        - les 14 types d'événements sont présents ;
        - schéma flexible du PDF : LOGIN sans quiz_code, QUIZ_SUBMITTED avec
          score et attempt, VIDEO_STARTED avec video_quality et buffer_time.
    V4  Règles métier : chaque événement a une session ; une session = un seul
        étudiant ; chaque session a un LOGIN ; aucun événement après le
        15/09/2026 (C20).
    V5  Inter-sources : exactement les 9 500 comptes LMS ; codes de contenus
        connus du référentiel (dont certains absents de mapping_courses : 5 %) ;
        références de paiement issues de PostgreSQL ; sessions identiques au
        fichier caché ; 700 sessions ouvertes le 15/09/2026 pour Redis.

Rapport : data/reports/s4_mongodb_G1.md — Code de sortie : 0 si G1 est validée.
Exécution : python -m sources.s4_mongodb.verify_source   (~30 s)
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time

from common.anomaly_journal import read_journal
from common.config import ConfigError, get_settings
from common.logger import get_logger
from common.referential import (MAPPING_COURSES_FILENAME, STATUT_APPARIE, STATUT_LMS_ORPHELIN,
                                load_referential)
from sources.s4_mongodb.anomalies import ANOMALY_TYPES, SOURCE, STUDENT_CODE_RE, measure_anomalies
from sources.s4_mongodb.create_source import COLLECTION, EVENT_TYPES, INDEXES, VALIDATOR, violates_schema
from sources.s4_mongodb.generate_data import PDF_MAX, PDF_MIN, SESSIONS_FILENAME, TARGET, TOLERANCE

logger = get_logger("s4_verify")


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


def check_volume(events) -> list[Check]:
    n = len(events)
    return [Check("V1", "Volume events", abs(n - TARGET) <= TOLERANCE * TARGET and PDF_MIN <= n <= PDF_MAX,
                  f"{n} documents (cible ~{TARGET}, écart {100 * (n - TARGET) / TARGET:+.1f} % ; PDF : {PDF_MIN}-{PDF_MAX})")]


def check_anomalies(events, gen, journal_counts, summary):
    mesure = measure_anomalies(events)
    checks, lignes = [], []
    for code, t in ANOMALY_TYPES.items():
        base = summary["anomalies"][code]["base"]
        n_j, n_m = journal_counts.get(code, 0), mesure[code]
        taux = n_m / base
        ok = n_j == n_m and n_m > 0 and gen.taux_anomalie_min <= taux <= gen.taux_anomalie_max
        lignes.append({"code": code, "colonne": t.colonne, "description": t.description, "journal": n_j,
                       "mesure": n_m, "taux": taux, "ok": ok})
        checks.append(Check("V2", f"Anomalie {code}", ok, f"base={n_m}, journal={n_j}, taux={100 * taux:.2f} %"))
    return checks, lignes


def check_structure_mongo(db) -> list[Check]:
    """Contrôles qui exigent un VRAI serveur MongoDB (validateur, index, $jsonSchema)."""
    infos = next(iter(db.list_collections(filter={"name": COLLECTION})), {})
    options = infos.get("options", {})
    ok_val = (options.get("validator") == VALIDATOR and options.get("validationLevel") == "moderate"
              and options.get("validationAction") == "error")
    checks = [Check("V3", "Validateur $jsonSchema (moderate / error)", ok_val,
                    f"level={options.get('validationLevel')}, action={options.get('validationAction')}")]
    noms = set(db[COLLECTION].index_information())
    attendus = {name for name, _ in INDEXES}
    checks.append(Check("V3", "Index", attendus <= noms, f"{len(attendus & noms)}/{len(attendus)} présents"))
    return checks


def check_structure(events, db=None) -> list[Check]:
    checks = check_structure_mongo(db) if db is not None else []
    n_python = sum(1 for d in events if violates_schema(d))
    if db is not None:
        n_mongo = db[COLLECTION].count_documents({"$nor": [VALIDATOR]})
        checks.append(Check("V3", "Validateur : MongoDB = Python", n_mongo == n_python,
                            f"{n_mongo} documents invalides selon MongoDB, {n_python} selon Python"))
    types = Counter(d.get("event_type") for d in events)
    checks.append(Check("V3", "14 types d'événements", set(EVENT_TYPES) <= set(types), f"{len(set(EVENT_TYPES) & set(types))}/14"))
    login_quiz = sum(1 for d in events if d.get("event_type") == "LOGIN" and "quiz_code" in d)
    checks.append(Check("V3", "Schéma flexible : LOGIN sans quiz_code", login_quiz == 0, f"{login_quiz} LOGIN avec quiz_code"))
    for type_, champs in (("QUIZ_SUBMITTED", ("score", "attempt")), ("VIDEO_STARTED", ("video_quality", "buffer_time"))):
        docs = [d for d in events if d.get("event_type") == type_ and isinstance(d.get("metadata"), dict)]
        ko = sum(1 for d in docs if not all(c in d["metadata"] for c in champs))
        checks.append(Check("V3", f"Schéma flexible : {type_} -> {', '.join(champs)}", ko == 0 and bool(docs),
                            f"{len(docs) - ko}/{len(docs)} documents conformes"))
    return checks


def check_regles(events, gen) -> list[Check]:
    sans_session = sum(1 for d in events if not d.get("session_id"))
    etudiants, types = defaultdict(set), defaultdict(set)
    for d in events:
        code = d.get("student_code")
        if code and STUDENT_CODE_RE.match(code):
            etudiants[d["session_id"]].add(code)
        types[d["session_id"]].add(d.get("event_type"))
    multi = sum(1 for v in etudiants.values() if len(v) > 1)
    sans_login = sum(1 for v in types.values() if "LOGIN" not in v)
    limite = datetime.combine(gen.date_reference, time(23, 59, 59))
    dates = [d["timestamp"] for d in events if isinstance(d.get("timestamp"), datetime)]
    return [
        Check("V4", "Chaque événement a une session", sans_session == 0, f"{sans_session} sans session_id"),
        Check("V4", "Une session = un seul étudiant", multi == 0, f"{multi} session(s) partagée(s)"),
        Check("V4", "Chaque session a un LOGIN", sans_login == 0, f"{sans_login} session(s) sans LOGIN"),
        Check("V4", "Aucun événement après le 15/09/2026 (C20)", max(dates) <= limite and min(dates) >= datetime(2023, 9, 30),
              f"du {min(dates):%Y-%m-%d %H:%M} au {max(dates):%Y-%m-%d %H:%M}"),
    ]


def check_inter_sources(events, gen, settings) -> list[Check]:
    ref = load_referential()
    lms = {s.student_code for s in ref if s.student_code}
    codes = {d["student_code"] for d in events if isinstance(d.get("student_code"), str)}
    checks = [Check("V5", "student_code = 9 500 comptes LMS", codes == lms,
                    f"{len(codes & lms)} communs, {len(codes - lms)} inconnus, {len(lms - codes)} absents")]

    with (settings.paths.referential_dir / "referentiel_contenus.csv").open(encoding="utf-8", newline="") as h:
        contenus = {r["code_externe"] for r in csv.DictReader(h)}
    with (settings.paths.mappings_dir / MAPPING_COURSES_FILENAME).open(encoding="utf-8", newline="") as h:
        mapping = {r["code_externe"] for r in csv.DictReader(h)}
    utilises = {d[c] for d in events for c in ("module_code", "course_code", "quiz_code") if c in d}
    checks.append(Check("V5", "Codes de contenus connus", utilises <= contenus,
                        f"{len(utilises)} codes utilisés, {len(utilises - contenus)} inconnus"))
    hors_mapping = utilises - mapping
    checks.append(Check("V5", "Codes absents de mapping_courses (5 %, voulu)", len(hors_mapping) > 0,
                        f"{len(hors_mapping)} codes utilisés dans MongoDB mais non résolubles via le mapping"))

    from sources.s1_postgresql.generate_data import generate_clean as s1_clean
    pg = [s for s in ref if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    refs_pg = {p["reference"] for p in s1_clean(pg, gen)["paiements"]}
    refs_mongo = {d["metadata"]["reference"] for d in events if str(d.get("event_type")).startswith("PAYMENT")
                  and isinstance(d.get("metadata"), dict)}
    checks.append(Check("V5", "Références de paiement issues de PostgreSQL", bool(refs_mongo) and refs_mongo <= refs_pg,
                        f"{len(refs_mongo & refs_pg)}/{len(refs_mongo)} références retrouvées"))
    apparies = {s.student_code for s in ref if s.statut_correspondance == STATUT_APPARIE}
    payeurs = {d["student_code"] for d in events if str(d.get("event_type")).startswith("PAYMENT")
               and isinstance(d.get("student_code"), str)}
    checks.append(Check("V5", "Paiements : uniquement des étudiants PostgreSQL", payeurs <= apparies,
                        f"{len(payeurs - apparies)} payeur(s) sans inscription PostgreSQL"))

    with (settings.paths.referential_dir / SESSIONS_FILENAME).open(encoding="utf-8", newline="") as h:
        sessions = list(csv.DictReader(h))
    ids_mongo = {d["session_id"] for d in events if d.get("session_id")}
    checks.append(Check("V5", "Sessions = fichier caché (Redis)", ids_mongo == {s["session_id"] for s in sessions},
                        f"{len(ids_mongo)} sessions en base, {len(sessions)} dans le fichier"))
    ouvertes = {s["session_id"] for s in sessions if s["statut"] == "OUVERTE"}
    logout_ouvertes = sum(1 for d in events if d.get("session_id") in ouvertes and d.get("event_type") == "LOGOUT")
    checks.append(Check("V5", "700 sessions ouvertes le 15/09/2026 (sans LOGOUT)", len(ouvertes) == 700 and logout_ouvertes == 0,
                        f"{len(ouvertes)} sessions ouvertes, {logout_ouvertes} LOGOUT parmi elles"))
    return checks


def write_report(path, checks, anomalies, volume) -> None:
    ok = all(c.ok for c in checks)
    lines = [
        "# Porte G1 — Source 4 : MongoDB « Journaux de l'application mobile »", "",
        f"*Rapport généré le {datetime.now():%Y-%m-%d %H:%M}*", "",
        f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** ({sum(c.ok for c in checks)}/{len(checks)} contrôles réussis)", "",
        f"Volume : **{volume:,} documents**".replace(",", " "), "",
        "## Anomalies (mesurées en base)", "",
        "| Code | Champ | Description | Journal | En base | Taux | OK |", "|---|---|---|---:|---:|---:|:-:|",
        *[f"| {a['code']} | {a['colonne']} | {a['description']} | {a['journal']} | {a['mesure']} | "
          f"{100 * a['taux']:.2f} % | {'✅' if a['ok'] else '❌'} |" for a in anomalies], "",
        "## Tous les contrôles", "", "| Groupe | Contrôle | Détail | OK |", "|---|---|---|:-:|",
        *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(events: list[dict], db=None):
    """Exécute tous les contrôles sur `events` ; `db` (vrai MongoDB) active les contrôles du validateur."""
    settings = get_settings()
    gen = settings.generation
    journal_counts = Counter(r.code for r in read_journal(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv"))
    summary = json.loads((settings.paths.generated_dir / SOURCE / "summary.json").read_text(encoding="utf-8"))
    checks = check_volume(events)
    anomaly_checks, anomaly_rows = check_anomalies(events, gen, journal_counts, summary)
    checks += anomaly_checks + check_structure(events, db) + check_regles(events, gen)
    checks += check_inter_sources(events, gen, settings)
    return checks, anomaly_rows


def main() -> int:
    settings = get_settings()
    try:
        from pymongo import MongoClient
        cfg = settings.mongo
        client = MongoClient(cfg.uri(), serverSelectionTimeoutMS=5000)
        try:
            db = client[cfg.database]
            events = list(db[COLLECTION].find({}, {"_id": 0}))
            checks, anomaly_rows = run(events, db)
        finally:
            client.close()
        for c in checks:
            (logger.info if c.ok else logger.error)("[%s] %s %-48s %s", "OK" if c.ok else "KO", c.code, c.libelle, c.detail)
        report = settings.paths.reports_dir / f"{SOURCE}_G1.md"
        write_report(report, checks, anomaly_rows, len(events))
        nb_ok = sum(c.ok for c in checks)
        logger.info("Porte G1 Source 4 : %d/%d contrôles réussis - rapport : %s", nb_ok, len(checks), report)
        return 0 if nb_ok == len(checks) else 1
    except FileNotFoundError as exc:
        logger.error("Fichier introuvable : %s (lancez generate_data puis insert_data)", exc.filename)
        return 1
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la vérification G1 de la Source 4")
        return 2


if __name__ == "__main__":
    sys.exit(main())
