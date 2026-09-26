"""Tests unitaires — Source 3 CSV RH (aucune base nécessaire)."""
import csv
import hashlib
import io
from collections import Counter
from datetime import date

import pytest

from common.academic_catalog import build_teacher_pool
from common.config import GenerationConfig
from common.referential import main as build_referential_files
from sources.s3_csv import anomalies as an
from sources.s3_csv import create_source as cs
from sources.s3_csv import generate_data as g
from sources.s3_csv import verify_source as vs

GEN = GenerationConfig(seed=2026)


@pytest.fixture(scope="module", autouse=True)
def referentiel():
    assert build_referential_files() == 0   # le générateur relit le référentiel (responsables de classe)


@pytest.fixture(scope="module")
def clean():
    return g.generate_clean(GEN)            # (tables, variantes)


@pytest.fixture(scope="module")
def generated():
    return g.generate(GEN)                  # (tables, journal, bases)


# --- Données propres ----------------------------------------------------------
def test_donnees_propres(clean):
    tables, _ = clean
    attendu = {code: 0 for code in an.ANOMALY_TYPES}
    attendu["C08"] = 4                       # les 4 lignes « même département, autre écriture »
    assert an.measure_anomalies(tables, g.COLUMNS, GEN) == attendu


def test_vivier_commun(clean):
    tables, _ = clean
    pool = build_teacher_pool(seed=GEN.seed)
    assert [(r["teacher_code"], r["prenom"], r["nom"], r["sexe"]) for r in tables["enseignants"]] == \
           [(t.teacher_code, t.prenom, t.nom, t.sexe) for t in pool]


def test_valeurs_canoniques(clean):
    tables, _ = clean
    ens = tables["enseignants"]
    assert {r["statut"] for r in ens} == {"Permanent", "Vacataire"}
    assert {r["grade"] for r in ens} <= set(an.GRADES) | {None}
    assert all(r["grade"] for r in ens if r["statut"] == "Permanent")
    assert {r["specialite"] for r in ens} == set(an.SPECIALITES)
    assert len({r["email"] for r in ens}) == len(ens)


def test_salaires_propres(clean):
    tables, _ = clean
    embauche = {r["teacher_code"]: date.fromisoformat(r["date_embauche"]) for r in tables["enseignants"]}
    cles = Counter((r["teacher_code"], r["annee"], r["mois"]) for r in tables["salaires"])
    assert max(cles.values()) == 1                                  # un salaire par mois
    for r in tables["salaires"]:
        assert r["salaire_net"] == r["salaire_base"] + r["primes"] - r["retenues"] > 0
        mois = an.MOIS.index(r["mois"]) + 1
        assert (r["annee"], mois) >= (embauche[r["teacher_code"]].year, embauche[r["teacher_code"]].month)
        assert (2023, 10) <= (r["annee"], mois) <= (2026, 8)          # 35 mois (C20)
    assert max(Counter(r["teacher_code"] for r in tables["salaires"]).values()) == 35


def test_absences_propres(clean):
    tables, _ = clean
    embauche = {r["teacher_code"]: date.fromisoformat(r["date_embauche"]) for r in tables["enseignants"]}
    for r in tables["absences"]:
        d = date.fromisoformat(r["date_absence"])
        assert embauche[r["teacher_code"]] <= d <= GEN.date_reference and d.weekday() < 5
        assert 2 <= r["duree_heures"] <= 8 and r["justifiee"] in ("Oui", "Non") and r["remplace"] in ("Oui", "Non")


def test_departements(clean):
    tables, variantes = clean
    dep = tables["departements"]
    assert len(dep) == 12 and len({r["nom_departement"] for r in dep}) == 12      # noms uniques (PDF)
    assert {"Développement Data", "Data Engineering"} <= {r["nom_departement"] for r in dep}
    assert set(variantes.values()) <= {"Data", "Informatique", "Réseaux et Télécommunications"}


# --- Anomalies ------------------------------------------------------------------
def test_mesure_egale_journal(generated):
    tables, journal, _ = generated
    assert an.measure_anomalies(tables, g.COLUMNS, GEN) == journal.counts()


def test_dix_neuf_types_et_taux(generated):
    _, journal, bases = generated
    counts = journal.counts()
    assert set(counts) == {f"C{i:02d}" for i in range(1, 20)}
    for code, n in counts.items():
        assert n > 0, code
        if code not in an.FIXED_BY_DESIGN:
            assert 0.02 <= n / bases[code] <= 0.05, (code, n, bases[code])


