"""Tests unitaires — KPI et OLAP (L7). Sans base : recalculs, fiches, SQL et DAX."""
import re
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from pipeline import kpi, olap

RACINE = Path(kpi.__file__).resolve().parent.parent
SQL_KPI = (RACINE / "pipeline" / "sql" / "olap" / "10_kpi.sql").read_text(encoding="utf-8")
DAX = (RACINE / "powerbi" / "mesures_kpi.dax").read_text(encoding="utf-8")


# --- Recalculs indépendants (cas limites) ---------------------------------------------------------
def test_ca_exclut_negatifs_non_valides_et_orphelins():
    paiements = [("VALIDE", D("100.00"), True), ("VALIDE", D("-50.00"), True), ("ECHOUE", D("70.00"), True),
                 ("VALIDE", D("30.00"), False), ("VALIDE", D("0.00"), True), ("REMBOURSE", D("10.00"), True)]
    assert kpi.calc_ca(paiements) == D("100.00")


def test_montant_du_frais_annuels_et_arrondi():
    # Licence : 3 ans ; 1 000 000 / 3 = 333 333,33 ; réduction 25 % -> 250 000,00 (arrondi au centime)
    assert kpi.calc_montant_du([(D("1000000"), "LICENCE", D("25"))]) == D("250000.00")
    assert kpi.calc_montant_du([(D("900000"), "MASTER", None)]) == D("450000.00")        # réduction neutralisée
    assert kpi.calc_montant_du([(D("500000"), "CERTIFICAT", D("0"))]) == D("500000.00")


def test_reussite_par_couple_et_non_par_tentative():
    notes = [("e1", "q1", False), ("e1", "q1", True),      # échoue puis réussit : 1 couple validé
             ("e1", "q2", False), ("e2", "q1", True)]
    assert kpi.calc_reussite(notes) == D(2) / D(3)


def test_abandon_et_progression():
    assert kpi.calc_abandon(["ABANDON", "INSCRIT", "SUSPENDU", "DIPLOME"]) == D("0.25")
    assert kpi.calc_progression([D("100"), None, D("50")]) == D("75")                  # NULL ignoré


def test_actifs_fenetre_de_30_jours_inclus():
    ref = date(2026, 9, 15)
    activites = [("a", date(2026, 8, 17)),       # 1er jour de la fenêtre : compté
                 ("b", date(2026, 8, 16)),       # la veille : exclu
                 ("c", ref), ("c", date(2026, 9, 1)),   # compté une fois
                 ("d", date(2026, 9, 16)),       # après la référence : exclu
                 (None, ref)]
    assert kpi.calc_actifs(activites, ref) == 2


def test_mediane_nombre_pair_et_nuls():
    assert kpi.calc_mediane([60, None, 120, 180, 240]) == D("150")                     # comme MEDIAN en DAX
    assert kpi.calc_mediane([1740]) == D("1740")


def test_comparaison_tolerances():
    sql = {k.code: D(1) for k in kpi.KPIS}
    py = dict(sql)
    py["REUSSITE"] = D(1) + D("1e-12")            # ratio : écart infime toléré
    assert all(ok for _, ok, _, _ in kpi.comparer(sql, py))
    py["CA"] = D("1.01")                          # montant : aucune tolérance
    assert not dict((c, ok) for c, ok, _, _ in kpi.comparer(sql, py))["CA"]


# --- Fiches, SQL et DAX cohérents ------------------------------------------------------------------
def test_huit_fiches_completes():
    assert len(kpi.KPIS) == 8 and len({k.code for k in kpi.KPIS}) == 8
    for k in kpi.KPIS:
        for champ in ("definition", "formule", "sources", "frequence", "cible", "decideur", "justification", "limites"):
            assert getattr(k, champ).strip(), (k.code, champ)
    assert kpi.KPI_NON_CALCULABLE["code"] == "SATISFACTION"


def test_vue_sql_couvre_les_8_kpi():
    codes_sql = set(re.findall(r"'([A-Z_0-9]+)' AS code|SELECT \d+, '([A-Z_0-9]+)'", SQL_KPI))
    assert {a or b for a, b in codes_sql} == {k.code for k in kpi.KPIS}


@pytest.mark.parametrize("mesure", ["CA encaissé", "Taux de recouvrement", "Taux de réussite", "Taux d'abandon",
                                    "Progression moyenne", "Étudiants actifs (30 j)", "Temps médian de connexion (s)",
                                    "Nombre réel d'étudiants"])
def test_une_mesure_dax_par_kpi(mesure):
    assert re.search(rf"^{re.escape(mesure)} =", DAX, re.M)


def test_date_de_reference_identique_partout():
    assert kpi.DATE_REFERENCE == date(2026, 9, 15)
    assert "DATE '2026-09-15'" in SQL_KPI and "DATE ( 2026, 9, 15 )" in DAX


# --- OLAP ----------------------------------------------------------------------------------------------
def test_les_six_operations_olap():
    assert list(olap.OPERATIONS.values()) == ["Cube", "Roll up", "Drill down", "Slice", "Dice", "Pivot"]
    textes = {f: (olap.SQL_OLAP / f).read_text(encoding="utf-8") for f in olap.OPERATIONS}
    assert "GROUP BY CUBE" in textes["01_cube.sql"] and "GROUP BY ROLLUP" in textes["02_roll_up.sql"]
    assert "FILTER (WHERE" in textes["06_pivot.sql"]
    for f, t in textes.items():
        assert olap.blocs(t), f


def test_decoupage_des_blocs():
    texte = "-- entête\n-- @titre Premier\nSELECT 1;\n-- @titre Second\nDROP TABLE x;\nCREATE TABLE x AS SELECT 2;\n"
    assert olap.blocs(texte) == [("Premier", "SELECT 1"), ("Second", "DROP TABLE x"), ("Second", "CREATE TABLE x AS SELECT 2")]
