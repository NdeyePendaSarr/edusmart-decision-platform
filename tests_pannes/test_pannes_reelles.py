"""
Pannes réelles : le pipeline est lancé pour de vrai, sur de vraies bases, et chaque panne est provoquée.

Aucune doublure : on lit le résultat dans le code de sortie, le journal meta.etl_execution_log et l'entrepôt.
Ce dossier est hors de `testpaths` : il ne tourne que dans le job « pannes » de .github/workflows/integration.yml.
Chaque test repart d'un lot complet, car une panne laisse volontairement un état incomplet.

    python -m pytest tests_pannes -v      (conteneurs démarrés, 5 sources générées et chargées)
"""
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest
import redis

from common.config import get_settings

RACINE = Path(__file__).resolve().parent.parent
FAUX_ID = "00000000-0000-0000-0000-000000000001"


def lancer(*arguments: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Lance le pipeline dans son propre processus : la configuration y est relue."""
    return subprocess.run([sys.executable, "-m", "pipeline.run_pipeline", *arguments], cwd=RACINE,
                          env={**os.environ, **(env or {})}, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def code_de(resultat: subprocess.CompletedProcess) -> tuple[int, str]:
    return resultat.returncode, resultat.stdout[-1500:]


def client_redis() -> redis.Redis:
    return redis.Redis(**get_settings().redis.connect_kwargs())


@pytest.fixture
def dw():
    """Lot complet et validé, puis connexion à l'entrepôt."""
    charge = subprocess.run([sys.executable, "-m", "sources.s5_redis.insert_data"], cwd=RACINE, check=False)
    assert charge.returncode == 0
    assert code_de(lancer())[0] == 0
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    conn.autocommit = True
    yield conn
    conn.close()


def _val(conn, sql: str, params: tuple = ()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def dernier_lot(conn) -> str:
    return _val(conn, "SELECT MAX(batch_id) FROM meta.etl_execution_log")


def nb_etapes(conn, lot: str, etape: str) -> int:
    return _val(conn, "SELECT COUNT(*) FROM meta.etl_execution_log WHERE batch_id = %s AND etape = %s", (lot, etape))


def dernier_statut(conn, lot: str, etape: str, objet: str) -> str:
    return _val(conn, """SELECT statut FROM meta.etl_execution_log WHERE batch_id = %s AND etape = %s AND objet = %s
                         ORDER BY id_execution DESC LIMIT 1""", (lot, etape, objet))


def lot_en_clean(conn) -> str:
    return _val(conn, "SELECT MAX(_batch_id) FROM clean.paiements")


def test_source_injoignable_arrete_avant_la_couche_clean(dw):
    avant = lot_en_clean(dw)
    code, sortie = code_de(lancer(env={"MYSQL_PORT": "1"}))
    lot = dernier_lot(dw)
    assert code == 1, sortie
    assert lot != avant
    assert _val(dw, """SELECT COUNT(*) FROM meta.etl_execution_log WHERE batch_id = %s AND etape = 'EXTRACT'
                       AND code_source = 's2_mysql' AND statut = 'ECHEC'""", (lot,)) > 0
    assert nb_etapes(dw, lot, "LOAD") > 0                      # les autres sources restent chargées
    assert nb_etapes(dw, lot, "TRANSFORM") == 0
    assert lot_en_clean(dw) == avant


def test_g2_ko_arrete_avant_la_couche_clean(dw):
    avant = lot_en_clean(dw)
    assert code_de(lancer("--steps", "extract"))[0] == 0
    lot = dernier_lot(dw)
    client = client_redis()
    client.set("panne:cle_ajoutee_apres_extraction", "1")      # la source ne correspond plus au lot extrait
    client.close()
    code, sortie = code_de(lancer("--steps", "load", "verify", "transform", "qualite", "dw", "kpi"))
    assert code == 1, sortie
    assert dernier_statut(dw, lot, "VERIFY", "G2") == "ECHEC"
    assert nb_etapes(dw, lot, "TRANSFORM") == 0
    assert lot_en_clean(dw) == avant


def test_g3_ko_arrete_avant_l_entrepot(dw):
    journal = get_settings().paths.anomalies_dir / "s1_postgresql_anomalies.csv"
    original = journal.read_bytes()
    lot = dernier_lot(dw)
    dw_avant = nb_etapes(dw, lot, "DW")
    try:
        journal.write_bytes(original + f"A01,etudiants,email,{FAUX_ID},x,y\r\n".encode())
        code, sortie = code_de(lancer("--steps", "transform", "qualite", "dw", "kpi"))
    finally:
        journal.write_bytes(original)
    assert code == 1, sortie
    assert dernier_statut(dw, lot, "VERIFY", "G3") == "ECHEC"
    assert nb_etapes(dw, lot, "DW") == dw_avant


def test_g4_ko_annule_le_chargement_et_arrete_avant_les_kpi(dw):
    reference = get_settings().paths.reports_dir / "kpi_reference.json"
    date_kpi = reference.stat().st_mtime_ns
    lot = dernier_lot(dw)
    cube = _val(dw, "SELECT COUNT(*) FROM dw.cube_finance")
    identifiant = _val(dw, "SELECT id_etudiant::TEXT FROM clean.etudiants WHERE ville = 'Dakar' ORDER BY matricule LIMIT 1")
    with dw.cursor() as cur:
        # Ce déménagement créerait une version 2 si le chargement était validé
        cur.execute("UPDATE clean.etudiants SET ville = 'Ziguinchor', region = 'Ziguinchor' WHERE id_etudiant::TEXT = %s",
                    (identifiant,))
        # Paiement orphelin : absent de fact_paiements, donc G4.3 échoue
        cur.execute("""CREATE TEMP TABLE orphelin AS SELECT * FROM clean.paiements LIMIT 1;
                       UPDATE orphelin SET id_paiement = %s, id_inscription = %s;
                       INSERT INTO clean.paiements SELECT * FROM orphelin;""", (FAUX_ID, FAUX_ID))
    code, sortie = code_de(lancer("--steps", "dw", "kpi"))
    assert code == 1, sortie
    assert dernier_statut(dw, lot, "DW", "dw") == "ECHEC"
    assert _val(dw, "SELECT COUNT(*) FROM dw.dim_etudiant WHERE etudiant_id = %s AND version > 1", (identifiant,)) == 0
    assert _val(dw, "SELECT ville FROM dw.dim_etudiant WHERE etudiant_id = %s AND est_courant", (identifiant,)) == "Dakar"
    assert _val(dw, "SELECT COUNT(*) FROM dw.cube_finance") == cube
    assert reference.stat().st_mtime_ns == date_kpi


def test_redis_vide_fait_echouer_g3(dw):
    client = client_redis()
    client.flushdb()
    client.close()
    code, sortie = code_de(lancer())
    lot = dernier_lot(dw)
    assert code == 1, sortie
    assert dernier_statut(dw, lot, "VERIFY", "G3") == "ECHEC"
    assert nb_etapes(dw, lot, "DW") == 0


def test_lots_meles_refuses_sans_l_option(dw):
    avant = lot_en_clean(dw)
    code, sortie = code_de(lancer("--sources", "s5_redis"))
    lot = dernier_lot(dw)
    assert code == 1, sortie
    assert lot != avant and nb_etapes(dw, lot, "TRANSFORM") == 0
    assert "--autoriser-lots-mixtes" in sortie


def test_lots_meles_acceptes_avec_l_option(dw):
    code, sortie = code_de(lancer("--sources", "s5_redis", "--autoriser-lots-mixtes"))
    lot = dernier_lot(dw)
    assert code == 0, sortie
    assert nb_etapes(dw, lot, "TRANSFORM") == 5
    assert dernier_statut(dw, lot, "DW", "dw") == "SUCCES"
