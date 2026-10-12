"""Tests unitaires — porte G6, tests du pipeline de bout en bout (L9, Phase 15). Sans base de données."""
from datetime import datetime
from decimal import Decimal

import pytest

from pipeline import kpi, load_dw, verify_g4, verify_g6
from pipeline.registry import OBJECTS, SOURCES
from pipeline.verify_g6 import (Check, Contexte, attendus_journal, comparer_kpi, compter_familles, derniers_par_cle,
                                equation_conservation, evaluer_chargement, evaluer_couverture, evaluer_extraction,
                                famille_redis, rendre_rapport, resume_par_question)


# ----------------------------------------------------------------- cohérence avec le reste du pipeline --
def test_les_5_questions_du_pdf_et_la_non_regression():
    assert list(verify_g6.QUESTIONS) == ["G6.1", "G6.2", "G6.3", "G6.4", "G6.5", "G6.6"]
    assert len(verify_g6.SECTIONS) == len(verify_g6.QUESTIONS)


def test_reference_kpi_couvre_exactement_les_8_kpi_de_l7():
    assert set(verify_g6.REFERENCE_KPI) == {k.code for k in kpi.KPIS}
    assert set(verify_g6.TOLERANCE_KPI) == set(verify_g6.REFERENCE_KPI)


def test_tolerance_nulle_pour_montants_et_effectifs():
    for k in kpi.KPIS:
        if k.unite in ("XOF", "étudiants", "secondes"):
            assert verify_g6.TOLERANCE_KPI[k.code] == 0, k.code


def test_tables_de_conservation_couvrent_tous_les_objets_non_redis():
    tables = verify_g6._tables_conservation()
    assert len(tables) == 16
    assert {stg for _, _, stg, _ in tables} == {o.stg_table for o in OBJECTS if o.source != "s5_redis"}


def test_cles_des_dimensions_alignees_sur_le_dw():
    assert set(verify_g6.CLES_DIMENSIONS) == set(load_dw.DIMENSIONS)


def test_reutilise_les_listes_de_g4_sans_les_recopier():
    assert set(verify_g4.FK) == set(load_dw.FAITS) == set(verify_g4.SOURCE_CLEAN)
    assert not hasattr(verify_g6, "FK") and not hasattr(verify_g6, "SOURCE_CLEAN")


def test_integrite_clean_garantie_par_des_regles_de_rejet_existantes():
    from pipeline.qualite_regles import REGLES
    rejets = {r.code for r in REGLES if r.action == "REJETE"}
    for libelle, *_, regle in verify_g6.INTEGRITE_CLEAN:
        assert regle in rejets, libelle


# --------------------------------------------------------------------------------------- journal --
def test_attendus_journal_d_un_lot_complet():
    att = attendus_journal()
    assert set(att) == set(verify_g6.ETAPES_JOURNAL)
    assert len(att["EXTRACT"]) == len(att["LOAD"]) == 17
    assert att["TRANSFORM"] == {("TRANSFORM", s, "*") for s in SOURCES}
    assert sum(len(v) for v in att.values()) == 41


def test_derniere_execution_seule_jugee_et_echecs_rattrapes_comptes():
    lignes = [(1, "LOAD", "s1_postgresql", "etudiants", "ECHEC", 0, 1),
              (5, "LOAD", "s1_postgresql", "etudiants", "SUCCES", 10_000, 0),
              (3, "EXTRACT", "s1_postgresql", "etudiants", "SUCCES", 10_000, None)]
    derniers, rattrapes = derniers_par_cle(reversed(lignes))          # ordre d'arrivée quelconque
    assert derniers[("LOAD", "s1_postgresql", "etudiants")] == ("SUCCES", 10_000, 0)
    assert derniers[("EXTRACT", "s1_postgresql", "etudiants")] == ("SUCCES", 10_000, 0)   # NULL -> 0
    assert rattrapes == 1


def test_echec_non_rattrape_reste_visible():
    derniers, rattrapes = derniers_par_cle([(1, "DW", "*", "dw", "SUCCES", 9, 0), (2, "DW", "*", "dw", "ECHEC", None, 1)])
    assert derniers[("DW", "*", "dw")][0] == "ECHEC" and rattrapes == 0


def test_couverture_detecte_absence_et_echec():
    attendus = {("TRANSFORM", s, "*") for s in ("s1_postgresql", "s2_mysql", "s3_csv")}
    derniers = {("TRANSFORM", "s1_postgresql", "*"): ("SUCCES", 1, 0), ("TRANSFORM", "s2_mysql", "*"): ("ECHEC", 0, 1)}
    ok, detail = evaluer_couverture(attendus, derniers)
    assert not ok and "absentes : s3_csv.*" in detail and "s2_mysql.*=ECHEC" in detail
    derniers[("TRANSFORM", "s2_mysql", "*")] = ("SUCCES", 1, 0)
    derniers[("TRANSFORM", "s3_csv", "*")] = ("SUCCES", 1, 0)
    assert evaluer_couverture(attendus, derniers)[0]


