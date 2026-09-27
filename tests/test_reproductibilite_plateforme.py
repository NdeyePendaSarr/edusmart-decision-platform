"""
Reproductibilité entre machines (Windows / Linux, fuseaux horaires différents).

Cause corrigée en L4 : fake.date_between_dates() passait par le fuseau de la
machine et, sous Windows, ignorait une OSError pour les dates avant 1970 :
la Source 3 différait d'un poste à l'autre. On force ici un fuseau exotique
dans Faker : les données doivent rester IDENTIQUES.
"""
from datetime import date, timedelta, timezone

import pytest

import faker.providers.date_time as faker_dt
from common.config import GenerationConfig
from common.referential import build_referential
from common.referential import main as build_referential_files
from common.seed import get_rng, random_date

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module", autouse=True)
def referentiel():
    assert build_referential_files() == 0


@pytest.mark.parametrize("decalage", [+5, -8])
def test_source3_independante_du_fuseau(monkeypatch, decalage):
    from sources.s3_csv.generate_data import generate_clean
    reference, _ = generate_clean(GEN)
    monkeypatch.setattr(faker_dt, "_get_local_timezone", lambda: timezone(timedelta(hours=decalage)))
    autre, _ = generate_clean(GEN)
    assert autre == reference


@pytest.mark.parametrize("decalage", [+5, -8])
def test_source1_independante_du_fuseau(monkeypatch, decalage):
    from sources.s1_postgresql.generate_data import generate_clean
    etudiants = [s for s in build_referential(GEN) if s.statut_correspondance != "LMS_ORPHELIN"][:300]
    reference = generate_clean(etudiants, GEN)
    monkeypatch.setattr(faker_dt, "_get_local_timezone", lambda: timezone(timedelta(hours=decalage)))
    assert generate_clean(etudiants, GEN) == reference


def test_random_date():
    rng_a, rng_b = get_rng("t", seed=1), get_rng("t", seed=1)
    tirages = [random_date(rng_a, date(1958, 1, 1), date(1995, 12, 31)) for _ in range(200)]
    assert tirages == [random_date(rng_b, date(1958, 1, 1), date(1995, 12, 31)) for _ in range(200)]
    assert all(date(1958, 1, 1) <= d <= date(1995, 12, 31) for d in tirages)
    with pytest.raises(ValueError):
        random_date(rng_a, date(2000, 1, 2), date(2000, 1, 1))


def test_aucun_appel_faker_date_dans_la_source3():
    from pathlib import Path
    code = (Path(__file__).resolve().parent.parent / "sources" / "s3_csv" / "generate_data.py").read_text(encoding="utf-8")
    assert "fake.date_between_dates(" not in code          # le commentaire explicatif est autorisé
