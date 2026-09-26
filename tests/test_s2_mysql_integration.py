"""
Test d'intégration — Source 2 sur une VRAIE base MySQL.
Désactivé par défaut. Pour l'exécuter (conteneurs démarrés, docker/.env rempli) :
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s2_mysql_integration.py
ATTENTION : recharge entièrement la base edusmart_learning.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def loaded():
    from common.referential import main as build_ref
    from sources.s2_mysql import generate_data, insert_data
    assert build_ref() == 0
    assert generate_data.main() == 0
    assert insert_data.main([]) == 0


@pytest.fixture
def conn(loaded):
    import pymysql
    from common.config import get_settings
    c = pymysql.connect(**get_settings().mysql.connect_kwargs(), autocommit=False)
    yield c
    c.rollback()
    c.close()


def test_porte_g1(loaded):
    from sources.s2_mysql import verify_source
    assert verify_source.main() == 0


def test_check_actif_rejette(conn):
    """ck_notes_score est ENFORCED : un score négatif est refusé."""
    import pymysql
    with conn.cursor() as cur, pytest.raises(pymysql.err.OperationalError) as exc:
        cur.execute("INSERT INTO notes (id_note, id_quiz, student_code, date_passage, score) "
                    "SELECT UUID(), id_quiz, 'LMS-999999', NOW(), -1 FROM quiz LIMIT 1")
    assert exc.value.args[0] == 3819  # Check constraint is violated


def test_not_enforced_accepte_meme_les_nouvelles_lignes(conn):
    """Différence avec PostgreSQL NOT VALID : NOT ENFORCED ne vérifie rien, même les nouvelles lignes."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO temps_connexion (id_connexion, student_code, date_connexion, duree_minutes) "
                    "VALUES (UUID(), 'LMS-999999', NOW(), -5)")
        assert cur.rowcount == 1   # accepté ; annulé par le rollback de la fixture


def test_fk_rejette_les_nouveaux_orphelins(conn):
    """Après le chargement, FOREIGN_KEY_CHECKS = 1 : une progression sur un module inexistant est refusée."""
    import pymysql
    with conn.cursor() as cur, pytest.raises(pymysql.err.IntegrityError):
        cur.execute("INSERT INTO progression (id_progression, student_code, id_module, pourcentage) "
                    "VALUES (UUID(), 'LMS-999999', 'module-inexistant', 50)")


def test_rechargement_idempotent(loaded):
    from sources.s2_mysql import insert_data, verify_source
    assert insert_data.main([]) == 0
    assert verify_source.main() == 0
