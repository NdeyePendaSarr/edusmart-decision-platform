"""Tests unitaires — common/academic_catalog.py"""
from common import academic_catalog as cat


def test_catalogue_coherent():
    assert cat.validate_catalog() == []


def test_vingt_cinq_filieres_et_huit_departements():
    assert len(cat.FILIERES) == 25
    assert len(cat.DEPARTEMENTS) == 8
    assert {f.niveau for f in cat.FILIERES} == {"LICENCE", "MASTER", "CERTIFICAT"}


def test_trois_libelles_ia_du_pdf():
    libelles = {f.nom_filiere for f in cat.FILIERES if f.libelle_canonique == cat.LIBELLE_IA_CANONIQUE}
    assert libelles == {"Intelligence Artificielle", "IA", "Ingénierie IA"}


def test_vivier_enseignants_deterministe_et_unique():
    a, b = cat.build_teacher_pool(seed=1), cat.build_teacher_pool(seed=1)
    assert a == b and len(a) == cat.NB_ENSEIGNANTS
    assert len({t.nom_complet for t in a}) == len(a)
    assert len({t.teacher_code for t in a}) == len(a)
    assert {t.departement for t in a} == set(cat.DEPARTEMENTS)
