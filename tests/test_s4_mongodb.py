"""
Tests unitaires — Source 4 MongoDB (générateur, anomalies, validateur, fichier).
Aucun serveur MongoDB nécessaire (mongomock pour l'insertion). Génération complète : ~15 s.
"""
import hashlib
import itertools
from collections import defaultdict
from datetime import datetime, time

import mongomock
import pytest

from common.config import GenerationConfig
from common.referential import build_referential
from sources.s4_mongodb import anomalies as an
from sources.s4_mongodb import create_source as cs
from sources.s4_mongodb import generate_data as g
from sources.s4_mongodb.insert_data import load_into

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module")
def students():
    return build_referential(GEN)


@pytest.fixture(scope="module")
def generated(students):
    return g.generate(GEN, students)       # (events, journal, bases, sessions)


@pytest.fixture(scope="module")
def propres(generated):
    events, journal, _, _ = generated
    touches = {r.id_ligne for r in journal.records}
    return [d for d in events if d["event_id"] not in touches]


# --- Anomalies ------------------------------------------------------------------
def test_mesure_egale_journal(generated):
    events, journal, _, _ = generated
    assert an.measure_anomalies(events) == journal.counts()


def test_onze_types_et_taux(generated):
    _, journal, bases, _ = generated
    counts = journal.counts()
    assert set(counts) == {f"D{i:02d}" for i in range(1, 12)}
    for code, n in counts.items():
        assert 0.02 <= n / bases[code] <= 0.05, (code, n)


def test_exemples_du_pdf(generated):
    events, _, _, _ = generated
    villes = {d.get("city") for d in events}
    assert {"DAKAR", "dakarr", "Dakar"} <= villes
    assert {"ANDROID", "android", "Android"} <= {d.get("operating_system") for d in events}
    assert {"2.4", "v2.4", "2.4.0"} <= {d.get("app_version") for d in events}
    assert {type(d.get("timestamp")) for d in events if "timestamp" in d} == {datetime, str, int}


def test_volume(generated):
    events, _, _, _ = generated
    assert abs(len(events) - g.TARGET) <= g.TOLERANCE * g.TARGET
    assert g.PDF_MIN <= len(events) <= g.PDF_MAX


# --- Validateur -----------------------------------------------------------------
def test_documents_propres_valides(propres):
    assert not any(cs.violates_schema(d) for d in propres)


def test_validateur_detecte_les_anomalies_de_schema(generated):
    events, journal, _, _ = generated
    par_id = defaultdict(list)
    for d in events:
        par_id[d["event_id"]].append(d)
    detectables = {"D01", "D02", "D03", "D05", "D06", "D07", "D08", "D11"}
    for r in journal.records:
        doc = par_id[r.id_ligne][0]
        attendu = r.code in detectables
        assert cs.violates_schema(doc) is attendu, (r.code, doc)


def test_json_schema_coherent():
    assert set(cs.JSON_SCHEMA["required"]) == set(cs.STANDARD_FIELDS)
    assert cs.JSON_SCHEMA["properties"]["event_type"]["enum"] == list(cs.EVENT_TYPES)
    assert set(cs.CONTEXT_FIELDS) == set(cs.EVENT_TYPES) == set(cs.METADATA_FIELDS)


# --- Schéma flexible et sessions --------------------------------------------------
def test_schema_flexible(propres):
    for d in propres:
        contexte = {k for k in ("module_code", "course_code", "quiz_code") if k in d}
        assert contexte == set(cs.CONTEXT_FIELDS[d["event_type"]]), d["event_type"]
        assert set(cs.METADATA_FIELDS[d["event_type"]]) | {"network"} <= set(d["metadata"])


def test_sessions(generated):
    events, _, _, sessions = generated
    par_session = defaultdict(list)
    for d in events:
        par_session[d["session_id"]].append(d)
    for sid, docs in itertools.islice(par_session.items(), 5000):
        if all(isinstance(d.get("timestamp"), datetime) for d in docs):
            ordre = sorted(docs, key=lambda d: (d["timestamp"], d["event_type"] != "LOGIN"))
            assert ordre[0]["event_type"] == "LOGIN"
            if any(d["event_type"] == "LOGOUT" for d in docs):
                assert ordre[-1]["event_type"] == "LOGOUT"
        assert len({d["student_code"] for d in docs if isinstance(d.get("student_code"), str)}) <= 1
    ouvertes = [s for s in sessions if s["statut"] == "OUVERTE"]
    assert len(ouvertes) == g.NB_SESSIONS_OUVERTES
    # début vers 20 h (un LOGIN raté peut précéder d'une minute)
    assert all(s["debut"].date() == GEN.date_reference and s["debut"].time() >= time(19, 55) for s in ouvertes)
    assert all(not s["logout"] for s in ouvertes)


def test_population_et_date_limite(generated, students):
    events, _, _, _ = generated
    lms = {s.student_code for s in students if s.student_code}
    assert {d["student_code"] for d in events if isinstance(d.get("student_code"), str)} == lms
    limite = datetime.combine(GEN.date_reference, time(23, 59, 59))
    assert max(d["timestamp"] for d in events if isinstance(d.get("timestamp"), datetime)) <= limite


def test_versions_d_application():
    rng = g.get_rng("test_versions", seed=1)
    assert g.app_version_at(datetime(2023, 10, 1), rng) == "2.0.0"
    assert g.app_version_at(datetime(2026, 9, 1), rng) in ("2.4.1", "2.4.0")


# --- Fichier et insertion -----------------------------------------------------------
def test_fichier_aller_retour_et_octets(generated, tmp_path):
    events, _, _, _ = generated
    echantillon = events[:3000]
    g.write_events(echantillon, tmp_path / "a.jsonl.gz")
    g.write_events(echantillon, tmp_path / "b.jsonl.gz")
    md5 = [hashlib.md5((tmp_path / f).read_bytes()).hexdigest() for f in ("a.jsonl.gz", "b.jsonl.gz")]
    assert md5[0] == md5[1]                                   # gzip reproductible (mtime=0)
    assert list(g.read_events(tmp_path / "a.jsonl.gz")) == echantillon   # types conservés (date, texte, nombre)


def test_insertion_mongomock(generated, tmp_path):
    events, _, _, _ = generated
    g.write_events(events[:4000], tmp_path / "e.jsonl.gz")
    db = mongomock.MongoClient().edusmart_mobile
    assert load_into(db, tmp_path / "e.jsonl.gz", with_validator=False) == 4000
    assert {name for name, _ in cs.INDEXES} <= set(db[cs.COLLECTION].index_information())
    assert load_into(db, tmp_path / "e.jsonl.gz", with_validator=False) == 4000   # idempotent


def test_reproductibilite(students):
    echantillon = students[:400]
    a, _ = g.generate_clean(GEN, echantillon)
    b, _ = g.generate_clean(GEN, echantillon)
    assert a == b
