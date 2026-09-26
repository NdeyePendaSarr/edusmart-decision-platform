"""
Tests unitaires — Source 1 PostgreSQL (générateur + anomalies), SANS base.
La génération complète (10 000 étudiants) est faite une seule fois par module.
"""
import copy
import csv
import hashlib
import re
import uuid
from collections import Counter
from datetime import date

import pytest

from common.config import GenerationConfig
from common.referential import build_referential
from sources.s1_postgresql import anomalies as an
from sources.s1_postgresql import generate_data as g

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module")
def students():
    return build_referential(GEN)


@pytest.fixture(scope="module")
def clean(students):
    pg = [s for s in students if s.statut_correspondance != "LMS_ORPHELIN"]
    return g.generate_clean(pg, GEN)


@pytest.fixture(scope="module")
def generated(students):
    return g.generate(GEN, students)  # (tables, journal, bases)


# --- Données propres ----------------------------------------------------------
def test_donnees_propres_sans_anomalie(clean):
    mesure = an.measure_anomalies(clean, GEN)
    mesure.pop("A07")  # les libellés IA sont dans le catalogue lui-même
    assert mesure == {code: 0 for code in mesure}


def test_colonnes_conformes_au_pdf(clean):
    for table, cols in g.COLUMNS.items():
        assert all(set(cols) <= set(row) for row in clean[table]), table


def test_uuid_v4_et_unicite(clean):
    for table, pk in (("etudiants", "id_etudiant"), ("filieres", "id_filiere"), ("classes", "id_classe"),
                      ("inscriptions", "id_inscription"), ("paiements", "id_paiement")):
        ids = [r[pk] for r in clean[table]]
        assert len(ids) == len(set(ids)), table
        assert all(uuid.UUID(i).version == 4 for i in ids[:200]), table


def test_emails_uniques_et_references_uniques(clean):
    emails = [e["email"] for e in clean["etudiants"]]
    assert len(emails) == len(set(emails))
    refs = [p["reference"] for p in clean["paiements"]]
    assert len(refs) == len(set(refs))


def test_relations_propres(clean):
    fil = {f["id_filiere"] for f in clean["filieres"]}
    cls = {c["id_classe"] for c in clean["classes"]}
    etu = {e["id_etudiant"] for e in clean["etudiants"]}
    ins = {i["id_inscription"] for i in clean["inscriptions"]}
    assert all(c["id_filiere"] in fil for c in clean["classes"])
    assert all(i["id_classe"] in cls and i["id_etudiant"] in etu for i in clean["inscriptions"])
    assert all(p["id_inscription"] in ins for p in clean["paiements"])
    assert {i["id_etudiant"] for i in clean["inscriptions"]} == etu  # chaque étudiant a >= 1 inscription


def test_listes_de_valeurs_validees(clean):
    assert {f["niveau"] for f in clean["filieres"]} <= {"LICENCE", "MASTER", "CERTIFICAT"}
    assert {i["statut"] for i in clean["inscriptions"]} <= {"INSCRIT", "EN_COURS", "DIPLOME", "ABANDON", "SUSPENDU"}
    assert {i["type_inscription"] for i in clean["inscriptions"]} == {"Nouvelle", "Réinscription"}
    assert {p["statut"] for p in clean["paiements"]} <= {"VALIDE", "EN_ATTENTE", "ECHOUE", "REMBOURSE"}
    assert {p["tranche"] for p in clean["paiements"]} <= {"1ERE", "2EME", "3EME"}


def test_regles_metier_propres(clean):
    today = date(2026, 9, 26)
    assert all(e["date_naissance"] < today for e in clean["etudiants"])
    assert all(0 <= i["reduction"] <= 100 for i in clean["inscriptions"])
    assert all(p["montant"] > 0 and p["date_paiement"] <= today for p in clean["paiements"])
    assert all(c["capacite"] > 0 for c in clean["classes"])
    effectifs = Counter(i["id_classe"] for i in clean["inscriptions"])
    assert all(effectifs[c["id_classe"]] <= c["capacite"] for c in clean["classes"])


def test_bourse_totale_sans_paiement(clean):
    payees = {p["id_inscription"] for p in clean["paiements"]}
    for i in clean["inscriptions"]:
        if i["reduction"] == 100:
            assert i["id_inscription"] not in payees


