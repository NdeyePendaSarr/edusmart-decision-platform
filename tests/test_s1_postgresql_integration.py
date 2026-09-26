"""
Test d'intégration — Source 1 sur une VRAIE base PostgreSQL.
Désactivé par défaut. Pour l'exécuter (conteneurs démarrés, docker/.env rempli) :
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s1_postgresql_integration.py
ATTENTION : recharge entièrement la base edusmart_academic.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def loaded():
    from common.referential import main as build_ref
    from sources.s1_postgresql import generate_data, insert_data
    assert build_ref() == 0
    assert generate_data.main() == 0
    assert insert_data.main([]) == 0


def test_porte_g1(loaded):
    from sources.s1_postgresql import verify_source
    assert verify_source.main() == 0


def test_rechargement_idempotent(loaded):
    from sources.s1_postgresql import insert_data, verify_source
    assert insert_data.main([]) == 0
    assert verify_source.main() == 0


def test_not_valid_bloque_les_nouvelles_lignes(loaded):
    import psycopg2
    from common.config import get_settings
    conn = psycopg2.connect(**get_settings().pg_source.connect_kwargs())
    try:
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("""INSERT INTO paiements (id_inscription, reference, date_paiement, montant,
                           mode_paiement, tranche)
                           SELECT id_inscription, 'TEST', CURRENT_DATE, -1, 'Wave', '1ERE'
                           FROM inscriptions LIMIT 1""")
    finally:
        conn.rollback()
        conn.close()
