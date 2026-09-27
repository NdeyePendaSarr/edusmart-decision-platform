"""Tests unitaires — qualité L5 (catalogue des règles, SQL, référentiels, porte G3). Sans base."""
import re
from pathlib import Path

from common.academic_catalog import DEPARTEMENTS
from common.anomaly_journal import AnomalyRecord
from common.learning_catalog import APPAREILS, CATEGORIES
from pipeline import qualite_regles as qr
from pipeline.referentiels import SYNONYMES
from pipeline.verify_g3 import evaluer
from sources.s1_postgresql.anomalies import ANOMALY_TYPES as A, MODES_PAIEMENT_CANONIQUES
from sources.s2_mysql.anomalies import ANOMALY_TYPES as B
from sources.s3_csv.anomalies import ANOMALY_TYPES as C, GRADES, MODES_PAIEMENT as MODES_RH, SPECIALITES
from sources.s4_mongodb.anomalies import ANOMALY_TYPES as D
from sources.s5_redis.anomalies import ANOMALY_TYPES as E

SQL_CLEAN = Path(qr.__file__).parent / "sql" / "clean"


# --- Catalogue ------------------------------------------------------------------------
def test_les_69_anomalies_sont_couvertes():
    attendues = set(A) | set(B) | set(C) | set(D) | set(E)
    assert len(attendues) == 69
    assert qr.anomalies_couvertes() == attendues


def test_regles_valides():
    assert len({r.code for r in qr.REGLES}) == len(qr.REGLES)
    for r in qr.REGLES:
        assert r.dimension in qr.DIMENSIONS and r.action in ("CORRIGE", "REJETE", "SIGNALE")


def test_chaque_regle_utilisee_dans_le_sql_et_reciproquement():
    sql = "\n".join(p.read_text(encoding="utf-8") for p in SQL_CLEAN.glob("*.sql"))
    utilisees = set(re.findall(r"quality\.(?:constater|rejeter)\('([A-Z0-9_]+)'", sql))
    assert utilisees == {r.code for r in qr.REGLES}


def test_rejeter_uniquement_pour_les_regles_de_rejet():
    sql = "\n".join(p.read_text(encoding="utf-8") for p in SQL_CLEAN.glob("*.sql"))
    rejets = set(re.findall(r"quality\.rejeter\('([A-Z0-9_]+)'", sql))
    assert rejets == {r.code for r in qr.REGLES if r.action == "REJETE"}


# --- Référentiels cohérents avec les catalogues du volet A -----------------------------------
def test_valeurs_canoniques_des_referentiels():
    assert set(SYNONYMES["categorie_module"]) == set(CATEGORIES)
    assert set(SYNONYMES["appareil"]) == set(APPAREILS)
    assert set(SYNONYMES["specialite"]) == set(SPECIALITES)
    assert set(SYNONYMES["grade"]) == set(GRADES)
    assert set(SYNONYMES["departement"]) == set(DEPARTEMENTS)
    assert set(MODES_PAIEMENT_CANONIQUES) | set(MODES_RH) == set(SYNONYMES["mode_paiement"])
    assert set(SYNONYMES["sexe"]) == {"M", "F"} and set(SYNONYMES["os"]) == {"Android", "iOS"}


def test_chaque_canonique_est_sa_propre_variante():
    for domaine, valeurs in SYNONYMES.items():
        for canonique, variantes in valeurs.items():
            if domaine != "libelle_filiere":
                assert canonique in variantes, (domaine, canonique)


# --- Porte G3 (fonction pure) ------------------------------------------------------------------
def _rec(code, id_ligne, orig=""):
    return AnomalyRecord(code, "t", "c", id_ligne, orig, "")


def test_g3_anomalie_traitee_ou_non():
    journal = [_rec("A01", "e1"), _rec("A01", "e2")]
    res = {r.code: r for r in evaluer(journal, {"PG_SEXE": {"e1": "CORRIGE"}})}
    assert res["A01"].traitees == 1 and not res["A01"].ok
    res = {r.code: r for r in evaluer(journal, {"PG_SEXE": {"e1": "CORRIGE", "e2": "CORRIGE"}})}
    assert res["A01"].ok and res["A01"].par_action == {"CORRIGE": 2}


def test_g3_doublon_nouvel_identifiant():
    """A10 : la copie (nouvel id) OU l'original rejeté suffit à prouver le dédoublonnage."""
    journal = [_rec("A10", "copie", orig="original")]
    res = {r.code: r for r in evaluer(journal, {"PG_INSCRIPTION_DOUBLON": {"original": "REJETE"}})}
    assert res["A10"].ok


def test_g3_regle_d_une_autre_anomalie_ne_compte_pas():
    journal = [_rec("A02", "e1")]
    res = {r.code: r for r in evaluer(journal, {"PG_SEXE": {"e1": "CORRIGE"}})}
    assert not res["A02"].ok


def test_g3_constats_hors_journal():
    journal = [_rec("A13", "p1")]
    res = {r.code: r for r in evaluer(journal, {"PG_REFERENCE_DOUBLON": {"p1": "SIGNALE", "p2": "SIGNALE"}})}
    assert res["A13"].ok and res["A13"].hors_journal == 1
