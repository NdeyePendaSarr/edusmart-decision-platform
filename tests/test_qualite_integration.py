"""
Test d'intégration — couche clean, rapport qualité et porte G3 sur le VRAI entrepôt.
Prérequis : lot chargé en staging (python -m pipeline.run_pipeline --steps extract load verify).
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_qualite_integration.py -v
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def dw():
    import psycopg2
    from common.config import get_settings
    from pipeline.run_pipeline import main
    assert main(["--steps", "transform", "qualite"]) == 0           # G3 validée
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    conn.autocommit = True
    yield conn
    conn.close()


def _val(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


@pytest.mark.parametrize("expr,attendu", [
    ("clean.date_multi('2024-03-04')", "2024-03-04"), ("clean.date_multi('04/03/2024')", "2024-03-04"),
    ("clean.date_multi('03-04-2024')", "2024-03-04"), ("clean.date_multi('31/02/2024')", None),
    ("clean.telephone('771234567')", "+221 77 123 45 67"), ("clean.telephone('221 771234567')", "+221 77 123 45 67"),
    ("clean.telephone('77 123 45')", None), ("clean.student_code(' lms-154')", "LMS-000154"),
    ("clean.version('v2.4')", "2.4.0"), ("clean.version('2.4.1.0')", "2.4.1"), ("clean.mois('Févr.')", "2"),
    ("clean.annee_academique('23-24')", "2023-2024"), ("clean.salle('Salle B-204')", "B204"),
    ("clean.ville('dakarr')", "Dakar"), ("clean.ville(' THIES ')", "Thiès"), ("clean.ip_valide('256.1.1.1')", "False"),
])
def test_fonctions_sql(dw, expr, attendu):
    v = _val(dw, f"SELECT {expr}")
    assert (None if v is None else str(v)) == attendu


@pytest.mark.parametrize("requete", [
    "SELECT COUNT(*) FROM clean.etudiants WHERE sexe NOT IN ('M', 'F')",
    "SELECT COUNT(*) FROM clean.etudiants WHERE telephone !~ '^\\+221 7[05678] \\d{3} \\d{2} \\d{2}$'",
    "SELECT COUNT(*) FROM clean.progression WHERE pourcentage NOT BETWEEN 0 AND 100",
    "SELECT COUNT(*) - COUNT(DISTINCT (student_code, id_module)) FROM clean.progression",
    "SELECT COUNT(*) FROM clean.notes WHERE student_code !~ '^LMS-\\d{6}$'",
    "SELECT COUNT(*) FROM clean.paiements p WHERE NOT EXISTS (SELECT 1 FROM clean.inscriptions i WHERE i.id_inscription = p.id_inscription)",
    "SELECT COUNT(*) FROM clean.evenements WHERE horodatage IS NULL OR student_code IS NULL",
    "SELECT COUNT(*) FROM clean.salaires WHERE salaire_net < 0",
    "SELECT COUNT(*) FROM clean.redis_compteurs WHERE verifiable AND valeur <> (SELECT valeur FROM clean.redis_compteurs c2 WHERE c2.nom = redis_compteurs.nom)",
])
def test_invariants_de_la_couche_clean(dw, requete):
    assert _val(dw, requete) == 0


def test_retraitement_idempotent(dw):
    from pipeline.run_pipeline import main
    avant = _val(dw, "SELECT COUNT(*) FROM quality.constats WHERE batch_id = (SELECT MAX(batch_id) FROM quality.constats)")
    assert main(["--steps", "transform", "qualite"]) == 0
    apres = _val(dw, "SELECT COUNT(*) FROM quality.constats WHERE batch_id = (SELECT MAX(batch_id) FROM quality.constats)")
    assert avant == apres