def test_exemples_du_pdf(generated):
    tables, _, _ = generated
    assert {"IA", "Data Science"} <= {r["specialite"] for r in tables["enseignants"]}
    assert {"Virement", "Banque", "bank transfer"} <= {r["mode_paiement"] for r in tables["salaires"]}
    formats = Counter(an.parse_date(r["date_absence"])[1] for r in tables["absences"])
    assert set(formats) == {"ISO", "FR", "US"}


def test_doublons_strictement_identiques(generated):
    tables, journal, _ = generated
    for code, table, key in (("C12", "salaires", "id_salaire"), ("C15", "absences", "id_absence")):
        ids = {r.id_ligne for r in journal.records if r.code == code}
        for i in list(ids)[:20]:
            lignes = [tuple(str(x[c]) for c in g.COLUMNS[table]) for x in tables[table] if str(x[key]) == i]
            assert len(lignes) == 2 and lignes[0] == lignes[1]


# --- Fichiers ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def ecrits(generated, tmp_path_factory):
    tables, journal, _ = generated
    out = tmp_path_factory.mktemp("output")
    g.write_files(tables, out)
    return out, journal


def test_encodages_et_separateurs(ecrits):
    out, _ = ecrits
    for key in cs.FILE_ORDER:
        schema, raw = cs.SCHEMAS[key], (out / cs.SCHEMAS[key].nom).read_bytes()
        assert raw.endswith(b"\r\n")
        texte = raw.decode(schema.encodage)
        assert texte.split("\r\n")[0] == schema.separateur.join(schema.entetes)
        if schema.encodage == "iso-8859-1":
            with pytest.raises(UnicodeDecodeError):
                raw.decode("utf-8")                     # l'encodage est réellement différent
            assert "Février" in texte or "Décès" in texte


def test_relecture_fichiers_egale_journal(ecrits):
    out, journal = ecrits
    tables = {k: vs.read_file(k, out)[0] for k in cs.FILE_ORDER}
    assert an.measure_anomalies(tables, g.COLUMNS, GEN) == journal.counts()


def test_controles_format_et_regles(ecrits):
    out, journal = ecrits
    tables, raws = {}, {}
    for k in cs.FILE_ORDER:
        tables[k], raws[k] = vs.read_file(k, out)
    checks = vs.check_format(raws) + vs.check_regles(tables, journal.counts()) + vs.check_inter_sources(tables, GEN)
    assert [c.libelle for c in checks if not c.ok] == []


def test_caractere_hors_iso_refuse(clean, tmp_path):
    tables, _ = clean
    import copy
    t = copy.deepcopy(tables)
    t["absences"][0]["motif"] = "Visite au Sacré-Cœur"   # 'œ' n'existe pas en ISO-8859-1
    with pytest.raises(g.GenerationError):
        g.write_files(t, tmp_path)


def test_reproductibilite(tmp_path):
    empreintes = []
    for run in ("a", "b"):
        tables, _, _ = g.generate(GEN)
        g.write_files(tables, tmp_path / run)
        empreintes.append({k: hashlib.md5((tmp_path / run / cs.SCHEMAS[k].nom).read_bytes()).hexdigest()
                           for k in cs.FILE_ORDER})
    assert empreintes[0] == empreintes[1]


# --- Fonctions de lecture (réutilisables par l'ETL) -------------------------------
@pytest.mark.parametrize("texte,attendu", [
    ("2024-03-04", (date(2024, 3, 4), "ISO")),
    ("04/03/2024", (date(2024, 3, 4), "FR")),     # JJ/MM/AAAA
    ("03-04-2024", (date(2024, 3, 4), "US")),     # MM-JJ-AAAA : même jour, autre convention
    ("31/02/2024", (None, "FR")),
    ("2024/03/04", (None, None)),
    (None, (None, None)),
])
def test_parse_date(texte, attendu):
    assert an.parse_date(texte) == attendu


@pytest.mark.parametrize("texte,attendu", [("Février", 2), ("FEVRIER", 2), ("févr.", 2), ("02", 2), ("Août", 8),
                                           ("AOUT", 8), ("Sept.", 9), ("Juil.", 7), ("13", None), ("xyz", None)])
def test_normalize_mois(texte, attendu):
    assert an.normalize_mois(texte) == attendu


def test_dictionnaire_de_donnees():
    texte = cs.build_dictionnaire()
    for schema in cs.SCHEMAS.values():
        assert schema.nom in texte
        assert all(f"`{c.nom}`" in texte for c in schema.colonnes)