def test_longueurs_varchar(clean):
    assert max(len(c["code_classe"]) for c in clean["classes"]) <= 30
    assert max(len(c["nom_classe"]) for c in clean["classes"]) <= 100
    assert max(len(e["telephone"]) for e in clean["etudiants"]) <= 20
    assert max(len(e["email"]) for e in clean["etudiants"]) <= 150


# --- Anomalies ----------------------------------------------------------------
def test_mesure_egale_journal(generated):
    tables, journal, _ = generated
    assert an.measure_anomalies(tables, GEN) == journal.counts()


def test_seize_types_presents_et_taux(generated):
    _, journal, bases = generated
    counts = journal.counts()
    assert set(counts) == {f"A{i:02d}" for i in range(1, 17)}
    for code, n in counts.items():
        assert n > 0, code
        if code not in an.FIXED_BY_DESIGN:
            assert 0.02 <= n / bases[code] <= 0.05, (code, n, bases[code])


def test_variantes_conformes_au_pdf(generated):
    tables, _, _ = generated
    sexes = {e["sexe"] for e in tables["etudiants"]}
    assert sexes <= {"M", "F", "Homme", "Femme", "Garçon", "Fille", "1", "0"}
    modes = {p["mode_paiement"] for p in tables["paiements"]}
    assert "Orange Money" in modes and modes & {"OM", "orange money"}
    assert {f["nom_filiere"] for f in tables["filieres"]} >= {"IA", "Intelligence Artificielle", "Ingénierie IA"}
    assert all(len(e["sexe"]) <= 10 for e in tables["etudiants"])  # écart VARCHAR(10)


def test_orphelins_pointent_vers_rien(generated):
    tables, journal, _ = generated
    ins = {i["id_inscription"] for i in tables["inscriptions"]}
    orphelins = [r for r in journal.records if r.code == "A16"]
    assert all(r.valeur_injectee not in ins for r in orphelins)


def test_doublons_meme_contenu(generated):
    tables, journal, _ = generated
    par_id = {i["id_inscription"]: i for i in tables["inscriptions"]}
    for r in [r for r in journal.records if r.code == "A10"][:50]:
        copie, origine = par_id[r.id_ligne], par_id[r.valeur_originale]
        assert (copie["id_etudiant"], copie["id_classe"]) == (origine["id_etudiant"], origine["id_classe"])


def test_injection_ne_touche_que_les_lignes_journalisees(clean):
    tables = copy.deepcopy(clean)
    journal, _ = an.inject_anomalies(tables, GEN, g.get_rng("test_injection", seed=1))
    touches = {r.id_ligne for r in journal.records if r.table == "etudiants"}
    avant = {e["id_etudiant"]: e for e in clean["etudiants"]}
    for e in tables["etudiants"]:
        if e["id_etudiant"] not in touches:
            assert e == avant[e["id_etudiant"]]


# --- Volumes et reproductibilité ----------------------------------------------
def test_volumes_dans_la_cible(generated):
    tables, _, _ = generated
    for table, cible in g.TARGETS.items():
        n = len(tables[table])
        if table in ("inscriptions", "paiements"):
            assert abs(n - cible) <= g.TOLERANCE * cible, (table, n)
        else:
            assert n == cible, table


def test_reproductibilite_octet_pour_octet(students, tmp_path):
    empreintes = []
    for run in ("a", "b"):
        tables, _, _ = g.generate(GEN, students)
        g.write_tables(tables, tmp_path / run)
        empreintes.append({t: hashlib.md5((tmp_path / run / f"{t}.csv").read_bytes()).hexdigest()
                           for t in g.TABLE_ORDER})
    assert empreintes[0] == empreintes[1]


def test_csv_null_et_booleens(generated, tmp_path):
    tables, _, _ = generated
    g.write_tables(tables, tmp_path)
    with (tmp_path / "etudiants.csv").open(encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert sum(1 for r in rows if r["telephone"] == "") == sum(1 for e in tables["etudiants"] if e["telephone"] is None)
    with (tmp_path / "inscriptions.csv").open(encoding="utf-8") as h:
        assert {r["bourse"] for r in csv.DictReader(h)} <= {"true", "false"}


def test_rentree_depuis_code_classe():
    assert an.rentree_depuis_code_classe("LIC-GL-2324-A", GEN) == date(2023, 10, 1)
    with pytest.raises(ValueError):
        an.rentree_depuis_code_classe("INCONNU", GEN)
