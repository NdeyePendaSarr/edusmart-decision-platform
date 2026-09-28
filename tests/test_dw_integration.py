"""
Test d'intégration — Data Warehouse (L6) : chargement, porte G4 et cas limites du SCD 2.
Prérequis : couche clean construite (L5). Le schéma dw est RECONSTRUIT (--reset) par ce test.
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_dw_integration.py -v
"""
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def dw():
    import psycopg2
    from common.config import get_settings
    from pipeline import load_dw
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    load_dw.charger(conn, reset=True, effet=date(2026, 9, 20))
    yield conn
    # remise en état : clean reconstruite, DW rechargé sans historique de test
    from pipeline.transform import transform
    conn.rollback()
    transform(["s1_postgresql"])                 # connexion dédiée
    load_dw.charger(conn, reset=True)
    conn.close()


def _v(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def test_porte_g4(dw):
    from pipeline.verify_g4 import verify
    ko = [c for c in verify(dw) if not c.ok]
    assert not ko, ko


def test_scd2_demenagement_puis_scd1_correction(dw):
    from pipeline import load_dw
    ids = [r for (r,) in _q(dw, "SELECT id_etudiant::TEXT FROM clean.etudiants WHERE ville = 'Dakar' ORDER BY matricule LIMIT 3")]
    with dw.cursor() as cur:
        cur.execute("UPDATE clean.etudiants SET ville = 'Ziguinchor', region = 'Ziguinchor' WHERE id_etudiant::TEXT = ANY(%s)", (ids,))
        cur.execute("UPDATE clean.etudiants SET nom = nom || '-Test' WHERE id_etudiant::TEXT = %s", (ids[0],))
    dw.commit()
    load_dw.charger(dw, effet=date(2026, 10, 1))
    assert _v(dw, "SELECT COUNT(*) FROM dw.dim_etudiant WHERE etudiant_id = ANY(%s) AND version = 2 AND est_courant "
                  "AND ville = 'Ziguinchor' AND date_debut = '2026-10-01'", (ids,)) == 3
    assert _v(dw, "SELECT COUNT(*) FROM dw.dim_etudiant WHERE etudiant_id = ANY(%s) AND version = 1 AND NOT est_courant "
                  "AND ville = 'Dakar' AND date_fin = '2026-09-30'", (ids,)) == 3
    # SCD 1 : la correction du nom touche TOUTES les versions
    assert _v(dw, "SELECT COUNT(*) FROM dw.dim_etudiant WHERE etudiant_id = %s AND nom LIKE '%%-Test'", (ids[0],)) == 2
    # Nouveau déménagement LE MÊME JOUR que la version 2 : mise à jour, pas de version vide
    with dw.cursor() as cur:
        cur.execute("UPDATE clean.etudiants SET ville = 'Kolda', region = 'Kolda' WHERE id_etudiant::TEXT = %s", (ids[1],))
    dw.commit()
    load_dw.charger(dw, effet=date(2026, 10, 1))
    assert _v(dw, "SELECT MAX(version) FROM dw.dim_etudiant WHERE etudiant_id = %s", (ids[1],)) == 2
    assert _v(dw, "SELECT ville FROM dw.dim_etudiant WHERE etudiant_id = %s AND est_courant", (ids[1],)) == "Kolda"
    from pipeline.verify_g4 import verify
    assert all(c.ok for c in verify(dw) if c.code in ("G4.1", "G4.2", "G4.5"))


def test_rechargement_sans_changement_idempotent(dw):
    from pipeline import load_dw
    avant = _v(dw, "SELECT COUNT(*) FROM dw.dim_etudiant")
    load_dw.charger(dw, effet=date(2026, 10, 2))
    assert _v(dw, "SELECT COUNT(*) FROM dw.dim_etudiant") == avant


def _q(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()
