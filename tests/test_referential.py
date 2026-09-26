"""Tests unitaires — common/referential.py"""
import csv
from collections import Counter

import pytest

from common.config import GenerationConfig
from common import referential as ref

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module")
def records():
    return ref.build_referential(GEN)


def test_referential_valide(records):
    assert ref.validate_referential(records, GEN) == []


def test_volumes(records):
    statuts = Counter(r.statut_correspondance for r in records)
    assert len(records) == 10_500
    assert statuts[ref.STATUT_APPARIE] == 9_000
    assert statuts[ref.STATUT_SANS_LMS] == 1_000
    assert statuts[ref.STATUT_LMS_ORPHELIN] == 500
    assert sum(1 for r in records if r.student_code) == 9_500


def test_unicite(records):
    for attr in ("id_etudiant", "matricule", "student_code"):
        valeurs = [getattr(r, attr) for r in records if getattr(r, attr)]
        assert len(valeurs) == len(set(valeurs)), attr


def test_reproductible(records):
    assert ref.build_referential(GEN) == records


def test_graine_differente_donnees_differentes(records):
    autre = ref.build_referential(GenerationConfig(seed=7))
    assert [r.id_etudiant for r in autre[:10]] != [r.id_etudiant for r in records[:10]]


def test_code_lms_independant_du_matricule(records):
    """Les codes LMS ne suivent pas l'ordre des matricules (numéros mélangés)."""
    codes = [int(r.student_code[4:]) for r in records if r.statut_correspondance == ref.STATUT_APPARIE]
    assert codes != sorted(codes)


def test_orphelins_absents_de_postgresql(records):
    for r in records:
        if r.statut_correspondance == ref.STATUT_LMS_ORPHELIN:
            assert r.id_etudiant is None and r.matricule is None


def test_validation_detecte_une_erreur(records):
    casse = list(records)
    casse[0] = ref.MasterStudent(**{**casse[0].__dict__, "ville": "Ziguinchor", "region": "Dakar"})
    assert any("n'appartient pas" in e for e in ref.validate_referential(casse, GEN))


def test_ecriture_et_relecture(records, tmp_path):
    path = ref.write_referential(records, tmp_path)
    assert ref.load_referential(path) == records


def test_mapping_etudiants_ne_contient_que_les_paires(records, tmp_path):
    path = ref.write_mapping_etudiants(records, tmp_path)
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 9_000
    assert all(row["student_code"] and row["matricule"] for row in rows)
    assert list(rows[0]) == ref.MAPPING_ETUDIANTS_COLUMNS


def test_mapping_courses_squelette_non_ecrase(tmp_path):
    path = ref.init_mapping_courses(tmp_path)
    assert path.read_text(encoding="utf-8").strip() == ",".join(ref.MAPPING_COURSES_COLUMNS)
    path.write_text(path.read_text(encoding="utf-8") + "COURSE,COURSE-1,uuid,MOD-IA-01,APPARIE\n",
                    encoding="utf-8")
    ref.init_mapping_courses(tmp_path)
    assert "COURSE-1" in path.read_text(encoding="utf-8")


def test_lecture_fichier_absent(tmp_path):
    with pytest.raises(ref.ReferentialError):
        ref.load_referential(tmp_path / "absent.csv")
