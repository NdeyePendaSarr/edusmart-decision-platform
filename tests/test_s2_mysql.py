"""
Tests unitaires — Source 2 MySQL (générateur + anomalies), SANS base.
Génération complète (9 500 comptes) faite une fois par module (~15 s).
"""
import csv
import hashlib
import re
import uuid
from collections import Counter
from datetime import datetime, time, timedelta

import pytest

from common.config import GenerationConfig
from common.learning_catalog import APPAREILS, CATEGORIES
from common.referential import build_referential
from sources.s2_mysql import anomalies as an
from sources.s2_mysql import generate_data as g
from sources.s2_mysql.insert_data import _split_sql

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module")
def students():
    return build_referential(GEN)


@pytest.fixture(scope="module")
def clean(students):
    return g.generate_clean(GEN, students)  # (tables, codes, profils)


@pytest.fixture(scope="module")
def generated(students):
    return g.generate(GEN, students)        # (tables, journal, bases, codes)


# --- Données propres ----------------------------------------------------------
def test_donnees_propres_sans_anomalie(clean):
    tables, _, _ = clean
    assert an.measure_anomalies(tables) == {code: 0 for code in an.ANOMALY_TYPES}


def test_colonnes_et_uuid(clean):
    tables, _, _ = clean
    pks = {"modules": "id_module", "cours": "id_cours", "quiz": "id_quiz", "notes": "id_note",
           "progression": "id_progression", "temps_connexion": "id_connexion"}
    for table, pk in pks.items():
        assert all(set(g.COLUMNS[table]) <= set(r) for r in tables[table]), table
        ids = [r[pk] for r in tables[table]]
        assert len(ids) == len(set(ids)), table
        assert all(uuid.UUID(i).version == 4 for i in ids[:100]), table


def test_listes_de_valeurs(clean):
    tables, _, _ = clean
    assert {m["categorie"] for m in tables["modules"]} == set(CATEGORIES)
    assert {m["niveau"] for m in tables["modules"]} == {"DEBUTANT", "INTERMEDIAIRE", "AVANCE"}
    assert {c["type_cours"] for c in tables["cours"]} <= {"Vidéo", "PDF", "TP", "Projet"}
    assert {c["appareil"] for c in tables["temps_connexion"]} == set(APPAREILS)
    assert all(re.fullmatch(r"MOD-[A-Z]+-\d{2}", m["code_module"]) for m in tables["modules"])


def test_regles_metier_propres(clean):
    tables, _, _ = clean
    smax = {q["id_quiz"]: q["score_max"] for q in tables["quiz"]}
    for n in tables["notes"]:
        assert 0 <= n["score"] <= smax[n["id_quiz"]]
        assert n["valide"] == (n["score"] >= 0.5 * smax[n["id_quiz"]])
        assert n["tentative"] >= 1
    assert all(0 <= p["pourcentage"] <= 100 for p in tables["progression"])
    for c in tables["temps_connexion"]:
        assert c["duree_minutes"] > 0 and c["date_deconnexion"] > c["date_connexion"]


def test_aucune_activite_apres_la_date_de_reference(clean):
    tables, _, _ = clean
    limite = datetime.combine(GEN.date_reference, time(23, 59, 59))
    assert max(n["date_passage"] for n in tables["notes"]) <= limite
    assert max(c["date_connexion"] for c in tables["temps_connexion"]) <= limite


def test_activite_dans_la_fenetre_de_chaque_etudiant(clean):
    tables, _, profils = clean
    fenetre = {p.student_code: p for p in profils}
    for n in tables["notes"][::50]:
        p = fenetre[n["student_code"]]
        assert datetime.combine(p.debut, time.min) <= n["date_passage"]
        assert n["date_passage"].date() <= max(p.fin, p.debut + timedelta(days=30))


def test_population_lms(clean, students):
    tables, _, _ = clean
    lms = {s.student_code for s in students if s.student_code}
    codes = {r["student_code"] for t in ("notes", "progression", "temps_connexion") for r in tables[t]}
    assert codes == lms and len(lms) == 9_500
    assert {p["student_code"] for p in tables["progression"]} == lms


def test_filiere_oriente_les_modules(clean):
    tables, _, profils = clean
    cat_module = {m["id_module"]: m["categorie"] for m in tables["modules"]}
    pref = {p.student_code: p.categorie_preferee for p in profils}
    dans_pref = sum(1 for p in tables["progression"] if cat_module[p["id_module"]] == pref[p["student_code"]])
    assert dans_pref / len(tables["progression"]) > 0.65


def test_relations_propres(clean):
    tables, _, _ = clean
    mods = {m["id_module"] for m in tables["modules"]}
    crs = {c["id_cours"] for c in tables["cours"]}
    qz = {q["id_quiz"] for q in tables["quiz"]}
    assert all(c["id_module"] in mods for c in tables["cours"])
    assert all(q["id_cours"] in crs for q in tables["quiz"])
    assert all(n["id_quiz"] in qz for n in tables["notes"])
    assert all(p["id_module"] in mods for p in tables["progression"])
    assert all(p["dernier_cours"] is None or p["dernier_cours"] in crs for p in tables["progression"])


