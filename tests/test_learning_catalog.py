"""Tests unitaires — common/learning_catalog.py"""
import re

from common import learning_catalog as lc
from common.academic_catalog import DEPARTEMENTS


def test_catalogue_coherent():
    assert lc.validate_learning_catalog() == []


def test_300_modules_et_8_categories():
    assert sum(lc.MODULES_PAR_CATEGORIE.values()) == 300
    assert set(lc.MODULES_PAR_CATEGORIE) == set(lc.CATEGORIES)


def test_format_des_codes():
    assert lc.module_code("IA", 1) == "MOD-IA-01"          # exemple du PDF MongoDB
    assert lc.course_code(15) == "COURSE-15" and lc.quiz_code(3) == "QUIZ-3"
    assert re.fullmatch(r"MOD-[A-Z]+-\d{2}", lc.module_code("Data", 39))


def test_chaque_departement_a_une_categorie():
    assert set(lc.DEPARTEMENT_VERS_CATEGORIE) == set(DEPARTEMENTS)