# ---------------------------------------------------------------------- Q1 extraction, Q2 chargement --
def test_extraction_ok_et_ecart_source():
    assert evaluer_extraction(40_150, 40_150, ("SUCCES", 40_150, 0))[0]
    ok, detail = evaluer_extraction(40_151, 40_150, ("SUCCES", 40_150, 0))
    assert not ok and "source=40 151" in detail


def test_extraction_journal_absent_ou_en_echec():
    assert not evaluer_extraction(10, 10, None)[0]
    assert not evaluer_extraction(10, 10, ("ECHEC", 0, 1))[0]
    assert not evaluer_extraction(10, None, ("SUCCES", 10, 0))[0]


def test_extraction_redis_jugee_a_l_instant_d_extraction():
    ok, detail = evaluer_extraction(None, 4_608, ("SUCCES", 4_608, 0), volatile=True)
    assert ok and "volatile" in detail
    assert not evaluer_extraction(None, 4_608, ("SUCCES", 4_607, 0), volatile=True)[0]


def test_extraction_sans_recomptage():
    ok, detail = evaluer_extraction(None, 300, ("SUCCES", 300, 0))
    assert ok and "non recomptée" in detail


def test_chargement_ok_puis_lignes_d_un_autre_lot():
    assert evaluer_chargement(126, 126, 126, ("SUCCES", 126, 0))[0]
    ok, detail = evaluer_chargement(126, 130, 126, ("SUCCES", 126, 0))
    assert not ok and "4 ligne(s) d'un autre lot" in detail


def test_chargement_incomplet_ou_journal_en_echec():
    assert not evaluer_chargement(125, 125, 126, ("SUCCES", 126, 0))[0]
    assert not evaluer_chargement(126, 126, 126, ("ECHEC", 126, 1))[0]
    assert not evaluer_chargement(126, 126, 126, None)[0]


# -------------------------------------------------------------------------------- Q3 pertes --
def test_equation_de_conservation():
    ok, detail = equation_conservation(17_557, {"clean": 17_000, "rejetées": 557})
    assert ok and detail == "17 557 = 17 000 clean + 557 rejetées"
    ok, detail = equation_conservation(17_557, {"clean": 17_000, "rejetées": 556})
    assert not ok and "≠" in detail and "écart +1" in detail
    ok, detail = equation_conservation(10, {"clean": 11})
    assert not ok and "écart -1" in detail


@pytest.mark.parametrize("cle, famille", [
    ("session:3f25c89d", "session"), ("last_course:LMS-000154", "last_course"), ("last_quiz:LMS-000154", "last_quiz"),
    ("progress:LMS-000154", "progress"), ("notifications:LMS-000154", "notifications"),
    ("leaderboard:python", "leaderboard"), ("online_users", "compteur"), ("statistics:today", "compteur"),
    ("progress", None), ("cache:xyz", None), ("statistics:yesterday", None)])
def test_familles_redis_du_pdf_source_5(cle, famille):
    assert famille_redis(cle) == famille


def test_compter_familles_signale_les_cles_non_routees():
    comptes, inconnues = compter_familles(["session:a", "session:b", "online_users", "inconnue:1"])
    assert comptes == {"session": 2, "compteur": 1} and inconnues == ["inconnue:1"]


def test_classement_sans_perte():
    ok, detail = verify_g6.evaluer_classement(1_325, 1_325)
    assert ok and "aucune perte silencieuse" in detail


def test_classement_membre_ecarte_est_bloquant():
    """L9-A1 (décision A1-bis) : un membre écarté sans trace fait échouer G6, il n'est plus une information."""
    ok, detail = verify_g6.evaluer_classement(1_325, 1_324)
    assert not ok and "1 écarté(s) SANS trace" in detail


# ------------------------------------------------------------------------- Q6 non-régression --
def test_kpi_identiques_a_la_reference():
    res = comparer_kpi(dict(verify_g6.REFERENCE_KPI))
    assert all(ok for _, ok, _ in res) and len(res) == 8


def test_kpi_montant_exact_au_centime():
    valeurs = dict(verify_g6.REFERENCE_KPI, CA=Decimal("13553901000.01"))
    assert [c for c, ok, _ in comparer_kpi(valeurs) if not ok] == ["CA"]


def test_kpi_ratio_dans_et_hors_tolerance():
    ref = verify_g6.REFERENCE_KPI["RECOUVREMENT"]
    assert all(ok for _, ok, _ in comparer_kpi(dict(verify_g6.REFERENCE_KPI, RECOUVREMENT=ref + Decimal("4e-11"))))
    ko = [c for c, ok, _ in comparer_kpi(dict(verify_g6.REFERENCE_KPI, RECOUVREMENT=ref + Decimal("1e-6"))) if not ok]
    assert ko == ["RECOUVREMENT"]


def test_kpi_valeur_complete_compatible_avec_la_reference_tronquee():
    """La valeur du DW a plus de décimales que la référence transmise : elle doit passer."""
    valeurs = dict(verify_g6.REFERENCE_KPI, PROGRESSION=Decimal("65.588304291234"),
                   REUSSITE=Decimal("0.93128653751234"), CA=Decimal("13553901000.00"))
    assert all(ok for _, ok, _ in comparer_kpi(valeurs))


