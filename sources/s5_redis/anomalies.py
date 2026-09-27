"""
sources/s5_redis/anomalies.py — Anomalies volontaires de la Source 5
===================================================================

Les 7 anomalies du PDF Source 5 (codes E01 à E07), sur un snapshot en mémoire :
    snapshot = {clé: {"type": "hash"|"string"|"zset"|"list", "value": ..., "ttl": secondes | None}}

Les sessions anormales (E01, E02) sont de VRAIES sessions MongoDB (même
session_id) : l'ETL pourra les confronter aux journaux de l'application.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from common.anomaly_journal import AnomalyJournal, AnomalyType
from common.config import GenerationConfig
from sources.s5_redis.create_source import DATE_FMT, INACTIVITE_MAX_MIN, SNAPSHOT, TTL_SESSION

SOURCE = "s5_redis"
PDF = "Source 5 - Redis - Plateforme temps réel.pdf"

ANOMALY_TYPES: dict[str, AnomalyType] = {t.code: t for t in (
    AnomalyType("E01", "session:*", "ttl", "Session expirée mais encore présente (activité de plus de 24 h, sans TTL)", PDF),
    AnomalyType("E02", "session:*", "last_activity", f"Utilisateur connecté sans activité récente (plus de {INACTIVITE_MAX_MIN} min)", PDF),
    AnomalyType("E03", "online_users / statistics:today", "*", "Compteur incohérent avec l'état réel", PDF),
    AnomalyType("E04", "notifications:*", "*", "Notification en double", PDF),
    AnomalyType("E05", "progress:*", "progress", "Progression supérieure à 100 %", PDF),
    AnomalyType("E06", "*", "student_code", "Étudiant absent des autres systèmes", PDF),
    AnomalyType("E07", "session:*", "student_code", "Session sans étudiant associé", PDF),
)}
FIXED_BY_DESIGN = {"E03"}

UN_JOUR = timedelta(days=1)
INACTIVITE = timedelta(minutes=INACTIVITE_MAX_MIN)


def _count_for(rng: random.Random, base: int, gen: GenerationConfig) -> int:
    return rng.randint(math.ceil(gen.taux_anomalie_min * base), math.floor(gen.taux_anomalie_max * base))


def _session_hash(s: dict) -> dict:
    return {"student_code": s["student_code"], "status": "ONLINE", "login_time": s["login"].strftime(DATE_FMT),
            "last_activity": s["last"].strftime(DATE_FMT), "device": s["operating_system"], "ip": s["ip"]}


def student_codes(snapshot: dict) -> set[str]:
    """Tous les student_code présents dans le snapshot (clés, membres du classement, sessions)."""
    codes = set()
    for key, item in snapshot.items():
        for prefix in ("last_course:", "last_quiz:", "progress:", "notifications:"):
            if key.startswith(prefix):
                codes.add(key[len(prefix):])
        if key.startswith("session:") and item["value"].get("student_code"):
            codes.add(item["value"]["student_code"])
        if key.startswith("leaderboard:"):
            codes.update(item["value"])
    return codes


# -----------------------------------------------------------------------------
# Injection
# -----------------------------------------------------------------------------
def inject_anomalies(snapshot: dict, gen: GenerationConfig, rng: random.Random, verite: dict,
                     sessions_inactives: list[dict], sessions_expirees: list[dict],
                     codes_lms: set[str]) -> tuple[AnomalyJournal, dict[str, int]]:
    """
    verite              : compteurs réels (online_users, statistics) ;
    sessions_inactives  : sessions MongoDB du jour, non terminées, inactives depuis plus de 30 min ;
    sessions_expirees   : sessions MongoDB de jours précédents, jamais terminées (sans LOGOUT).
    """
    journal = AnomalyJournal(SOURCE, ANOMALY_TYPES)
    sessions = sorted(k for k in snapshot if k.startswith("session:"))
    n_sessions = len(sessions)
    bases = {"E01": n_sessions, "E02": n_sessions, "E07": n_sessions, "E03": 5}

    # E01 : sessions anciennes restées en mémoire, SANS TTL
    for s in rng.sample(sessions_expirees, _count_for(rng, n_sessions, gen)):
        key = f"session:{s['session_id']}"
        snapshot[key] = {"type": "hash", "value": _session_hash(s), "ttl": None}
        journal.add("E01", key, "expirée (supprimée)", f"présente, dernière activité {s['last']:%Y-%m-%d %H:%M}")

    # E02 : sessions du jour inactives depuis plus de 30 min, toujours ONLINE
    for s in rng.sample(sessions_inactives, _count_for(rng, n_sessions, gen)):
        key = f"session:{s['session_id']}"
        snapshot[key] = {"type": "hash", "value": _session_hash(s), "ttl": TTL_SESSION}
        journal.add("E02", key, "inactive (supprimée)", f"ONLINE, inactive depuis {int((SNAPSHOT - s['last']).total_seconds() // 60)} min")

    # E07 : sessions actives dont le champ student_code a disparu
    for key in rng.sample(sessions, _count_for(rng, n_sessions, gen)):
        journal.add("E07", key, snapshot[key]["value"]["student_code"], "champ absent")
        del snapshot[key]["value"]["student_code"]

    # E03 : deux compteurs faux (le PDF donne online_users = 548 pour active_students = 542)
    online_faux = verite["active_students"] + rng.randint(3, 20)          # plus de connectés que d'actifs du jour
    journal.add("E03", "online_users", verite["online_users"], online_faux)
    snapshot["online_users"]["value"] = str(online_faux)
    videos_faux = verite["videos_streaming"] + rng.randint(40, 90)        # plus de vidéos que de sessions actives
    journal.add("E03", "statistics:today.videos_streaming", verite["videos_streaming"], videos_faux)
    snapshot["statistics:today"]["value"]["videos_streaming"] = str(videos_faux)

    # E05 : progressions > 100 % (avant E06 : uniquement des étudiants réels)
    progress = sorted(k for k in snapshot if k.startswith("progress:"))
    bases["E05"] = len(progress)
    for key in rng.sample(progress, _count_for(rng, len(progress), gen)):
        new = f"{rng.uniform(100.5, 150):.2f}"
        journal.add("E05", key, snapshot[key]["value"]["progress"], new)
        snapshot[key]["value"]["progress"] = new

    # E04 : notification répétée juste après l'originale
    listes = sorted(k for k in snapshot if k.startswith("notifications:"))
    total_messages = sum(len(snapshot[k]["value"]) for k in listes)
    bases["E04"] = total_messages
    positions = [(k, i) for k in listes for i in range(len(snapshot[k]["value"]))]
    for key, i in sorted(rng.sample(positions, _count_for(rng, total_messages, gen)), reverse=True):
        message = snapshot[key]["value"][i]
        snapshot[key]["value"].insert(i + 1, message)
        journal.add("E04", key, message, "message dupliqué")

    # E06 : comptes inconnus de tous les autres systèmes (numéros LMS jamais attribués)
    reels = student_codes(snapshot)
    bases["E06"] = len(reels)
    k6 = _count_for(rng, len(reels), gen)
    numeros = rng.sample(range(len(codes_lms) + 1, 1_000_000), k6)
    modele_last = [k for k in snapshot if k.startswith("last_course:")]
    modele_prog = [k for k in progress if float(snapshot[k]["value"]["progress"]) <= 100]
    for numero in numeros:
        code = f"LMS-{numero:06d}"
        snapshot[f"last_course:{code}"] = dict(snapshot[rng.choice(modele_last)])
        snapshot[f"progress:{code}"] = {"type": "hash", "value": dict(snapshot[rng.choice(modele_prog)]["value"]),
                                        "ttl": snapshot[progress[0]]["ttl"]}
        journal.add("E06", code, None, "last_course + progress")
    return journal, bases


# -----------------------------------------------------------------------------
# Mesure (mêmes règles en mémoire et sur la base Redis relue)
# -----------------------------------------------------------------------------
def measure_anomalies(snapshot: dict, verite: dict, codes_lms: set[str]) -> dict[str, int]:
    sessions = [item["value"] for k, item in snapshot.items() if k.startswith("session:")]

    def age(s):
        return SNAPSHOT - datetime.strptime(s["last_activity"], DATE_FMT)

    stats = snapshot.get("statistics:today", {}).get("value", {})
    compteurs = [("online_users", snapshot.get("online_users", {}).get("value"))] + \
                [(f"statistics:today.{f}", stats.get(f)) for f in ("active_students", "quiz_running", "videos_streaming")]
    return {
        "E01": sum(1 for s in sessions if age(s) > UN_JOUR),
        "E02": sum(1 for s in sessions if INACTIVITE < age(s) <= UN_JOUR),
        "E03": sum(1 for nom, v in compteurs if v is None or int(v) != verite[nom.split(".")[-1]]),
        "E04": sum(len(item["value"]) - len(set(item["value"])) for k, item in snapshot.items()
                   if k.startswith("notifications:")),
        "E05": sum(1 for k, item in snapshot.items() if k.startswith("progress:") and float(item["value"]["progress"]) > 100),
        "E06": len(student_codes(snapshot) - codes_lms),
        "E07": sum(1 for s in sessions if not s.get("student_code")),
    }
