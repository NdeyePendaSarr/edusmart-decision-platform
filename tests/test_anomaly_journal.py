"""Tests unitaires — common/anomaly_journal.py"""
import pytest

from common.anomaly_journal import AnomalyJournal, AnomalyType, read_journal

TYPES = {"X01": AnomalyType("X01", "t", "c", "desc", "pdf")}


def test_ajout_comptage_et_relecture(tmp_path):
    j = AnomalyJournal("test", TYPES)
    j.add("X01", "id-1", "avant", None)
    assert j.counts() == {"X01": 1}
    path = tmp_path / "journal.csv"
    assert j.write_csv(path) == 1
    lu = read_journal(path)
    assert lu[0].id_ligne == "id-1" and lu[0].valeur_injectee == ""


def test_type_inconnu_refuse():
    with pytest.raises(KeyError):
        AnomalyJournal("test", TYPES).add("ZZZ", "1", "a", "b")
