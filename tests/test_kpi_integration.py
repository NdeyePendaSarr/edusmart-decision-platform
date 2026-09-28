"""
Test d'intégration — KPI et cube OLAP sur le vrai entrepôt (L7).
Prérequis : pipeline exécuté jusqu'au DW.
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_kpi_integration.py -v
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def dw():
    import psycopg2
    from common.config import get_settings
    from pipeline import olap
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    olap.executer(conn)
    yield conn
    conn.close()


def _v(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def test_porte_g5a(dw):
    from pipeline import kpi
    comparaison = kpi.comparer(kpi.valeurs_sql(dw), kpi.recalculer(dw))
    assert all(ok for _, ok, _, _ in comparaison), [c for c in comparaison if not c[1]]


def test_total_du_cube_egal_au_kpi_ca(dw):
    total = _v(dw, "SELECT ca FROM dw.cube_finance WHERE niveau_agregation = 7")
    assert total == _v(dw, "SELECT valeur FROM dw.v_kpi WHERE code = 'CA'")


def test_cube_additif_sur_chaque_axe(dw):
    for axe, niveau in (("niveau", 6), ("region", 5), ("annee_academique", 3)):
        somme = _v(dw, f"SELECT SUM(ca) FROM dw.cube_finance WHERE niveau_agregation = {niveau}")
        assert somme == _v(dw, "SELECT ca FROM dw.cube_finance WHERE niveau_agregation = 7"), axe


def test_recouvrement_par_annee_coherent_avec_le_global(dw):
    ca = _v(dw, "SELECT SUM(ca) FROM dw.v_kpi_annee")
    assert ca == _v(dw, "SELECT valeur FROM dw.v_kpi WHERE code = 'CA'")


def test_pivot_egal_au_cube(dw):
    """Le pivot (FILTER) et le cube (CUBE) donnent le même CA pour Dakar."""
    pivot = _v(dw, """SELECT SUM(p.montant_ca) FROM dw.fact_paiements p JOIN dw.dim_region r ON r.region_key = p.region_key
                      WHERE r.region = 'Dakar'""")
    cube = _v(dw, "SELECT ca FROM dw.cube_finance WHERE region = 'Dakar' AND niveau_agregation = 5")
    assert pivot == cube
