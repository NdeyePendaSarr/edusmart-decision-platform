"""Tests unitaires — common/senegalese_data.py"""
import pytest

from common import senegalese_data as sn
from common.seed import get_rng


def test_listes_coherentes():
    assert sn.validate_reference_data() == []


def test_quatorze_regions():
    assert len(sn.REGIONS) == 14
    assert "Kédougou" in sn.REGIONS and "Sédhiou" in sn.REGIONS


def test_ville_et_region_coherentes():
    rng = get_rng("test_regions", seed=1)
    for _ in range(500):
        region, ville = sn.random_region_and_city(rng)
        assert sn.CITY_TO_REGION[ville] == region


@pytest.mark.parametrize("ville,region", [
    ("Dakar", "Dakar"), ("DAKAR", "Dakar"), (" dakar ", "Dakar"),
    ("thies", "Thiès"), ("MBOUR", "Thiès"), ("Touba", "Diourbel"),
])
def test_region_of_city_insensible_casse_et_accents(ville, region):
    assert sn.region_of_city(ville) == region


@pytest.mark.parametrize("ville", ["dakarr", "", None, "Paris"])
def test_region_of_city_inconnue(ville):
    assert sn.region_of_city(ville) is None


def test_telephone_canonique():
    rng = get_rng("test_tel", seed=1)
    for _ in range(200):
        assert sn.PHONE_CANONICAL_RE.match(sn.random_phone(rng))


@pytest.mark.parametrize("style,attendu", [
    ("international", "+221 77 123 45 67"),
    ("international_compact", "+221771234567"),
    ("local", "77 123 45 67"),
    ("local_compact", "771234567"),
    ("double_zero", "00221771234567"),
])
def test_formats_telephone(style, attendu):
    assert sn.format_phone("77", "1234567", style) == attendu


def test_telephone_invalide():
    with pytest.raises(ValueError):
        sn.format_phone("33", "1234567")      # préfixe fixe, pas mobile
    with pytest.raises(ValueError):
        sn.format_phone("77", "12345")        # trop court
    with pytest.raises(ValueError):
        sn.format_phone("77", "1234567", "inconnu")


def test_prenom_selon_sexe():
    rng = get_rng("test_prenom", seed=1)
    assert sn.random_first_name(rng, "M") in sn.PRENOMS_MASCULINS
    assert sn.random_first_name(rng, "F") in sn.PRENOMS_FEMININS
    with pytest.raises(ValueError):
        sn.random_first_name(rng, "Homme")
