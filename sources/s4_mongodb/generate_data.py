"""
sources/s4_mongodb/generate_data.py — Génération de la Source 4 (Lot L2-d)
=========================================================================

Produit ~300 000 événements de l'application mobile (PDF Source 4), organisés
en SESSIONS : LOGIN -> activités -> LOGOUT (parfois absent : application fermée).

Cohérence avec les autres sources (vérité terrain, jamais lue par l'ETL)
    - Population : les 9 500 comptes LMS (dont 500 orphelins) ; appareil,
      ville et fenêtre d'activité propres à chaque étudiant.
    - QUIZ_SUBMITTED : 8 % des notes MySQL (propres) sont passées sur mobile.
      Même quiz (QUIZ-n), même score, même tentative, même horodatage.
    - PAYMENT_* : 60 % des paiements PostgreSQL par Orange Money ou Wave des
      étudiants ayant un compte LMS passent par l'application. Même référence,
      même montant ; un paiement ECHOUE donne un PAYMENT_FAILED.
    - Codes de contenus : issus du référentiel caché (100 %) ; 5 % d'entre eux
      sont absents de mapping_courses.csv (décision C22).
    - Sessions « ouvertes » le 15/09/2026 au soir (pas de LOGOUT) : ce sont
      les sessions que Redis (L2-e) montrera comme en ligne.

Sorties
    data/generated/s4_mongodb/events.jsonl.gz     (JSON étendu MongoDB, 1 document par ligne)
    data/generated/s4_mongodb/summary.json
    data/referential/sessions_mobile.csv          (CACHÉ : sessions, pour Redis et les tests)
    data/anomalies/s4_mongodb_anomalies.csv

Exécution : python -m sources.s4_mongodb.generate_data   (~30 s)
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import random
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from common import senegalese_data as sn
from common.config import GenerationConfig, get_settings
from common.logger import get_logger, log_step
from common.referential import STATUT_APPARIE, STATUT_LMS_ORPHELIN, MasterStudent, load_referential
from common.seed import deterministic_uuid, get_faker, get_rng
from sources.s4_mongodb.anomalies import SOURCE, inject_anomalies, measure_anomalies
from sources.s4_mongodb.create_source import EVENT_TYPES

logger = get_logger("s4_generate")

TARGET, TOLERANCE, PDF_MIN, PDF_MAX = 300_000, 0.05, 200_000, 500_000
EVENTS_FILENAME = "events.jsonl.gz"
SESSIONS_FILENAME = "sessions_mobile.csv"
SESSIONS_COLUMNS = ["session_id", "student_code", "debut", "fin", "device", "operating_system", "app_version",
                    "ip_address", "city", "logout", "statut"]

# Paramètres de simulation (conventions, voir README)
P_NOTE_MOBILE = 0.08            # part des notes MySQL passées sur l'application
P_PAIEMENT_APP = 0.60           # part des paiements OM/Wave faits via l'application
ECART_SESSION = timedelta(hours=2)
P_LOGOUT = 0.90                 # sinon : application fermée sans déconnexion
P_ECHEC_LOGIN = 0.04
P_AUTRE_VILLE = 0.08
NB_SESSIONS_OUVERTES = 700      # 15/09/2026 au soir, pour Redis (L2-e)
FIN_JOURNEE = time(23, 59, 59)

APP_RELEASES = (("2.0.0", date(2023, 9, 1)), ("2.1.0", date(2024, 1, 15)), ("2.1.1", date(2024, 4, 10)),
                ("2.2.0", date(2024, 9, 1)), ("2.3.0", date(2025, 2, 1)), ("2.3.1", date(2025, 6, 15)),
                ("2.4.0", date(2025, 10, 1)), ("2.4.1", date(2026, 3, 15)))
DEVICES = {"Android": ("Samsung Galaxy A54", "Samsung Galaxy A14", "Samsung Galaxy A05s", "Tecno Spark 10",
                       "Tecno Camon 20", "Infinix Hot 30", "Infinix Smart 7", "Itel A70", "Xiaomi Redmi Note 12",
                       "Xiaomi Redmi 12C", "Huawei Y9 Prime", "Oppo A17"),
           "iOS": ("iPhone 11", "iPhone 12", "iPhone 13", "iPhone 14", "iPhone SE (2022)", "iPhone XR")}
NETWORKS, NETWORK_WEIGHTS = ("4G", "WiFi", "3G"), (60, 25, 15)
EXTRAS, EXTRAS_WEIGHTS = (("COURSE_OPENED", "VIDEO_STARTED", "RESOURCE_DOWNLOADED", "SEARCH", "PROFILE_UPDATED"),
                          (40, 30, 12, 16, 2))
RECHERCHES = ("python", "sql", "power bi", "machine learning", "examen", "certificat", "excel", "réseaux",
              "cybersécurité", "comptabilité", "marketing", "projet", "quiz", "emploi du temps", "paiement")
ERREURS_PAIEMENT = ("Solde insuffisant", "Délai dépassé", "Code secret incorrect")


class GenerationError(Exception):
    """Erreur bloquante pendant la génération de la Source 4."""


# -----------------------------------------------------------------------------
# Profils mobiles et ancrages
# -----------------------------------------------------------------------------
def app_version_at(t: datetime, rng: random.Random) -> str:
    """Version installée : la dernière publiée, ou la précédente (25 % n'ont pas mis à jour)."""
    publiees = [v for v, d in APP_RELEASES if d <= t.date()]
    if len(publiees) > 1 and rng.random() < 0.25:
        return publiees[-2]
    return publiees[-1]


def _paiements_via_app(students: list[MasterStudent], gen, rng) -> dict[str, list[tuple[datetime, dict]]]:
    """Paiements PostgreSQL (propres) passés par l'application, par student_code."""
    from sources.s1_postgresql.generate_data import generate_clean as s1_clean
    pg = [s for s in students if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    tables = s1_clean(pg, gen)
    code_de = {s.id_etudiant: s.student_code for s in students if s.statut_correspondance == STATUT_APPARIE}
    etudiant_de = {i["id_inscription"]: i["id_etudiant"] for i in tables["inscriptions"]}
    ancres = defaultdict(list)
    for p in tables["paiements"]:
        code = code_de.get(etudiant_de[p["id_inscription"]])
        if (code and p["mode_paiement"] in ("Orange Money", "Wave") and p["statut"] in ("VALIDE", "ECHOUE")
                and p["date_paiement"] >= gen.periode_debut and rng.random() < P_PAIEMENT_APP):
            t = datetime.combine(p["date_paiement"], time(rng.randint(8, 21), rng.randint(0, 59), rng.randint(0, 59)))
            ancres[code].append((t, {"kind": "payment", **p}))
    return ancres


# -----------------------------------------------------------------------------
# Construction des sessions
# -----------------------------------------------------------------------------
class SessionBuilder:
    def __init__(self, gen: GenerationConfig, rng: random.Random, fake, contenus: dict):
        self.gen, self.rng, self.fake, self.c = gen, rng, fake, contenus
        self.ref_end = datetime.combine(gen.date_reference, FIN_JOURNEE)
        self.events: list[dict] = []
        self.sessions: list[dict] = []

    def _event(self, s: dict, event_type: str, t: datetime, duration: int, success: bool = True,
               context: dict | None = None, meta: dict | None = None) -> dict:
        doc = {"event_id": deterministic_uuid(self.rng), "student_code": s["student_code"],
               "timestamp": t.replace(microsecond=0), "event_type": event_type}
        doc.update(context or {})
        doc.update({"device": s["device"], "operating_system": s["operating_system"],
                    "app_version": s["app_version"], "ip_address": s["ip_address"], "city": s["city"],
                    "country": sn.PAYS, "session_id": s["session_id"], "duration_seconds": int(duration),
                    "success": success, "metadata": {"network": s["network"], **(meta or {})}})
        return doc

    def _context_module(self, code: str):
        modules = self.c["modules_etudiant"].get(code)
        if not modules:
            return None
        id_module = self.rng.choice(modules)
        id_cours = self.rng.choice(self.c["cours_par_module"][id_module])
        return {"module_code": self.c["code"][id_module], "course_code": self.c["code"][id_cours]}

    def _extra(self, s: dict, t: datetime) -> list[dict]:
        rng, kind = self.rng, self.rng.choices(EXTRAS, weights=EXTRAS_WEIGHTS, k=1)[0]
        ctx = self._context_module(s["student_code"])
        if kind == "SEARCH" or ctx is None:
            return [self._event(s, "SEARCH", t, rng.randint(2, 40),
                                meta={"query": rng.choice(RECHERCHES), "results_count": rng.randint(0, 40)})]
        if kind == "PROFILE_UPDATED":
            return [self._event(s, kind, t, rng.randint(10, 180),
                                meta={"field": rng.choice(("telephone", "photo", "ville", "email"))})]
        if kind == "RESOURCE_DOWNLOADED":
            return [self._event(s, kind, t, rng.randint(2, 120), context=ctx,
                                meta={"resource_type": rng.choice(("PDF", "ZIP", "MP4")),
                                      "size_mb": round(rng.uniform(0.2, 150), 1)})]
        if kind == "VIDEO_STARTED":
            duree = rng.randint(60, 2400)
            evs = [self._event(s, kind, t, duree, context=ctx,
                               meta={"video_quality": rng.choice(("360p", "480p", "720p", "1080p")),
                                     "buffer_time": round(rng.uniform(0.1, 12.0), 1)})]
            if rng.random() < 0.7:
                evs.append(self._event(s, "VIDEO_FINISHED", t + timedelta(seconds=duree), rng.randint(1, 10),
                                       context=ctx, meta={"watched_percent": rng.randint(85, 100)}))
            return evs
        duree = rng.randint(60, 1500)                                  # COURSE_OPENED
        evs = [self._event(s, "COURSE_OPENED", t, duree, context=ctx, meta={"progress": rng.randint(0, 95)})]
        if rng.random() < 0.15:
            evs.append(self._event(s, "COURSE_COMPLETED", t + timedelta(seconds=duree), rng.randint(5, 60),
                                   context=ctx, meta={"progress": 100}))
        return evs

    def _anchor(self, s: dict, a: dict, t: datetime) -> list[dict]:
        rng = self.rng
        if a["kind"] == "quiz":
            q = a["id_quiz"]
            id_cours = self.c["quiz_cours"][q]
            ctx = {"module_code": self.c["code"][self.c["cours_module"][id_cours]],
                   "course_code": self.c["code"][id_cours], "quiz_code": self.c["code"][q]}
            duree = max(30, int(self.c["quiz_duree"][q] * 60 * rng.uniform(0.4, 1.0)))
            return [self._event(s, "QUIZ_STARTED", t - timedelta(seconds=duree), rng.randint(1, 5), context=ctx,
                                meta={"attempt": a["tentative"]}),
                    self._event(s, "QUIZ_SUBMITTED", t, duree, success=bool(a["valide"]), context=ctx,
                                meta={"score": float(a["score"]), "attempt": a["tentative"]})]
        meta = {"amount": float(a["montant"]), "currency": "XOF", "method": a["mode_paiement"],
                "reference": a["reference"], "tranche": a["tranche"]}
        fin = t + timedelta(seconds=rng.randint(20, 180))
        if a["statut"] == "ECHOUE":
            final = self._event(s, "PAYMENT_FAILED", fin, rng.randint(3, 30), success=False,
                                meta={**meta, "error": rng.choice(ERREURS_PAIEMENT)})
        else:
            final = self._event(s, "PAYMENT_SUCCESS", fin, rng.randint(3, 30), meta=meta)
        return [self._event(s, "PAYMENT_STARTED", t, rng.randint(5, 60), meta=meta), final]

    def build(self, profil: dict, debut: datetime, ancres: list[tuple[datetime, dict]], nb_extras: int,
              ouverte: bool = False) -> None:
        rng = self.rng
        city = profil["city"] if rng.random() > P_AUTRE_VILLE else rng.choice(sorted(sn.CITY_TO_REGION))
        device, os_ = profil["device"], profil["operating_system"]
        if rng.random() < 0.10:                                         # second appareil occasionnel
            os_ = rng.choice(("Android", "iOS"))
            device = rng.choice(DEVICES[os_])
        s = {"session_id": deterministic_uuid(rng), "student_code": profil["student_code"], "device": device,
             "operating_system": os_, "app_version": app_version_at(debut, rng), "ip_address": self.fake.ipv4_public(),
             "city": city, "network": rng.choices(NETWORKS, weights=NETWORK_WEIGHTS, k=1)[0]}
        # Contenu d'abord (extras + ancrages), puis LOGIN juste avant l'événement le plus ancien :
        # un QUIZ_STARTED est antérieur à sa note (durée du quiz) et ne doit jamais précéder le LOGIN.
        contenu = []
        fin_contenu = max([t for t, _ in ancres], default=debut + timedelta(minutes=rng.randint(5, 60)))
        for _ in range(nb_extras):
            t = debut + timedelta(seconds=rng.randint(10, max(11, int((fin_contenu - debut).total_seconds()))))
            contenu.extend(self._extra(s, t))
        for t, a in ancres:
            contenu.extend(self._anchor(s, a, t))
        t_login = min([debut] + [e["timestamp"] - timedelta(seconds=rng.randint(5, 120)) for e in contenu])
        evs = []
        if rng.random() < P_ECHEC_LOGIN:
            evs.append(self._event(s, "LOGIN", t_login - timedelta(minutes=1), rng.randint(1, 8), success=False,
                                   meta={"method": "password"}))
        evs.append(self._event(s, "LOGIN", t_login, rng.randint(1, 8), meta={"method": rng.choice(("password", "otp"))}))
        evs.extend(contenu)
        evs = [e for e in evs if e["timestamp"] <= self.ref_end]
        dernier = max(e["timestamp"] for e in evs)
        logout = False
        if not ouverte and rng.random() < P_LOGOUT:
            t_out = dernier + timedelta(seconds=rng.randint(10, 600))
            if t_out <= self.ref_end:
                evs.append(self._event(s, "LOGOUT", t_out, rng.randint(0, 3)))
                dernier, logout = t_out, True
        self.events.extend(evs)
        self.sessions.append({"session_id": s["session_id"], "student_code": s["student_code"],
                              "debut": min(e["timestamp"] for e in evs), "fin": dernier, "device": device,
                              "operating_system": os_, "app_version": s["app_version"],
                              "ip_address": s["ip_address"], "city": city, "logout": logout,
                              "statut": "OUVERTE" if ouverte else ("FERMEE" if logout else "SANS_LOGOUT")})


def generate_clean(gen: GenerationConfig, students: list[MasterStudent]):
    """Événements PROPRES + sessions (aucune anomalie)."""
    from sources.s2_mysql.generate_data import generate_clean as s2_clean

    rng = get_rng(SOURCE, seed=gen.seed)
    fake = get_faker(SOURCE, seed=gen.seed)
    t2, codes, profils_lms = s2_clean(gen, students)
    contenus = {
        "code": {c["id_mysql"]: c["code_externe"] for c in codes},
        "cours_module": {c["id_cours"]: c["id_module"] for c in t2["cours"]},
        "quiz_cours": {q["id_quiz"]: q["id_cours"] for q in t2["quiz"]},
        "quiz_duree": {q["id_quiz"]: q["duree_minutes"] for q in t2["quiz"]},
        "cours_par_module": defaultdict(list), "modules_etudiant": defaultdict(list),
    }
    for c in t2["cours"]:
        contenus["cours_par_module"][c["id_module"]].append(c["id_cours"])
    for p in t2["progression"]:
        contenus["modules_etudiant"][p["student_code"]].append(p["id_module"])

    ville = {s.student_code: s.ville for s in students if s.student_code}
    ancres = defaultdict(list)
    for n in t2["notes"]:
        if rng.random() < P_NOTE_MOBILE:
            ancres[n["student_code"]].append((n["date_passage"], {"kind": "quiz", **n}))
    for code, lst in _paiements_via_app(students, gen, rng).items():
        ancres[code].extend(lst)

    builder = SessionBuilder(gen, rng, fake, contenus)
    actifs = sorted(p.student_code for p in profils_lms if p.fin == gen.date_reference)
    ouvertes = set(rng.sample(actifs, min(NB_SESSIONS_OUVERTES, len(actifs))))
    for p in profils_lms:
        os_ = rng.choices(("Android", "iOS"), weights=(78, 22), k=1)[0]
        profil = {"student_code": p.student_code, "city": ville[p.student_code], "operating_system": os_,
                  "device": rng.choice(DEVICES[os_])}
        # 1. Sessions autour des ancrages (notes, paiements) regroupés à moins de 2 h d'écart
        groupe: list = []
        for t, a in sorted(ancres[p.student_code], key=lambda x: x[0]) + [(None, None)]:
            if groupe and (t is None or t - groupe[-1][0] > ECART_SESSION):
                debut = groupe[0][0] - timedelta(minutes=rng.randint(2, 15), seconds=rng.randint(0, 59))
                builder.build(profil, debut, groupe, rng.choices((0, 1, 2, 3), weights=(45, 35, 15, 5))[0])
                groupe = []
            if t is not None:
                groupe.append((t, a))
        # 2. Sessions de consultation (au moins une par compte LMS)
        fin_active = max(p.debut + timedelta(days=30), p.fin)
        for _ in range(rng.randint(1, 2)):
            jour = p.debut + timedelta(days=rng.randint(0, (fin_active - p.debut).days))
            debut = datetime.combine(min(jour, gen.date_reference), time(rng.randint(6, 20), rng.randint(0, 59)))
            builder.build(profil, debut, [], rng.randint(2, 6))
        # 3. Session encore ouverte le 15/09/2026 au soir (Redis, L2-e)
        if p.student_code in ouvertes:
            debut = datetime.combine(gen.date_reference, time(rng.randint(20, 22), rng.randint(0, 59)))
            builder.build(profil, debut, [], rng.randint(1, 4), ouverte=True)

    builder.events.sort(key=lambda e: (e["timestamp"], e["event_id"]))
    return builder.events, builder.sessions


def generate(gen: GenerationConfig | None = None, students: list[MasterStudent] | None = None):
    """Retourne (events, journal, bases, sessions)."""
    gen = gen or get_settings().generation
    students = students if students is not None else load_referential()
    events, sessions = generate_clean(gen, students)
    journal, bases = inject_anomalies(events, gen, get_rng(f"{SOURCE}_anomalies", seed=gen.seed))
    mesure, attendu = measure_anomalies(events), journal.counts()
    if mesure != attendu:
        ecarts = {c: (attendu[c], mesure[c]) for c in attendu if attendu[c] != mesure[c]}
        raise GenerationError(f"Journal et données divergent (journal, mesure) : {ecarts}")
    return events, journal, bases, sessions


# -----------------------------------------------------------------------------
# Écriture
# -----------------------------------------------------------------------------
def write_events(events: list[dict], path: Path) -> int:
    """JSON étendu MongoDB (relaxed), compressé gzip, reproductible (mtime=0)."""
    from bson import json_util
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".events_", suffix=".tmp")
    os.close(fd)
    try:
        with open(tmp, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            for doc in events:
                gz.write((json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS,
                                          ensure_ascii=False) + "\n").encode("utf-8"))
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise GenerationError(f"Écriture impossible de {path} : {exc}") from exc
    return len(events)


def read_events(path: Path):
    """Relit le fichier (générateur de documents : pas de chargement complet en mémoire)."""
    from bson import json_util
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json_util.loads(line)


def write_sessions(sessions: list[dict], path: Path) -> None:
    from common.referential import _atomic_write_csv
    _atomic_write_csv(path, SESSIONS_COLUMNS,
                      ([s[c].strftime("%Y-%m-%d %H:%M:%S") if isinstance(s[c], datetime) else
                        ("true" if s[c] is True else "false" if s[c] is False else s[c]) for c in SESSIONS_COLUMNS]
                       for s in sessions))


def build_summary(events, journal_counts, bases, sessions, gen) -> dict:
    types = defaultdict(int)
    for e in events:
        types[e.get("event_type")] += 1
    statuts = defaultdict(int)
    for s in sessions:
        statuts[s["statut"]] += 1
    return {"source": SOURCE, "seed": gen.seed, "volume": len(events), "cible": TARGET,
            "par_type": {t: types[t] for t in EVENT_TYPES}, "sessions": len(sessions), "sessions_par_statut": statuts,
            "anomalies": {c: {"nombre": n, "base": bases[c], "taux": round(n / bases[c], 4)}
                          for c, n in journal_counts.items()}}


def main() -> int:
    settings = get_settings()
    gen = settings.generation
    out_dir = settings.paths.generated_dir / SOURCE
    try:
        settings.paths.ensure_directories()
        with log_step(logger, "Génération Source 4 (MongoDB)"):
            events, journal, bases, sessions = generate(gen)
        with log_step(logger, "Écriture des événements, des sessions et du journal"):
            n = write_events(events, out_dir / EVENTS_FILENAME)
            write_sessions(sessions, settings.paths.referential_dir / SESSIONS_FILENAME)
            journal.write_csv(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv")
            summary = build_summary(events, journal.counts(), bases, sessions, gen)
            (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("%d événements, %d sessions %s", n, len(sessions), dict(summary["sessions_par_statut"]))
        logger.info("Par type : %s", summary["par_type"])
        for code, info in summary["anomalies"].items():
            logger.info("%s : %6d / %6d = %5.2f %%", code, info["nombre"], info["base"], 100 * info["taux"])
        return 0
    except (GenerationError, OSError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la génération de la Source 4")
        return 2


if __name__ == "__main__":
    sys.exit(main())
