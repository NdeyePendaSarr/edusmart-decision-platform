"""
sources/s5_redis/generate_data.py — Génération de la Source 5 (Lot L2-e)
=======================================================================

Construit l'état de Redis le 15/09/2026 à 23 h 00 (snapshot figé, C24), en le
DÉDUISANT des autres sources (vérité terrain recalculée en mémoire) :

    session:{id}          sessions MongoDB non terminées, actives depuis moins de 30 min
    last_course:{code}    dernier COURSE_OPENED (MongoDB) des 30 derniers jours
    last_quiz:{code}      dernier QUIZ_SUBMITTED (MongoDB) des 30 derniers jours (écart validé)
    progress:{code}       progression MySQL la plus récente des 30 derniers jours
                          (le PDF : Redis la garde « temporairement » avant MySQL)
    leaderboard:python    moyenne des meilleurs scores (sur 100) aux quiz des modules Python (MySQL)
    notifications:{code}  1 à 4 messages en attente pour les étudiants actifs cette semaine
    online_users          nombre d'étudiants connectés
    statistics:today      actifs du jour, enseignants, quiz et vidéos en cours

Sorties
    data/generated/s5_redis/snapshot.json    (clé -> type, valeur, ttl)
    data/generated/s5_redis/summary.json
    data/referential/redis_verite.json       (CACHÉ : compteurs réels, pour G1)
    data/anomalies/s5_redis_anomalies.csv

Exécution : python -m sources.s5_redis.generate_data   (~40 s)
"""

from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from common.config import GenerationConfig, get_settings
from common.logger import get_logger, log_step
from common.referential import MasterStudent, load_referential
from common.seed import get_rng
from sources.s5_redis.anomalies import SOURCE, inject_anomalies, measure_anomalies
from sources.s5_redis.create_source import (DATE_FMT, INACTIVITE_MAX_MIN, SNAPSHOT, TTL_PROGRESS, TTL_SESSION,
                                            TTL_STATISTICS)

logger = get_logger("s5_generate")

SNAPSHOT_FILENAME = "snapshot.json"
VERITE_FILENAME = "redis_verite.json"
FENETRE_RECENTE = timedelta(days=30)
FENETRE_NOTIFICATIONS = timedelta(days=7)
MODULES_LEADERBOARD = ("Python - ", "Python pour la Data - ")   # thèmes Python du catalogue


class GenerationError(Exception):
    """Erreur bloquante pendant la génération de la Source 5."""


