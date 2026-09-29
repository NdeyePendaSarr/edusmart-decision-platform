"""Tests unitaires — Power BI (L8) : cohérence du DAX avec le DW, porte G5b, guide. Sans base."""
import re
from decimal import Decimal as D
from pathlib import Path

import pytest

from pipeline import verify_g4
from scripts import verifier_g5b as g5b

RACINE = Path(__file__).resolve().parent.parent
DAX = (RACINE / "powerbi" / "mesures_kpi.dax").read_text(encoding="utf-8")
GUIDE = (RACINE / "powerbi" / "guide_powerbi.md").read_text(encoding="utf-8")
CODE_DAX = "\n".join(l.split("//")[0] for l in DAX.splitlines())          # sans commentaires


def _colonnes_dw() -> dict[str, set[str]]:
    tables = {}
    for f in ("01_dimensions.sql", "02_faits.sql"):
        ddl = (RACINE / "pipeline" / "sql" / "dw" / f).read_text(encoding="utf-8")
        for nom, corps in re.findall(r"CREATE TABLE IF NOT EXISTS dw\.(\w+) \((.*?)\n\);", ddl, re.S):
            tables[nom] = {m.group(1) for l in corps.splitlines() if (m := re.match(r"\s{4}([a-z_]+)\s", l))
                           and m.group(1) != "constraint"}
    return tables


def test_chaque_reference_table_colonne_existe_dans_le_dw():
    tables = _colonnes_dw()
    refs = set(re.findall(r"\b([a-z_]+)\[([a-z_]+)\]", CODE_DAX))
    assert refs, "aucune référence trouvée"
    for table, colonne in refs:
        assert table in tables, f"table inconnue : {table}"
        assert colonne in tables[table], f"colonne inconnue : {table}[{colonne}]"


def test_chaque_mesure_citee_est_definie():
    definies = {m.strip() for m in re.findall(r"^([^\s/][^=\n]*?) =", CODE_DAX, re.M)}
    citees = set(re.findall(r"(?<![\w\]])\[([^\]]+)\]", CODE_DAX))
    assert citees <= definies, citees - definies


def test_les_8_kpi_ont_leur_mesure_et_la_satisfaction_reste_non_mesuree():
    definies = {m.strip() for m in re.findall(r"^([^\s/][^=\n]*?) =", CODE_DAX, re.M)}
    assert set(g5b.MESURES.values()) <= definies
    assert re.search(r'^Satisfaction = "Non mesurée', CODE_DAX, re.M)


# --- Porte G5b ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("texte,attendu", [("13 553 901 000,00", D("13553901000.00")), ("0,901016", D("0.901016")),
                                           ("1740", D("1740")), ("13,553,901,000.00", D("13553901000.00")),
                                           ("65.588304", D("65.588304")), ("\u202f10\u202f500", D("10500")), ("", None)])
def test_lecture_des_valeurs_recopiees(texte, attendu):
    assert g5b.lire_nombre(texte) == attendu


def test_pourcentage_refuse():
    with pytest.raises(ValueError, match="pourcentage"):
        g5b.lire_nombre("90,10 %")


def test_tolerances_g5b():
    ref = {"CA": D("13553901000.00"), "RECOUVREMENT": D("0.9010161429"), "REUSSITE": D("0.9312865374"),
           "ABANDON": D("0.0624163806"), "PROGRESSION": D("65.588304290"), "ACTIFS_30J": D(3003),
           "CONNEXION_MEDIANE": D(1740), "ETUDIANTS": D(10500)}
    saisie = {"CA": D("13553901000"), "RECOUVREMENT": D("0.901016"), "REUSSITE": D("0.931287"),
              "ABANDON": D("0.062416"), "PROGRESSION": D("65.588304"), "ACTIFS_30J": D(3003),
              "CONNEXION_MEDIANE": D(1740), "ETUDIANTS": D(10500)}
    assert all(r[4] for r in g5b.comparer(ref, saisie))
    saisie["ACTIFS_30J"] = D(3002)                                   # un effectif doit être exact
    saisie["RECOUVREMENT"] = D("0.9011")                             # 6 décimales exigées
    ko = {r[0] for r in g5b.comparer(ref, saisie) if not r[4]}
    assert ko == {"ACTIFS_30J", "RECOUVREMENT"}


def test_modele_de_saisie_a_l_aveugle(tmp_path, monkeypatch):
    monkeypatch.setattr(g5b, "MODELE", tmp_path / "g5b.csv")
    contenu = Path(g5b.ecrire_modele()).read_text(encoding="utf-8")
    assert "13553901000" not in contenu and contenu.count("\n") == 9       # en-tête + 8 KPI, sans valeur attendue


# --- Guide ------------------------------------------------------------------------------------------------
def test_guide_coherent_avec_le_modele():
    assert sum(len(v) for v in verify_g4.FK.values()) == 26 and "26 relations" in GUIDE
    assert "`dim_quiz[module_key]` → `dim_module`" in GUIDE and "`dim_etudiant[region_key]` → `dim_region`" in GUIDE
    assert "date_key` ≠ **-1**" in GUIDE
    assert "dim_formation[annee_academique]" in GUIDE and "dim_temps[annee_academique]" in GUIDE


def test_les_cinq_graphiques_de_la_phase_12():
    from scripts import visualisations as v
    for f in ("histogramme", "boxplot", "scatterplot", "heatmap", "barplot"):
        assert callable(getattr(v, f))
