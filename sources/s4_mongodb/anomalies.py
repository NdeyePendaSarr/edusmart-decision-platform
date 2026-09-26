"""
sources/s4_mongodb/anomalies.py — Anomalies volontaires de la Source 4
=====================================================================

Les 11 anomalies listées par le PDF Source 4, codes D01 à D11.

Chaque document reçoit AU PLUS une anomalie (ensembles disjoints) : la mesure
est donc exacte et chaque anomalie est comptée une fois. Les doublons (D09)
sont créés en dernier, à partir de documents sans autre anomalie.

Distinction importante avec le schéma flexible
    Un LOGIN sans quiz_code est NORMAL (schéma flexible du PDF). Une anomalie
    « champ absent » porte uniquement sur les champs STANDARD, présents dans
    tous les documents propres (voir create_source.STANDARD_FIELDS).
"""

from __future__ import annotations

import ipaddress
import math
import random
import re
import unicodedata
from datetime import datetime

from common import senegalese_data as sn
from common.anomaly_journal import AnomalyJournal, AnomalyType
from common.config import GenerationConfig
from sources.s4_mongodb.create_source import OPERATING_SYSTEMS, STANDARD_FIELDS

SOURCE = "s4_mongodb"
PDF = "Source 4 - MongoDB - Journaux de l'application mobile.pdf"

ANOMALY_TYPES: dict[str, AnomalyType] = {t.code: t for t in (
    AnomalyType("D01", "events", "*", "Document incomplet (tronqué : seuls les identifiants restent)", PDF),
    AnomalyType("D02", "events", "*", "Champ standard absent (device, app_version, ip_address, city, country ou duration_seconds)", PDF),
    AnomalyType("D03", "events", "*", "Valeur nulle (device, city, ip_address, app_version ou duration_seconds)", PDF),
    AnomalyType("D04", "events", "city", "Ville écrite différemment (Dakar, DAKAR, dakarr)", PDF),
    AnomalyType("D05", "events", "app_version", "Version d'application incohérente (2.4, 2.4.0, v2.4)", PDF),
    AnomalyType("D06", "events", "operating_system", "Système d'exploitation écrit différemment (Android, ANDROID, android)", PDF),
    AnomalyType("D07", "events", "student_code", "Événement sans student_code (absent ou nul)", PDF),
    AnomalyType("D08", "events", "timestamp", "Date dans un autre format (texte ou nombre au lieu d'une date)", PDF),
    AnomalyType("D09", "events", "*", "Événement dupliqué (même event_id)", PDF),
    AnomalyType("D10", "events", "ip_address", "Adresse IP invalide", PDF),
    AnomalyType("D11", "events", "duration_seconds", "Durée négative", PDF),
)}

CHAMPS_HORS_CODE = tuple(f for f in STANDARD_FIELDS if f != "student_code")
CHAMPS_CONSERVES_D01 = ("event_id", "student_code", "event_type", "timestamp", "session_id",
                        "module_code", "course_code", "quiz_code")
CHAMPS_ABSENTS_D02 = ("device", "app_version", "ip_address", "city", "country", "duration_seconds")
CHAMPS_NULS_D03 = ("device", "city", "ip_address", "app_version", "duration_seconds")

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
STUDENT_CODE_RE = re.compile(r"^LMS-\d{6}$")
VILLES = frozenset(sn.CITY_TO_REGION)
VARIANTES_OS = {"Android": ("ANDROID", "android", "Android OS"), "iOS": ("IOS", "ios", "iPhone OS")}


def _strip_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def variante_ville(ville: str, rng: random.Random) -> str:
    candidats = {ville.upper(), ville.lower(), ville + ville[-1], (ville + ville[-1]).lower(),
                 _strip_accents(ville).lower(), f"{ville} "}
    return rng.choice(sorted(c for c in candidats if c not in VILLES))


def variante_version(version: str, rng: random.Random) -> str:
    major, minor, patch = version.split(".")
    candidats = {f"v{version}", f"{version}.0", f"V{version}"}
    if patch == "0":
        candidats |= {f"{major}.{minor}", f"v{major}.{minor}"}   # 2.4 / v2.4 (exemples du PDF)
    return rng.choice(sorted(candidats))


def variante_timestamp(ts: datetime, rng: random.Random):
    return rng.choice((
        ts.strftime("%Y-%m-%dT%H:%M:%S"),        # texte ISO (comme l'exemple JSON du PDF)
        ts.strftime("%d/%m/%Y %H:%M:%S"),
        ts.strftime("%Y-%m-%d %H:%M:%S"),
        int(ts.timestamp() * 1000),               # epoch en millisecondes (nombre)
    ))


def _invalid_ip(rng: random.Random) -> str:
    a, b, c = rng.randint(1, 255), rng.randint(0, 255), rng.randint(0, 255)
    return rng.choice((f"{rng.randint(256, 999)}.{a}.{b}.{c}", f"{a}.{b}.{c}",
                       f"{a}.{b}.{c}.{rng.randint(0, 255)}.{b}", "0.0.0", "unknown", f"197.{a}.{b}.-{c}"))


def _count_for(rng: random.Random, base: int, gen: GenerationConfig) -> int:
    return rng.randint(math.ceil(gen.taux_anomalie_min * base), math.floor(gen.taux_anomalie_max * base))


