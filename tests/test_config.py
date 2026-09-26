"""Tests unitaires — common/config.py"""
from datetime import date

import pytest

from common.config import ConfigError, GenerationConfig, PostgresConfig, get_settings


def test_volumes_valides_par_defaut():
    gen = GenerationConfig()
    gen.validate()
    assert gen.nb_etudiants_pg == 10_000
    assert gen.nb_pg_avec_lms == 9_000
    assert gen.nb_pg_sans_lms == 1_000
    assert gen.nb_lms_orphelins == 500
    assert gen.nb_student_codes == 9_500


def test_periode_et_rentree():
    gen = GenerationConfig()
    assert gen.rentree("2024-2025") == date(2024, 10, 1)
    assert gen.periode_debut == date(2023, 10, 1)
    assert gen.periode_fin == date(2026, 9, 30)


@pytest.mark.parametrize("annee", ["2024-2026", "24-25", "2024/2025", ""])
def test_annee_academique_invalide(annee):
    with pytest.raises(ConfigError):
        GenerationConfig().rentree(annee)


def test_configuration_incoherente_rejetee():
    with pytest.raises(ConfigError):
        GenerationConfig(nb_etudiants_pg=100, nb_pg_avec_lms=200).validate()
    with pytest.raises(ConfigError):
        GenerationConfig(taux_anomalie_min=0.06, taux_anomalie_max=0.05).validate()


def test_mot_de_passe_jamais_dans_repr():
    cfg = PostgresConfig(service="t", host="h", port=1, user="u", password="SECRET", database="d")
    assert "SECRET" not in repr(cfg)


def test_mot_de_passe_par_defaut_refuse():
    cfg = PostgresConfig(service="t", host="h", port=1, user="u", password="change_me_pg", database="d")
    with pytest.raises(ConfigError):
        cfg.connect_kwargs()


def test_get_settings_est_mis_en_cache():
    assert get_settings() is get_settings()


def test_ports_par_defaut_hors_ports_reserves(monkeypatch):
    """Les ports par défaut n'utilisent pas ceux de l'autre projet (5433, 27017, 8080)."""
    for var in ("PG_SOURCE_PORT", "PG_DW_PORT", "MYSQL_PORT", "MONGO_PORT", "REDIS_PORT"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("common.config.load_dotenv", None)  # ignorer un éventuel docker/.env
    try:
        s = get_settings()
        ports = {s.pg_source.port, s.pg_dw.port, s.mysql.port, s.mongo.port, s.redis.port}
        assert ports == {5435, 5434, 3307, 27018, 6380}
        assert not ports & {5433, 27017, 8080}
    finally:
        get_settings.cache_clear()
