"""Tests unitaires — common/seed.py (reproductibilité)"""
import uuid

import pytest

from common.seed import derive_seed, deterministic_uuid, get_faker, get_rng


def test_meme_namespace_meme_sequence():
    a, b = get_rng("test", seed=1), get_rng("test", seed=1)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_namespaces_independants():
    assert derive_seed("pg_etudiants", seed=1) != derive_seed("mysql_notes", seed=1)


def test_graines_differentes_sequences_differentes():
    assert get_rng("test", seed=1).random() != get_rng("test", seed=2).random()


def test_uuid_deterministe_et_version_4():
    u1 = deterministic_uuid(get_rng("uuid", seed=1))
    u2 = deterministic_uuid(get_rng("uuid", seed=1))
    assert u1 == u2
    assert uuid.UUID(u1).version == 4


def test_faker_reproductible():
    assert get_faker("f", seed=1).name() == get_faker("f", seed=1).name()


def test_namespace_vide_refuse():
    with pytest.raises(ValueError):
        derive_seed("")
