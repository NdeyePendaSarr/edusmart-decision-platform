"""
sources/s5_redis/verify_source.py — Porte G1 de la Source 5 (Lot L2-e)
=====================================================================

Relit TOUT Redis (SCAN, type, valeur, TTL) et contrôle :

    V1  Volumes : nombre de clés = snapshot ; les 8 familles de clés présentes ;
        sessions actives = état réel calculé (241).
    V2  Anomalies : 7 types, mesure dans Redis = journal ; taux dans [2 %, 5 %]
        (sauf E03 : 2 compteurs faux, fixé par conception).
    V3  Structure : type Redis de chaque famille conforme au PDF ; champs des
        hash (sessions, progress, statistics) ; TTL (sessions 24 h, sauf E01
        SANS TTL ; progress 7 jours ; statistics jusqu'à minuit).
    V4  Règles métier : sessions ONLINE, login_time <= last_activity <= snapshot ;
        scores du classement entre 0 et 100 ; 4 notifications au plus (hors doublons).
    V5  Inter-sources : sessions = vraies sessions MongoDB du même étudiant ;
        codes étudiants connus (sauf E06) ; codes de contenus connus.

Rapport : data/reports/s5_redis_G1.md — Code de sortie : 0 si G1 est validée.
Exécution : python -m sources.s5_redis.verify_source
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from common.anomaly_journal import read_journal
from common.config import ConfigError, get_settings
from common.logger import get_logger
from common.referential import load_referential
from sources.s5_redis.anomalies import ANOMALY_TYPES, FIXED_BY_DESIGN, SOURCE, measure_anomalies, student_codes
from sources.s5_redis.create_source import (DATE_FMT, PROGRESS_FIELDS, SESSION_FIELDS, SNAPSHOT, STATISTICS_FIELDS,
                                            TTL_PROGRESS, TTL_SESSION, TTL_STATISTICS)
from sources.s5_redis.generate_data import SNAPSHOT_FILENAME, VERITE_FILENAME

logger = get_logger("s5_verify")

TYPES_ATTENDUS = {"session": "hash", "last_course": "string", "last_quiz": "string", "progress": "hash",
                  "leaderboard:python": "zset", "notifications": "list", "online_users": "string",
                  "statistics:today": "hash"}


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


def famille(key: str) -> str:
    return key if key in ("leaderboard:python", "statistics:today", "online_users") else key.split(":")[0]


def read_redis(client) -> dict:
    """Relit toutes les clés : {clé: {"type", "value", "ttl"}} (ttl None = pas de durée de vie)."""
    snapshot = {}
    for key in client.scan_iter(count=1000):
        t = client.type(key)
        if t == "hash":
            v = client.hgetall(key)
        elif t == "string":
            v = client.get(key)
        elif t == "zset":
            v = dict(client.zrange(key, 0, -1, withscores=True))
        elif t == "list":
            v = client.lrange(key, 0, -1)
        else:
            v = None
        ttl = client.ttl(key)
        snapshot[key] = {"type": t, "value": v, "ttl": ttl if ttl > 0 else None}
    return snapshot


def check_volumes(snapshot, attendu: int, verite: dict, journal_counts) -> list[Check]:
    familles = Counter(famille(k) for k in snapshot)
    checks = [Check("V1", "Nombre de clés", len(snapshot) == attendu, f"{len(snapshot)} clés (snapshot : {attendu})")]
    for f in TYPES_ATTENDUS:
        checks.append(Check("V1", f"Famille {f}", familles.get(f, 0) > 0, f"{familles.get(f, 0)} clé(s)"))
    n_sessions = familles.get("session", 0) - journal_counts.get("E01", 0) - journal_counts.get("E02", 0)
    checks.append(Check("V1", "Sessions actives = état réel", n_sessions == verite["sessions_actives"],
                        f"{n_sessions} sessions actives (réel : {verite['sessions_actives']})"))
    return checks


def check_anomalies(snapshot, gen, journal_counts, summary, verite, codes_lms):
    mesure = measure_anomalies(snapshot, verite, codes_lms)
    checks, lignes = [], []
    for code, t in ANOMALY_TYPES.items():
        base = summary["anomalies"][code]["base"]
        n_j, n_m = journal_counts.get(code, 0), mesure[code]
        taux = n_m / base
        taux_ok = code in FIXED_BY_DESIGN or gen.taux_anomalie_min <= taux <= gen.taux_anomalie_max
        ok = n_j == n_m and n_m > 0 and taux_ok
        lignes.append({"code": code, "table": t.table, "description": t.description, "journal": n_j, "mesure": n_m,
                       "taux": taux, "ok": ok})
        checks.append(Check("V2", f"Anomalie {code}", ok, f"Redis={n_m}, journal={n_j}, taux={100 * taux:.2f} %"))
    return checks, lignes


def check_structure(snapshot, journal_counts) -> list[Check]:
    mauvais_types = sorted({famille(k) for k, it in snapshot.items() if it["type"] != TYPES_ATTENDUS.get(famille(k))})
    checks = [Check("V3", "Types Redis conformes au PDF", not mauvais_types, f"familles non conformes : {mauvais_types}")]
    sessions = {k: it for k, it in snapshot.items() if famille(k) == "session"}
    champs_ko = sum(1 for it in sessions.values() if set(it["value"]) not in (set(SESSION_FIELDS),
                                                                              set(SESSION_FIELDS) - {"student_code"}))
    checks.append(Check("V3", "Champs des sessions (PDF)", champs_ko == 0, f"{champs_ko} session(s) non conforme(s)"))
    progress = [it for k, it in snapshot.items() if famille(k) == "progress"]
    prog_ko = sum(1 for it in progress if not {"module", "progress", "last_update"} <= set(it["value"]) <= set(PROGRESS_FIELDS))
    checks.append(Check("V3", "Champs de progress (PDF)", prog_ko == 0, f"{prog_ko} non conforme(s)"))
    stats = snapshot.get("statistics:today", {}).get("value", {})
    checks.append(Check("V3", "Champs de statistics:today (PDF)", set(stats) == set(STATISTICS_FIELDS), f"{sorted(stats)}"))
    sans_ttl = sum(1 for it in sessions.values() if it["ttl"] is None)
    ttl_ko = sum(1 for it in sessions.values() if it["ttl"] is not None and not 0 < it["ttl"] <= TTL_SESSION)
    checks.append(Check("V3", "Sessions sans TTL = E01", sans_ttl == journal_counts.get("E01", 0) and ttl_ko == 0,
                        f"{sans_ttl} session(s) sans TTL (E01 : {journal_counts.get('E01', 0)}), {ttl_ko} TTL hors bornes"))
    prog_ttl = sum(1 for it in progress if it["ttl"] is None or not 0 < it["ttl"] <= TTL_PROGRESS)
    stat_ttl = snapshot.get("statistics:today", {}).get("ttl")
    checks.append(Check("V3", "TTL progress (7 j) et statistics (minuit)",
                        prog_ttl == 0 and stat_ttl is not None and 0 < stat_ttl <= TTL_STATISTICS,
                        f"{prog_ttl} progress hors bornes ; statistics : {stat_ttl} s"))
    return checks


def check_regles(snapshot, journal_counts) -> list[Check]:
    sessions = [it["value"] for k, it in snapshot.items() if famille(k) == "session"]
    statut_ko = sum(1 for s in sessions if s.get("status") != "ONLINE")
    dates_ko = sum(1 for s in sessions if not (datetime.strptime(s["login_time"], DATE_FMT)
                                               <= datetime.strptime(s["last_activity"], DATE_FMT) <= SNAPSHOT))
    scores = snapshot["leaderboard:python"]["value"].values()
    trop = sum(1 for k, it in snapshot.items() if famille(k) == "notifications" and len(set(it["value"])) > 4)
    return [
        Check("V4", "Sessions ONLINE", statut_ko == 0, f"{statut_ko} session(s) avec un autre statut"),
        Check("V4", "login_time <= last_activity <= snapshot", dates_ko == 0, f"{dates_ko} incohérence(s)"),
        Check("V4", "Scores du classement entre 0 et 100", all(0 <= s <= 100 for s in scores),
              f"{len(scores)} membres, de {min(scores)} à {max(scores)}"),
        Check("V4", "4 notifications au plus (hors doublons E04)", trop == 0, f"{trop} liste(s) trop longue(s)"),
    ]


def check_inter_sources(snapshot, settings, codes_lms, journal_counts) -> list[Check]:
    with (settings.paths.referential_dir / "sessions_mobile.csv").open(encoding="utf-8", newline="") as h:
        mongo = {r["session_id"]: r["student_code"] for r in csv.DictReader(h)}
    sessions = {k.split(":", 1)[1]: it["value"] for k, it in snapshot.items() if famille(k) == "session"}
    inconnues = sum(1 for sid in sessions if sid not in mongo)
    autre_etudiant = sum(1 for sid, v in sessions.items() if v.get("student_code") and mongo.get(sid) != v["student_code"])
    codes = student_codes(snapshot)
    with (settings.paths.referential_dir / "referentiel_contenus.csv").open(encoding="utf-8", newline="") as h:
        contenus = {r["code_externe"] for r in csv.DictReader(h)}
    utilises = {it["value"] for k, it in snapshot.items() if famille(k) in ("last_course", "last_quiz")}
    utilises |= {it["value"][c] for k, it in snapshot.items() if famille(k) == "progress" for c in ("module", "course")
                 if c in it["value"]}
    return [
        Check("V5", "Sessions = sessions MongoDB", inconnues == 0, f"{len(sessions) - inconnues}/{len(sessions)} retrouvées"),
        Check("V5", "Même étudiant que dans MongoDB", autre_etudiant == 0, f"{autre_etudiant} écart(s)"),
        Check("V5", "Codes étudiants inconnus = E06", len(codes - codes_lms) == journal_counts.get("E06", 0),
              f"{len(codes & codes_lms)} comptes LMS, {len(codes - codes_lms)} inconnus"),
        Check("V5", "Codes de contenus connus", utilises <= contenus,
              f"{len(utilises)} codes utilisés, {len(utilises - contenus)} inconnus"),
    ]


def write_report(path, checks, anomalies, n_cles) -> None:
    ok = all(c.ok for c in checks)
    lines = [
        "# Porte G1 — Source 5 : Redis « Plateforme temps réel »", "",
        f"*Rapport généré le {datetime.now():%Y-%m-%d %H:%M} — snapshot du {SNAPSHOT:%d/%m/%Y %H:%M}*", "",
        f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** ({sum(c.ok for c in checks)}/{len(checks)} contrôles réussis)", "",
        f"Clés : **{n_cles}**", "", "## Anomalies (mesurées dans Redis)", "",
        "| Code | Clés | Description | Journal | Redis | Taux | OK |", "|---|---|---|---:|---:|---:|:-:|",
        *[f"| {a['code']} | `{a['table']}` | {a['description']} | {a['journal']} | {a['mesure']} | "
          f"{100 * a['taux']:.2f} % | {'✅' if a['ok'] else '❌'} |" for a in anomalies], "",
        "## Tous les contrôles", "", "| Groupe | Contrôle | Détail | OK |", "|---|---|---|:-:|",
        *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(snapshot: dict):
    settings = get_settings()
    gen = settings.generation
    journal_counts = Counter(r.code for r in read_journal(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv"))
    summary = json.loads((settings.paths.generated_dir / SOURCE / "summary.json").read_text(encoding="utf-8"))
    verite = json.loads((settings.paths.referential_dir / VERITE_FILENAME).read_text(encoding="utf-8"))
    attendu = len(json.loads((settings.paths.generated_dir / SOURCE / SNAPSHOT_FILENAME).read_text(encoding="utf-8")))
    codes_lms = {s.student_code for s in load_referential() if s.student_code}
    checks = check_volumes(snapshot, attendu, verite, journal_counts)
    anomaly_checks, rows = check_anomalies(snapshot, gen, journal_counts, summary, verite, codes_lms)
    checks += anomaly_checks + check_structure(snapshot, journal_counts) + check_regles(snapshot, journal_counts)
    checks += check_inter_sources(snapshot, settings, codes_lms, journal_counts)
    return checks, rows


def main() -> int:
    settings = get_settings()
    try:
        import redis
        client = redis.Redis(**settings.redis.connect_kwargs())
        try:
            snapshot = read_redis(client)
        finally:
            client.close()
        checks, rows = run(snapshot)
        for c in checks:
            (logger.info if c.ok else logger.error)("[%s] %s %-44s %s", "OK" if c.ok else "KO", c.code, c.libelle, c.detail)
        report = settings.paths.reports_dir / f"{SOURCE}_G1.md"
        write_report(report, checks, rows, len(snapshot))
        nb_ok = sum(c.ok for c in checks)
        logger.info("Porte G1 Source 5 : %d/%d contrôles réussis - rapport : %s", nb_ok, len(checks), report)
        return 0 if nb_ok == len(checks) else 1
    except FileNotFoundError as exc:
        logger.error("Fichier introuvable : %s (lancez generate_data puis insert_data)", exc.filename)
        return 1
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la vérification G1 de la Source 5")
        return 2


if __name__ == "__main__":
    sys.exit(main())