# --- Codes et mapping -----------------------------------------------------------
def test_codes_externes(clean):
    tables, codes, _ = clean
    par_type = Counter(c["type_objet"] for c in codes)
    assert par_type == {"MODULE": 300, "COURSE": len(tables["cours"]), "QUIZ": len(tables["quiz"])}
    assert len({c["code_externe"] for c in codes}) == len(codes)
    for t in ("COURSE", "QUIZ"):
        lot = [c for c in codes if c["type_objet"] == t]
        absents = sum(1 for c in lot if not c["dans_mapping"])
        assert absents == round(0.05 * len(lot))
        assert [c["code_externe"] for c in lot] == [f"{t}-{n}" for n in range(1, len(lot) + 1)]
    assert all(c["dans_mapping"] for c in codes if c["type_objet"] == "MODULE")


def test_ecriture_mapping(clean, tmp_path):
    _, codes, _ = clean
    total, livres = g.write_codes(codes, tmp_path / "m", tmp_path / "r")
    with (tmp_path / "m" / "mapping_courses.csv").open(encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert len(rows) == livres < total
    assert {r["statut_correspondance"] for r in rows} == {"APPARIE"}


# --- Anomalies ------------------------------------------------------------------
def test_mesure_egale_journal(generated):
    tables, journal, _, _ = generated
    assert an.measure_anomalies(tables) == journal.counts()


def test_seize_types_et_taux(generated):
    _, journal, bases, _ = generated
    counts = journal.counts()
    assert set(counts) == {f"B{i:02d}" for i in range(1, 17)}
    for code, n in counts.items():
        assert 0.02 <= n / bases[code] <= 0.05, (code, n, bases[code])


def test_exemples_du_pdf_presents(generated):
    tables, _, _, _ = generated
    assert {"DATA", "data science"} <= {m["categorie"] for m in tables["modules"]}
    assert {"mobile", "Téléphone"} <= {c["appareil"] for c in tables["temps_connexion"]}
    assert any(p["pourcentage"] > 100 for p in tables["progression"])
    assert any(p["pourcentage"] < 0 for p in tables["progression"])


def test_volumes_dans_la_cible(generated):
    tables, _, _, _ = generated
    for table, cible in g.TARGETS.items():
        n = len(tables[table])
        if table in g.EXACT_TARGETS:
            assert n == cible
        else:
            assert abs(n - cible) <= g.TOLERANCE * cible, (table, n)


@pytest.mark.parametrize("valeur,invalide", [("197.210.15.24", False), ("2001:db8::1", False),
                                             ("256.1.1.1", True), ("10.0.1", True), ("abc", True),
                                             ("2001:db8::zz", True), (None, False)])
def test_ip_invalide(valeur, invalide):
    assert an.ip_invalide(valeur) is invalide


@pytest.mark.parametrize("duree,nb,incoherent", [(15, 10, False), (0, 10, True), (1, 20, True),
                                                 (400, 10, True), (5, 5, False)])
def test_duree_quiz(duree, nb, incoherent):
    assert an.quiz_duree_incoherente(duree, nb) is incoherent


# --- CSV, SQL, reproductibilité ---------------------------------------------------
def test_csv_format_load_data(generated, tmp_path):
    tables, _, _, _ = generated
    g.write_tables(tables, tmp_path)
    brut = (tmp_path / "temps_connexion.csv").read_bytes()
    assert b"\r\n" not in brut                      # LINES TERMINATED BY '\n'
    with (tmp_path / "temps_connexion.csv").open(encoding="utf-8", newline="") as h:
        rows = list(csv.DictReader(h))
    assert sum(1 for r in rows if r["navigateur"] == g.NULL) == sum(1 for c in tables["temps_connexion"]
                                                                      if c["navigateur"] is None)
    with (tmp_path / "modules.csv").open(encoding="utf-8", newline="") as h:
        assert {r["actif"] for r in csv.DictReader(h)} == {"0", "1"}


def test_decoupage_sql():
    statements = _split_sql(g.Path(g.__file__).with_name("create_database.sql").read_text(encoding="utf-8"))
    assert len(statements) == 18
    assert sum(s.startswith("CREATE TABLE") for s in statements) == 6
    assert all(s.count("'") % 2 == 0 for s in statements)  # aucune chaîne coupée par un ';'


def test_reproductibilite(students, tmp_path):
    echantillon = students[:600]
    empreintes = []
    for run in ("a", "b"):
        tables, _, _, codes = g.generate(GEN, echantillon)
        g.write_tables(tables, tmp_path / run)
        empreintes.append({t: hashlib.md5((tmp_path / run / f"{t}.csv").read_bytes()).hexdigest()
                           for t in g.TABLE_ORDER})
    assert empreintes[0] == empreintes[1]
