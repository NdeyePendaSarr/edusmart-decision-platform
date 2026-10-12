"""
Test d'intégration — pipeline complet sur les VRAIES bases (5 sources + DW), porte G6 et tests de mutation.
Désactivé par défaut. Pour l'exécuter (conteneurs démarrés, 5 sources chargées) :
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_pipeline_integration.py -v

Ordre d'exécution (celui du fichier) :
    1. L4 : pipeline complet (nouveau lot), rechargement idempotent, journal ;
    2. L9 : porte G6 complète sur le lot qui vient d'être produit (Phase 15 : 5 questions + non-régression) ;
    3. L9 : TESTS DE MUTATION. Un test qui ne peut pas échouer ne prouve rien : on casse volontairement
            une donnée (ligne perdue, clé orpheline, erreur au journal, KPI faussé...) DANS UNE TRANSACTION,
            et G6 doit passer au rouge. La transaction est ensuite ANNULÉE (ROLLBACK) : aucune donnée
            n'est modifiée durablement ;
    4. L9 : contre-épreuve : après les mutations, G6 est de nouveau verte (rien n'a été validé par erreur).
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


def _connexion(autocommit: bool):
    import psycopg2
    from common.config import get_settings
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    conn.autocommit = autocommit
    return conn


@pytest.fixture(scope="module")
def dw():
    conn = _connexion(autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def transaction():
    """Connexion en transaction : tout ce que le test modifie est annulé à la fin, quoi qu'il arrive."""
    conn = _connexion(autocommit=False)
    yield conn
    conn.rollback()
    conn.close()


# =============================================================================
# 1. Pipeline complet (L4)
# =============================================================================
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


# =============================================================================
# 2. Porte G6 complète (L9, Phase 15)
# =============================================================================
def test_porte_g6(dw):
    """Les 6 sections, sources recomptées : 101 contrôles, tous verts, rapport écrit."""
    from pipeline import verify_g6
    from pipeline.verify_g2 import compter_source
    ctx = verify_g6.contexte(dw, recompter=compter_source)
    checks = verify_g6.verify(dw, ctx)
    ko = [(c.code, c.libelle, c.detail) for c in checks if not c.ok]
    assert not ko, ko
    assert len(checks) == 101
    assert {c.code for c in checks} == set(verify_g6.QUESTIONS)
    rapport = verify_g6.write_report(checks, ctx.batch_id)
    with open(rapport, encoding="utf-8") as fichier:
        assert "**Résultat : VALIDÉE** (101/101 contrôles)" in fichier.read()


def test_porte_g6_en_ligne_de_commande():
    from pipeline import verify_g6
    assert verify_g6.main(["--sans-recomptage"]) == 0


