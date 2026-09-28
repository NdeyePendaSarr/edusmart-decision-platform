"""Tests unitaires — conception du Data Warehouse (L6). Sans base : DDL et démonstration SCD 2."""
import re
from pathlib import Path

from common import senegalese_data as sn
from pipeline import verify_g4
from pipeline.demo_scd2 import choisir_demenagements
from pipeline.load_dw import DIMENSIONS, FAITS

SQL_DW = Path(verify_g4.__file__).parent / "sql" / "dw"
DDL_DIM = (SQL_DW / "01_dimensions.sql").read_text(encoding="utf-8")
DDL_FAITS = (SQL_DW / "02_faits.sql").read_text(encoding="utf-8")


def _bloc(ddl, table):
    m = re.search(rf"CREATE TABLE IF NOT EXISTS dw\.{table} \((.*?)\n\);", ddl, re.S)
    assert m, table
    return m.group(1)


def test_constellation_de_8_faits_et_7_dimensions():
    assert len(FAITS) == 8 and len(DIMENSIONS) == 7
    for t in FAITS:
        assert f"dw.{t} (" in DDL_FAITS
    for t in DIMENSIONS:
        assert f"dw.{t} (" in DDL_DIM


def test_chaque_fait_a_une_date_et_des_cles_obligatoires():
    for fait in FAITS:
        bloc = _bloc(DDL_FAITS, fait)
        assert "date_key" in bloc and "REFERENCES dw.dim_temps" in bloc
        for ligne in bloc.splitlines():
            if "REFERENCES dw.dim_" in ligne:
                assert "NOT NULL" in ligne, ligne          # jamais de clé étrangère NULL (membre -1)


def test_verify_g4_couvre_toutes_les_cles_etrangeres_du_ddl():
    for fait in FAITS:
        ddl = {m for m in re.findall(r"(\w+_key)\s+INTEGER NOT NULL REFERENCES", _bloc(DDL_FAITS, fait))}
        assert ddl == {col for col, _, _ in verify_g4.FK[fait]}, fait
    assert set(verify_g4.GRAIN) == set(FAITS) == set(verify_g4.SOURCE_CLEAN)


def test_membre_inconnu_dans_chaque_dimension():
    for dim in DIMENSIONS:
        assert re.search(rf"INSERT INTO dw\.{dim} .*?\(-1,", DDL_DIM, re.S), dim


def test_dim_etudiant_scd2():
    bloc = _bloc(DDL_DIM, "dim_etudiant")
    for col in ("etudiant_id", "date_debut", "date_fin", "est_courant", "version"):
        assert col in bloc
    assert "uq_dim_etudiant_courant ON dw.dim_etudiant (etudiant_id) WHERE est_courant" in DDL_DIM


def test_demenagements_deterministes_et_valides():
    villes = sorted(sn.CITY_TO_REGION)
    etudiants = [(f"id{i}", f"MAT{i:05d}", villes[i % len(villes)] if i % 7 else " dakar ", "MF"[i % 2] if i % 11 else "Homme")
                 for i in range(1000)]
    a, b = choisir_demenagements(etudiants), choisir_demenagements(etudiants)
    assert a == b and len(a) == 20
    for d in a:
        assert d["ancienne_ville"] in sn.CITY_TO_REGION                     # jamais une ville anomalie (A05)
        assert d["ancienne_region"] != d["nouvelle_region"]
        assert sn.CITY_TO_REGION[d["nouvelle_ville"]] == d["nouvelle_region"]
    choisis = {d["id_etudiant"] for d in a}
    assert not choisis & {e[0] for e in etudiants if e[3] == "Homme"}       # contrainte CHECK de la source
