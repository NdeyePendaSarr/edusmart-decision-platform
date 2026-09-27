"""
Test d'intégration — pipeline L4 complet sur les VRAIES bases (5 sources + DW).
Désactivé par défaut. Pour l'exécuter (conteneurs démarrés, 5 sources chargées) :
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_pipeline_integration.py -v
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def dw():
    import psycopg2
    from common.config import get_settings
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    conn.autocommit = True
    yield conn
    conn.close()


def test_pipeline_complet_porte_g2():
    from sources.s5_redis import insert_data as redis_insert
    from pipeline.run_pipeline import main
    assert redis_insert.main() == 0          # snapshot Redis régénéré juste avant l'extraction
    assert main([]) == 0


def test_rechargement_idempotent(dw):
    from pipeline.run_pipeline import main
    with dw.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM staging.stg_mysql_notes")
        avant = cur.fetchone()[0]
    assert main(["--steps", "load", "verify"]) == 0
    with dw.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM staging.stg_mysql_notes")
        assert cur.fetchone()[0] == avant                           # rien n'est dupliqué


def test_journal_complet(dw):
    with dw.cursor() as cur:
        cur.execute("""SELECT etape, COUNT(*) FROM meta.etl_execution_log
                       WHERE batch_id = (SELECT MAX(batch_id) FROM meta.etl_execution_log) AND statut = 'SUCCES'
                       GROUP BY etape""")
        par_etape = dict(cur.fetchall())
    assert par_etape.get("EXTRACT") == 17 and par_etape.get("LOAD", 0) >= 17