# =============================================================================
# 3. Tests de mutation : G6 doit DÉTECTER chaque défaut introduit (transaction annulée)
# =============================================================================
MUTATIONS = {
    # Q2 « toutes les lignes ont-elles été chargées ? » : une ligne disparaît du staging
    "Q2_ligne_staging_perdue": (
        "DELETE FROM staging.stg_pg_filieres WHERE _row_number = (SELECT MIN(_row_number) FROM staging.stg_pg_filieres)",
        "controles_chargement", "Chargement de s1_postgresql.filieres -> staging.stg_pg_filieres"),
    # Q3 « des données ont-elles été perdues ? » : une ligne disparaît entre clean et DW
    "Q3_ligne_dw_perdue": (
        "DELETE FROM dw.fact_notes WHERE id_note = (SELECT id_note FROM dw.fact_notes LIMIT 1)",
        "controles_pertes", "clean -> DW : fact_notes"),
    # Q3 : une ligne disparaît entre staging et clean, sans rejet tracé
    "Q3_ligne_clean_perdue": (
        "DELETE FROM clean.paiements WHERE id_paiement = (SELECT id_paiement FROM clean.paiements LIMIT 1)",
        "controles_pertes", "staging -> clean + rejets : s1_postgresql.paiements"),
    # Q3 : une ligne rejetée deux fois (le rapport qualité surestimerait les rejets)
    "Q3_rejet_en_double": (
        """INSERT INTO quality.rejets (batch_id, code_regle, code_source, table_source, id_ligne, rang, motif, ligne)
           SELECT batch_id, code_regle, code_source, table_source, id_ligne, rang, motif, ligne FROM quality.rejets
           WHERE batch_id = %(lot)s AND code_source <> 's5_redis' LIMIT 1""",
        "controles_pertes", "Aucune ligne rejetée deux fois (16 tables)"),
    # Q4 « des erreurs sont-elles apparues ? » : la dernière exécution d'une étape est en échec
    "Q4_etape_en_echec": (
        """INSERT INTO meta.etl_execution_log (batch_id, etape, code_source, objet, date_debut, date_fin, nb_lignes,
                                               nb_erreurs, erreurs, statut, version_pipeline)
           VALUES (%(lot)s, 'TRANSFORM', 's2_mysql', '*', now(), now(), 0, 1, 'Mutation G6', 'ECHEC', 'test')""",
        "controles_erreurs", "Journal : étape TRANSFORM"),
    # Q5 « les clés sont-elles toujours valides ? » : une inscription disparaît, ses paiements deviennent orphelins
    "Q5_cle_orpheline": (
        "DELETE FROM clean.inscriptions WHERE id_inscription = (SELECT id_inscription FROM clean.paiements LIMIT 1)",
        "controles_cles", "Intégrité clean : paiements -> inscriptions"),
    # Non-régression : 1 000 XOF de trop sur un seul paiement suffisent à faire échouer le KPI CA
    "NR_kpi_ca_fausse": (
        """UPDATE dw.fact_paiements SET montant_ca = montant_ca + 1000
           WHERE id_paiement = (SELECT id_paiement FROM dw.fact_paiements WHERE montant_ca > 0 LIMIT 1)""",
        "controles_kpi", "KPI CA"),
}


@pytest.mark.parametrize("nom", list(MUTATIONS))
def test_mutation_detectee(transaction, nom):
    from pipeline import verify_g6
    from pipeline.transform import batch_en_staging
    sql, section, attendu = MUTATIONS[nom]
    lot = batch_en_staging(transaction)
    with transaction.cursor() as cur:
        cur.execute(sql, {"lot": lot})
        assert cur.rowcount == 1, f"{nom} : la mutation a touché {cur.rowcount} ligne(s) au lieu d'une"
    ctx = verify_g6.contexte(transaction, batch_id=lot)                    # journal relu APRÈS la mutation
    checks = verify_g6.verify(transaction, ctx, sections=(getattr(verify_g6, section),))
    ko = [c.libelle for c in checks if not c.ok]
    assert attendu in ko, f"{nom} : défaut NON détecté. Contrôles en échec : {ko}"


def test_mutation_extraction_detectee(dw):
    """Q1 « toutes les lignes ont-elles été extraites ? » : la source contient une ligne de plus que le lot."""
    from pipeline import verify_g6
    ctx = verify_g6.contexte(dw)
    reel = {k: v["nb_lignes"] for k, v in ctx.manifeste["objets"].items()}
    ctx.recompter = lambda s, o: reel[f"{s}.{o}"] + (1 if (s, o) == ("s2_mysql", "notes") else 0)
    ko = [c.libelle for c in verify_g6.verify(dw, ctx, sections=(verify_g6.controles_extraction,)) if not c.ok]
    assert ko == ["Extraction de s2_mysql.notes"]


# =============================================================================
# 4. Contre-épreuve : les mutations ont bien été annulées
# =============================================================================
def test_mutations_annulees(dw):
    from pipeline import verify_g6
    checks = verify_g6.verify(dw, verify_g6.contexte(dw), sections=verify_g6.SECTIONS[1:])
    ko = [(c.code, c.libelle, c.detail) for c in checks if not c.ok]
    assert not ko, ko