def test_kpi_absent():
    valeurs = dict(verify_g6.REFERENCE_KPI)
    del valeurs["ETUDIANTS"]
    res = {c: (ok, d) for c, ok, d in comparer_kpi(valeurs)}
    assert not res["ETUDIANTS"][0] and "absent" in res["ETUDIANTS"][1]


# ------------------------------------------------------------- sections avec un curseur simulé --
class FauxCurseur:
    """Curseur minimal : renvoie les lignes prévues pour une requête, ou lève l'erreur prévue."""

    class _Conn:
        autocommit = True

    def __init__(self, lignes=None, erreur=None):
        self.lignes, self.erreur, self.connection, self.requetes = lignes or [], erreur, self._Conn(), []

    def execute(self, sql, params=None):
        self.requetes.append(sql)
        if self.erreur and "v_kpi" in sql:
            raise self.erreur

    def fetchall(self):
        return self.lignes


def _ctx(**kw):
    return Contexte("B20261012T100000", {"objets": {}}, None, **kw)


def test_section_kpi_detecte_une_regression():
    lignes = [(c, v) for c, v in verify_g6.REFERENCE_KPI.items()]
    lignes[0] = ("CA", Decimal("13553900000"))                     # 1 000 XOF de moins
    checks = verify_g6.controles_kpi(FauxCurseur(lignes), _ctx())
    assert [c.libelle for c in checks if not c.ok] == ["KPI CA"]
    assert all(c.code == "G6.6" for c in checks) and len(checks) == 8


def test_section_kpi_vue_absente_ne_plante_pas():
    checks = verify_g6.controles_kpi(FauxCurseur(erreur=RuntimeError("relation dw.v_kpi does not exist")), _ctx())
    assert len(checks) == 8 and not any(c.ok for c in checks) and "--steps kpi" in checks[0].detail


def test_section_erreurs_sur_journal_complet_puis_degrade():
    journal = {k: ("SUCCES", 1, 0) for att in attendus_journal().values() for k in att}
    ctx = _ctx(journal=journal)
    ctx.manifeste = {"objets": {f"{o.source}.{o.objet}": {"nb_lignes": 1} for o in OBJECTS}}
    meta = [(o.source, o.objet, ctx.batch_id, 1, "SUCCES") for o in OBJECTS]
    checks = verify_g6.controles_erreurs(FauxCurseur(meta), ctx)
    assert all(c.ok for c in checks) and len(checks) == 9
    journal[("TRANSFORM", "s4_mongodb", "*")] = ("EN_COURS", None, 0)
    ko = [c.libelle for c in verify_g6.controles_erreurs(FauxCurseur(meta), ctx) if not c.ok]
    assert ko == ["Journal : étape TRANSFORM", "Aucune étape restée EN_COURS (arrêt brutal)"]


def test_section_extraction_source_injoignable_ne_bloque_pas_les_autres():
    ctx = _ctx(journal={("EXTRACT", o.source, o.objet): ("SUCCES", 5, 0) for o in OBJECTS})
    ctx.manifeste = {"objets": {f"{o.source}.{o.objet}": {"nb_lignes": 5} for o in OBJECTS}}

    def recompter(source, objet):
        if source == "s2_mysql":
            raise ConnectionError("MySQL arrêté")
        return 5
    ctx.recompter = recompter
    checks = verify_g6.controles_extraction(None, ctx)
    assert len(checks) == 17
    assert {c.libelle.split()[-1].split(".")[0] for c in checks if not c.ok} == {"s2_mysql"}


# ------------------------------------------------------------------------------------ rapport --
def _checks():
    return [Check("G6.1", "Extraction de s1_postgresql.etudiants", True, "source=10 000"),
            Check("G6.3", "clean -> DW : fact_notes", False, "1 ≠ 0"),
            Check("G6.6", "KPI CA", True, "ok")]


def test_resume_par_question():
    res = {q: (n_ok, n) for q, _, n_ok, n in resume_par_question(_checks())}
    assert res["G6.1"] == (1, 1) and res["G6.3"] == (0, 1) and res["G6.2"] == (0, 0)


def test_rapport_au_format_des_portes():
    md = rendre_rapport(_checks(), "B20261012T100000", datetime(2026, 10, 12, 14, 30))
    assert md.startswith("# Porte G6 — Tests du pipeline de bout en bout, lot B20261012T100000")
    assert "*Rapport du 12/10/2026 14:30*" in md
    assert "**Résultat : NON VALIDÉE** (2/3 contrôles)" in md
    assert "| Contrôle | Libellé | Détail | OK |" in md                # même tableau que G4
    assert "| G6.3 | Des données ont-elles été perdues ? | 0/1 ❌ |" in md
    assert "| G6.2 | Toutes les lignes ont-elles été chargées ? | 0/0 ❌ |" in md   # section vide = échec visible
    md_ok = rendre_rapport([c for c in _checks() if c.ok], "B1")
    assert "**Résultat : VALIDÉE** (2/2 contrôles)" in md_ok