# -----------------------------------------------------------------------------
# Injection
# -----------------------------------------------------------------------------
def inject_anomalies(events: list[dict], gen: GenerationConfig,
                     rng: random.Random) -> tuple[AnomalyJournal, dict[str, int]]:
    journal = AnomalyJournal(SOURCE, ANOMALY_TYPES)
    n = len(events)
    bases = {code: n for code in ANOMALY_TYPES}
    codes = ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D10", "D11")
    tailles = {c: _count_for(rng, n, gen) for c in codes + ("D09",)}

    # Ensembles DISJOINTS : un document reçoit au plus une anomalie
    indices = rng.sample(range(n), sum(tailles[c] for c in codes))
    lots, debut = {}, 0
    for c in codes:
        lots[c] = indices[debut:debut + tailles[c]]
        debut += tailles[c]
    touches = set(indices)

    for i in lots["D01"]:
        doc = events[i]
        retires = [k for k in doc if k not in CHAMPS_CONSERVES_D01]
        for k in retires:
            del doc[k]
        journal.add("D01", doc["event_id"], ",".join(retires), "document tronqué")
    for i in lots["D02"]:
        doc = events[i]
        champ = rng.choice(CHAMPS_ABSENTS_D02)
        journal.add("D02", doc["event_id"], f"{champ}={doc[champ]}", f"{champ} absent")
        del doc[champ]
    for i in lots["D03"]:
        doc = events[i]
        champ = rng.choice(CHAMPS_NULS_D03)
        journal.add("D03", doc["event_id"], f"{champ}={doc[champ]}", f"{champ}=null")
        doc[champ] = None

    d04 = lots["D04"]
    dakar = [i for i in d04 if events[i]["city"] == "Dakar"]
    for i in d04:
        doc = events[i]
        # Les deux premiers exemples du PDF sont garantis
        new = ("DAKAR", "dakarr")[dakar.index(i)] if i in dakar[:2] else variante_ville(doc["city"], rng)
        journal.add("D04", doc["event_id"], doc["city"], new)
        doc["city"] = new
    d05_240 = [i for i in lots["D05"] if events[i]["app_version"] == "2.4.0"]
    for i in lots["D05"]:
        doc = events[i]
        # Les deux exemples du PDF (2.4 et v2.4 pour 2.4.0) sont garantis
        new = ("2.4", "v2.4")[d05_240.index(i)] if i in d05_240[:2] else variante_version(doc["app_version"], rng)
        journal.add("D05", doc["event_id"], doc["app_version"], new)
        doc["app_version"] = new
    d06_android = [i for i in lots["D06"] if events[i]["operating_system"] == "Android"]
    for i in lots["D06"]:
        doc = events[i]
        new = ("ANDROID", "android")[d06_android.index(i)] if i in d06_android[:2] \
            else rng.choice(VARIANTES_OS[doc["operating_system"]])
        journal.add("D06", doc["event_id"], doc["operating_system"], new)
        doc["operating_system"] = new
    for i in lots["D07"]:
        doc = events[i]
        champ_absent = rng.random() < 0.5            # moitié champ absent, moitié valeur nulle
        journal.add("D07", doc["event_id"], doc["student_code"], "absent" if champ_absent else "null")
        if champ_absent:
            del doc["student_code"]
        else:
            doc["student_code"] = None
    for i in lots["D08"]:
        doc = events[i]
        new = variante_timestamp(doc["timestamp"], rng)
        journal.add("D08", doc["event_id"], doc["timestamp"].isoformat(), new)
        doc["timestamp"] = new
    for i in lots["D10"]:
        doc = events[i]
        new = _invalid_ip(rng)
        journal.add("D10", doc["event_id"], doc["ip_address"], new)
        doc["ip_address"] = new
    for i in lots["D11"]:
        doc = events[i]
        new = -max(1, doc["duration_seconds"])
        journal.add("D11", doc["event_id"], doc["duration_seconds"], new)
        doc["duration_seconds"] = new

    # D09 : doublons (même contenu, même event_id), juste après l'original
    sources = set(rng.sample([i for i in range(n) if i not in touches], tailles["D09"]))
    resultat = []
    for i, doc in enumerate(events):
        resultat.append(doc)
        if i in sources:
            resultat.append(dict(doc, metadata=dict(doc["metadata"])))
            journal.add("D09", doc["event_id"], doc["event_id"], doc["event_id"])
    events[:] = resultat
    return journal, bases


# -----------------------------------------------------------------------------
# Mesure (identique en mémoire et sur les documents relus depuis MongoDB)
# -----------------------------------------------------------------------------
def _ip_invalide(v) -> bool:
    try:
        ipaddress.ip_address(v)
        return False
    except ValueError:
        return True


def measure_anomalies(events: list[dict]) -> dict[str, int]:
    def manquants(d):
        return sum(1 for f in CHAMPS_HORS_CODE if f not in d)

    return {
        "D01": sum(1 for d in events if manquants(d) >= 5),
        "D02": sum(1 for d in events if manquants(d) == 1),
        "D03": sum(1 for d in events if any(f in d and d[f] is None for f in CHAMPS_HORS_CODE)),
        "D04": sum(1 for d in events if d.get("city") is not None and d["city"] not in VILLES),
        "D05": sum(1 for d in events if d.get("app_version") is not None and not VERSION_RE.match(d["app_version"])),
        "D06": sum(1 for d in events if d.get("operating_system") is not None
                   and d["operating_system"] not in OPERATING_SYSTEMS),
        "D07": sum(1 for d in events if d.get("student_code") is None),
        "D08": sum(1 for d in events if "timestamp" in d and not isinstance(d["timestamp"], datetime)),
        "D09": len(events) - len({d["event_id"] for d in events}),
        "D10": sum(1 for d in events if d.get("ip_address") is not None and _ip_invalide(d["ip_address"])),
        "D11": sum(1 for d in events if isinstance(d.get("duration_seconds"), int) and d["duration_seconds"] < 0),
    }
