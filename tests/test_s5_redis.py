"""
Tests unitaires — Source 5 Redis (snapshot, anomalies, chargement avec fakeredis).
Aucun serveur nécessaire. Génération complète : ~20 s (recalcule MongoDB et MySQL).
"""
import json
import re
from datetime import datetime, timedelta

import fakeredis
import pytest

from common.config import GenerationConfig
from common.referential import build_referential
from sources.s5_redis import anomalies as an
from sources.s5_redis import create_source as cs
from sources.s5_redis import generate_data as g
from sources.s5_redis.insert_data import load_into
from sources.s5_redis.verify_source import TYPES_ATTENDUS, famille, read_redis

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module")
def students():
    return build_referential(GEN)


@pytest.fixture(scope="module")
def codes_lms(students):
    return {s.student_code for s in students if s.student_code}


@pytest.fixture(scope="module")
def generated(students):
    return g.generate(GEN, students)          # (snapshot, journal, bases, verite)


def ids(journal, code):
    return {r.id_ligne for r in journal.records if r.code == code}


# --- Anomalies ------------------------------------------------------------------
def test_mesure_egale_journal(generated, codes_lms):
    snapshot, journal, _, verite = generated
    assert an.measure_anomalies(snapshot, verite, codes_lms) == journal.counts()


def test_sept_types_et_taux(generated):
    _, journal, bases, _ = generated
    counts = journal.counts()
    assert set(counts) == {f"E{i:02d}" for i in range(1, 8)}
    for code, n in counts.items():
        assert n > 0
        if code not in an.FIXED_BY_DESIGN:
            assert 0.02 <= n / bases[code] <= 0.05, (code, n, bases[code])


def test_compteurs_incoherents_comme_le_pdf(generated):
    snapshot, _, _, verite = generated
    assert int(snapshot["online_users"]["value"]) > int(snapshot["statistics:today"]["value"]["active_students"])
    assert verite["online_users"] <= verite["active_students"]         # la vérité, elle, est cohérente


# --- Structure (PDF) ------------------------------------------------------------
def test_types_et_familles(generated):
    snapshot, _, _, _ = generated
    assert {famille(k) for k in snapshot} == set(TYPES_ATTENDUS)
    assert all(it["type"] == TYPES_ATTENDUS[famille(k)] for k, it in snapshot.items())


def test_sessions(generated):
    snapshot, journal, _, verite = generated
    sessions = {k: it for k, it in snapshot.items() if k.startswith("session:")}
    e01, e02, e07 = ids(journal, "E01"), ids(journal, "E02"), ids(journal, "E07")
    propres = {k: it for k, it in sessions.items() if k not in e01 | e02}
    assert len(propres) == verite["sessions_actives"]
    for k, it in sessions.items():
        attendus = set(cs.SESSION_FIELDS) - ({"student_code"} if k in e07 else set())
        assert set(it["value"]) == attendus and it["value"]["status"] == "ONLINE"
        assert (it["ttl"] is None) == (k in e01)
    limite = cs.SNAPSHOT - timedelta(minutes=cs.INACTIVITE_MAX_MIN)
    for it in propres.values():
        assert datetime.strptime(it["value"]["last_activity"], cs.DATE_FMT) >= limite
    assert all(it["value"]["device"] in ("Android", "iOS") for it in sessions.values())   # « device = Android » (PDF)


def test_progress(generated):
    snapshot, journal, _, _ = generated
    e05 = ids(journal, "E05")
    for k, it in snapshot.items():
        if k.startswith("progress:"):
            v = it["value"]
            assert {"module", "progress", "last_update"} <= set(v) <= set(cs.PROGRESS_FIELDS)
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", v["last_update"])
            assert (float(v["progress"]) > 100) == (k in e05)
            assert it["ttl"] == cs.TTL_PROGRESS


def test_classement_et_notifications(generated, codes_lms):
    snapshot, _, _, _ = generated
    lb = snapshot["leaderboard:python"]["value"]
    assert set(lb) <= codes_lms and all(0 <= s <= 100 for s in lb.values())
    for k, it in snapshot.items():
        if k.startswith("notifications:"):
            assert 1 <= len(set(it["value"])) <= 4


def test_etudiants_inconnus(generated, codes_lms):
    snapshot, journal, _, _ = generated
    inconnus = an.student_codes(snapshot) - codes_lms
    assert inconnus == ids(journal, "E06")
    assert all(re.fullmatch(r"LMS-\d{6}", c) for c in inconnus)


# --- Chargement (fakeredis) --------------------------------------------------------
def test_chargement_et_relecture(generated, codes_lms):
    snapshot, journal, _, verite = generated
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set("cle_parasite", "x")                                   # doit être effacée (FLUSHDB)
    donnees = json.loads(json.dumps(snapshot))                        # comme lu depuis snapshot.json
    assert load_into(client, donnees) == len(snapshot)
    relu = read_redis(client)
    assert an.measure_anomalies(relu, verite, codes_lms) == journal.counts()
    assert set(relu) == set(snapshot)
    k = next(k for k in snapshot if k.startswith("notifications:"))
    assert relu[k]["value"] == snapshot[k]["value"]                     # ordre de la liste conservé
    assert sum(1 for k, it in relu.items() if k.startswith("session:") and it["ttl"] is None) == len(ids(journal, "E01"))


def test_dictionnaire():
    texte = cs.build_dictionnaire()
    for s in cs.STRUCTURES:
        assert s.motif in texte


def test_reproductibilite(generated, students):
    snapshot, _, _, _ = generated
    assert g.generate(GEN, students)[0] == snapshot