def _fmt_pct(value: float) -> str:
    """72.0 -> '72' ; 72.5 -> '72.5' (l'exemple du PDF est '72')."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def etat_plateforme(gen: GenerationConfig, students: list[MasterStudent]) -> dict:
    """Vérité terrain au moment du snapshot, calculée à partir de MongoDB et MySQL propres."""
    from sources.s2_mysql.generate_data import generate_clean as s2_clean
    from sources.s4_mongodb.generate_data import generate_clean as s4_clean

    events, _ = s4_clean(gen, students)
    t2, codes, _ = s2_clean(gen, students)
    avant = [e for e in events if e["timestamp"] <= SNAPSHOT]

    par_session = defaultdict(list)
    for e in avant:
        par_session[e["session_id"]].append(e)
    actives, inactives, expirees = [], [], []
    for sid, docs in par_session.items():
        if any(d["event_type"] == "LOGOUT" for d in docs):
            continue
        docs.sort(key=lambda d: d["timestamp"])
        s = {"session_id": sid, "student_code": docs[0]["student_code"], "login": docs[0]["timestamp"],
             "last": docs[-1]["timestamp"], "operating_system": docs[0]["operating_system"],
             "ip": docs[0]["ip_address"], "docs": docs}
        age = SNAPSHOT - s["last"]
        if s["login"].date() == SNAPSHOT.date():
            (actives if age <= timedelta(minutes=INACTIVITE_MAX_MIN) else inactives).append(s)
        else:
            expirees.append(s)
    return {"events": avant, "t2": t2, "codes": codes, "actives": actives,
            "inactives": inactives, "expirees": expirees}


def _en_cours(docs, debut_type, fin_type) -> bool:
    """Un quiz (ou une vidéo) commencé avant le snapshot et pas encore terminé à 23 h 00."""
    ouverts = 0
    for d in docs:
        if d["event_type"] == debut_type:
            fin = d["timestamp"] + timedelta(seconds=d["duration_seconds"]) if debut_type == "VIDEO_STARTED" else None
            ouverts = 1 if (fin is None or fin > SNAPSHOT) else 0
        elif d["event_type"] == fin_type:
            ouverts = 0
    return bool(ouverts)


def build_snapshot(gen: GenerationConfig, students: list[MasterStudent], rng: random.Random):
    etat = etat_plateforme(gen, students)
    events, t2, codes = etat["events"], etat["t2"], etat["codes"]
    code = {c["id_mysql"]: c["code_externe"] for c in codes}
    snapshot: dict = {}

    # 1. Sessions actives
    for s in etat["actives"]:
        snapshot[f"session:{s['session_id']}"] = {"type": "hash", "ttl": TTL_SESSION, "value": {
            "student_code": s["student_code"], "status": "ONLINE", "login_time": s["login"].strftime(DATE_FMT),
            "last_activity": s["last"].strftime(DATE_FMT), "device": s["operating_system"], "ip": s["ip"]}}

    # 2 et +. Dernier cours et dernier quiz (MongoDB, 30 derniers jours)
    recents = [e for e in events if e["timestamp"] >= SNAPSHOT - FENETRE_RECENTE]
    for type_, prefix, champ in (("COURSE_OPENED", "last_course", "course_code"), ("QUIZ_SUBMITTED", "last_quiz", "quiz_code")):
        dernier = {}
        for e in recents:
            if e["event_type"] == type_:
                dernier[e["student_code"]] = e[champ]               # événements triés : le dernier gagne
        for sc, val in dernier.items():
            snapshot[f"{prefix}:{sc}"] = {"type": "string", "ttl": None, "value": val}

    # 3. Progression récente (MySQL, 30 derniers jours) : la plus récente par étudiant
    plus_recente = {}
    for p in t2["progression"]:
        if SNAPSHOT - FENETRE_RECENTE <= p["date_maj"] <= SNAPSHOT:
            if p["student_code"] not in plus_recente or p["date_maj"] > plus_recente[p["student_code"]]["date_maj"]:
                plus_recente[p["student_code"]] = p
    for sc, p in plus_recente.items():
        valeur = {"module": code[p["id_module"]], "progress": _fmt_pct(p["pourcentage"]),
                  "last_update": p["date_maj"].strftime("%Y-%m-%d %H:%M")}      # format de l'exemple du PDF
        if p["dernier_cours"]:
            valeur["course"] = code[p["dernier_cours"]]
        snapshot[f"progress:{sc}"] = {"type": "hash", "ttl": TTL_PROGRESS, "value": valeur}

    # 4. Classement Python : moyenne des meilleurs scores (/100) aux quiz des modules Python
    modules_py = {m["id_module"] for m in t2["modules"] if m["nom_module"].startswith(MODULES_LEADERBOARD)}
    cours_py = {c["id_cours"] for c in t2["cours"] if c["id_module"] in modules_py}
    quiz_py = {q["id_quiz"]: q["score_max"] for q in t2["quiz"] if q["id_cours"] in cours_py}
    meilleurs = defaultdict(dict)
    for n in t2["notes"]:
        if n["id_quiz"] in quiz_py and n["date_passage"] <= SNAPSHOT:
            pct = 100 * n["score"] / quiz_py[n["id_quiz"]]
            meilleurs[n["student_code"]][n["id_quiz"]] = max(pct, meilleurs[n["student_code"]].get(n["id_quiz"], 0))
    snapshot["leaderboard:python"] = {"type": "zset", "ttl": None, "value": {
        sc: round(sum(v.values()) / len(v), 1) for sc, v in meilleurs.items()}}

    # 5. Notifications en attente (étudiants actifs cette semaine)
    semaine = defaultdict(list)
    for e in events:
        if e["timestamp"] >= SNAPSHOT - FENETRE_NOTIFICATIONS:
            semaine[e["student_code"]].append(e)
    cours_par_module = defaultdict(list)
    for c in t2["cours"]:
        cours_par_module[c["id_module"]].append(c["id_cours"])
    quiz_par_cours = defaultdict(list)
    for q in t2["quiz"]:
        quiz_par_cours[q["id_cours"]].append(q["id_quiz"])
    modules_etudiant = defaultdict(list)
    for p in t2["progression"]:
        modules_etudiant[p["student_code"]].append(p["id_module"])
    for sc in sorted(semaine):
        messages = []
        for e in semaine[sc]:
            if e["event_type"] == "PAYMENT_SUCCESS":
                messages.append(f"Paiement validé : {e['metadata']['reference']}")
            elif e["event_type"] == "COURSE_COMPLETED":
                messages.append(f"Votre certificat est disponible : {e['module_code']}")
        for _ in range(rng.randint(1, 3)):
            id_module = rng.choice(modules_etudiant[sc])
            id_cours = rng.choice(cours_par_module[id_module])
            if quiz_par_cours[id_cours] and rng.random() < 0.5:
                messages.append(f"Quiz disponible : {code[rng.choice(quiz_par_cours[id_cours])]}")
            else:
                messages.append(f"Nouveau cours publié : {code[id_cours]}")
        uniques = list(dict.fromkeys(messages))[-4:]           # sans doublon, 4 au plus
        snapshot[f"notifications:{sc}"] = {"type": "list", "ttl": None, "value": list(reversed(uniques))}  # récent en tête

    # 6 et 7. Compteurs réels
    actives = etat["actives"]
    verite = {
        "sessions_actives": len(actives),
        "online_users": len({s["student_code"] for s in actives}),
        "active_students": len({e["student_code"] for e in events if e["timestamp"].date() == SNAPSHOT.date()}),
        "quiz_running": sum(1 for s in actives if _en_cours(s["docs"], "QUIZ_STARTED", "QUIZ_SUBMITTED")),
        "videos_streaming": sum(1 for s in actives if _en_cours(s["docs"], "VIDEO_STARTED", "VIDEO_FINISHED")),
    }
    snapshot["online_users"] = {"type": "string", "ttl": None, "value": str(verite["online_users"])}
    snapshot["statistics:today"] = {"type": "hash", "ttl": TTL_STATISTICS, "value": {
        "active_students": str(verite["active_students"]),
        # Aucune source ne trace l'activité des enseignants : valeur plausible, NON vérifiable (voir README)
        "active_teachers": str(rng.randint(30, 45)),
        "quiz_running": str(verite["quiz_running"]), "videos_streaming": str(verite["videos_streaming"])}}
    return snapshot, verite, etat


def generate(gen: GenerationConfig | None = None, students: list[MasterStudent] | None = None):
    """Retourne (snapshot, journal, bases, verite)."""
    gen = gen or get_settings().generation
    students = students if students is not None else load_referential()
    rng = get_rng(SOURCE, seed=gen.seed)
    snapshot, verite, etat = build_snapshot(gen, students, rng)
    codes_lms = {s.student_code for s in students if s.student_code}
    journal, bases = inject_anomalies(snapshot, gen, get_rng(f"{SOURCE}_anomalies", seed=gen.seed), verite,
                                      etat["inactives"], etat["expirees"], codes_lms)
    mesure, attendu = measure_anomalies(snapshot, verite, codes_lms), journal.counts()
    if mesure != attendu:
        ecarts = {c: (attendu[c], mesure[c]) for c in attendu if attendu[c] != mesure[c]}
        raise GenerationError(f"Journal et données divergent (journal, mesure) : {ecarts}")
    return snapshot, journal, bases, verite


def _atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(data, h, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise GenerationError(f"Écriture impossible de {path} : {exc}") from exc


def summarize(snapshot: dict) -> dict:
    familles = defaultdict(int)
    for k in snapshot:
        familles[k.split(":")[0] if ":" in k and not k.startswith(("leaderboard", "statistics")) else k] += 1
    return dict(sorted(familles.items()))


def main() -> int:
    settings = get_settings()
    gen = settings.generation
    out_dir = settings.paths.generated_dir / SOURCE
    try:
        settings.paths.ensure_directories()
        with log_step(logger, "Génération Source 5 (Redis, snapshot du 15/09/2026 23:00)"):
            snapshot, journal, bases, verite = generate(gen)
        _atomic_json(out_dir / SNAPSHOT_FILENAME, snapshot)
        _atomic_json(settings.paths.referential_dir / VERITE_FILENAME, verite)
        journal.write_csv(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv")
        summary = {"source": SOURCE, "seed": gen.seed, "snapshot": SNAPSHOT.strftime(DATE_FMT),
                   "cles": len(snapshot), "par_structure": summarize(snapshot),
                   "anomalies": {c: {"nombre": n, "base": bases[c], "taux": round(n / bases[c], 4)}
                                 for c, n in journal.counts().items()}}
        _atomic_json(out_dir / "summary.json", summary)
        logger.info("%d clés : %s", len(snapshot), summary["par_structure"])
        logger.info("Compteurs réels : %s", verite)
        for c, info in summary["anomalies"].items():
            logger.info("%s : %4d / %5d = %5.2f %%", c, info["nombre"], info["base"], 100 * info["taux"])
        return 0
    except (GenerationError, OSError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la génération de la Source 5")
        return 2


if __name__ == "__main__":
    sys.exit(main())
