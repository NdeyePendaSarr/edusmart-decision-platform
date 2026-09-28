"""
Tests unitaires — pipeline L4 (registre, atterrissage, extracteurs CSV / MongoDB / Redis).
Sans serveur : mongomock et fakeredis ; PostgreSQL, MySQL, load et G2 sont couverts
par tests/test_pipeline_integration.py.
"""
import csv
import itertools
import json
from pathlib import Path

import fakeredis
import mongomock
import pytest

from common.config import get_settings
from pipeline import extract_csv, extract_mongodb, extract_redis
from pipeline import registry as reg
from pipeline.landing import Batch, Empreinte, read_landing, read_manifest, update_manifest, write_landing, latest_batch
from sources.s1_postgresql.generate_data import COLUMNS as S1
from sources.s2_mysql.generate_data import COLUMNS as S2
from sources.s3_csv.create_source import SCHEMAS


# --- Registre -------------------------------------------------------------------
def test_dix_sept_objets():
    assert len(reg.OBJECTS) == 17
    assert [len(reg.objects_of(s)) for s in reg.SOURCES] == [5, 6, 4, 1, 1]
    assert len({o.stg_table for o in reg.OBJECTS}) == 17


def test_colonnes_issues_du_volet_a():
    for o in reg.objects_of("s1_postgresql"):
        assert list(o.colonnes) == S1[o.objet]
    for o in reg.objects_of("s2_mysql"):
        assert list(o.colonnes) == S2[o.objet]
    for o in reg.objects_of("s3_csv"):
        assert list(o.colonnes) == SCHEMAS[o.objet].entetes


def test_ddl_staging_a_jour():
    fichier = Path(reg.__file__).parent / "sql" / "staging" / "01_staging_tables.sql"
    assert fichier.read_text(encoding="utf-8") == reg.staging_ddl(), "Relancez : python -m pipeline.registry"


def test_ddl_metadonnees_conforme_au_pdf():
    ddl = (Path(reg.__file__).parent / "sql" / "meta" / "01_meta_tables.sql").read_text(encoding="utf-8")
    for colonne in ("code_source", "date_debut", "duree_secondes", "nb_lignes", "erreurs", "statut", "version_pipeline"):
        assert colonne in ddl
    assert "meta.metadata_sources" in ddl and "meta.etl_execution_log" in ddl


# --- Atterrissage -----------------------------------------------------------------
@pytest.fixture
def batch(tmp_path):
    return Batch("B20260101T000000", root=tmp_path)


def test_null_et_chaine_vide_distincts(batch):
    obj = reg.get_object("s5_redis", "keys")
    lignes = [["a", "string", '"x"', "-1"], ["b", None, "", "\\"]]
    n, empreinte = write_landing(batch, obj, lignes)
    assert n == 2 and list(read_landing(batch, obj)) == lignes
    e = Empreinte()
    for ligne in lignes:
        e.ajouter(ligne)
    assert e.hexdigest() == empreinte


def test_nombre_de_valeurs_controle(batch):
    with pytest.raises(ValueError):
        write_landing(batch, reg.get_object("s5_redis", "keys"), [["trop", "peu"]])


def test_manifeste_et_dernier_lot(batch, tmp_path):
    obj = reg.get_object("s5_redis", "keys")
    update_manifest(batch, obj, 3, "abc", "localhost")
    m = read_manifest(batch)
    assert m["objets"]["s5_redis.keys"]["nb_lignes"] == 3
    assert latest_batch(tmp_path).batch_id == batch.batch_id


# --- Extraction CSV (vrais fichiers de la Source 3) -------------------------------------
def test_extraction_csv_fidele(batch):
    res = extract_csv.extract(batch)
    for key, n in res.items():
        schema = SCHEMAS[key]
        with (extract_csv.OUTPUT_DIR / schema.nom).open(encoding=schema.encodage, newline="") as h:
            originales = list(csv.reader(h, delimiter=schema.separateur))[1:]
        relues = list(read_landing(batch, reg.get_object("s3_csv", key)))
        assert n == len(originales) and relues == originales        # aucune valeur modifiée, vide = chaîne vide
    salaires = list(read_landing(batch, reg.get_object("s3_csv", "salaires")))
    assert any(r[2] in ("Février", "Août", "Décembre") for r in salaires)   # ISO-8859-1 correctement décodé
    absences = list(read_landing(batch, reg.get_object("s3_csv", "absences")))
    assert any("/" in r[2] for r in absences)                        # formats de date d'origine conservés


def test_extraction_csv_entete_non_conforme(tmp_path, batch):
    for key, schema in SCHEMAS.items():
        contenu = (extract_csv.OUTPUT_DIR / schema.nom).read_bytes()
        if key == "departements":
            contenu = contenu.replace(b"nom_departement", b"nom_dept", 1)
        (tmp_path / schema.nom).write_bytes(contenu)
    with pytest.raises(extract_csv.FormatCSVError):
        extract_csv.extract(batch, dossier=tmp_path)


# --- Extraction MongoDB (mongomock) ------------------------------------------------------
def test_extraction_mongodb_types_conserves(batch):
    from sources.s4_mongodb.generate_data import read_events
    chemin = get_settings().paths.generated_dir / "s4_mongodb" / "events.jsonl.gz"
    if not chemin.exists():
        pytest.skip("Source 4 non générée")
    docs = list(itertools.islice(read_events(chemin), 3000))
    db = mongomock.MongoClient().edusmart_mobile
    db.events.insert_many([dict(d) for d in docs])
    assert extract_mongodb.extract(batch, db=db) == {"events": 3000}
    lignes = list(read_landing(batch, reg.get_object("s4_mongodb", "events")))
    types = {type(json.loads(doc)["timestamp"]).__name__ for _, _, doc in lignes if "timestamp" in json.loads(doc)}
    assert types == {"dict", "str", "int"}                           # date ($date), texte, nombre : D08 préservé
    assert [e for _, e, _ in lignes] == [d.get("event_id") for d in docs]


# --- Extraction Redis (fakeredis) ----------------------------------------------------------
def test_extraction_redis_snapshot(batch):
    from sources.s5_redis.insert_data import load_into
    chemin = get_settings().paths.generated_dir / "s5_redis" / "snapshot.json"
    if not chemin.exists():
        pytest.skip("Source 5 non générée")
    snapshot = json.loads(chemin.read_text(encoding="utf-8"))
    client = fakeredis.FakeRedis(decode_responses=True)
    load_into(client, snapshot)
    assert extract_redis.extract(batch, client=client) == {"keys": len(snapshot)}
    lignes = {r[0]: r for r in read_landing(batch, reg.get_object("s5_redis", "keys"))}
    assert set(lignes) == set(snapshot)
    classement = json.loads(lignes["leaderboard:python"][2])
    assert [s for _, s in classement] == sorted((s for _, s in classement), reverse=True)
    sessions = [r for k, r in lignes.items() if k.startswith("session:")]
    assert {r[3] for r in sessions} - {"-1"} and "-1" in {r[3] for r in sessions}   # TTL réels et sessions E01 sans TTL


def test_toutes_les_etapes_du_code_sont_autorisees_par_le_journal():
    """Régression L6 : l'étape DW était refusée par ck_log_etape sur une base créée en L4."""
    import re
    racine = Path(reg.__file__).parent
    code = "\n".join(p.read_text(encoding="utf-8") for p in racine.glob("*.py"))
    etapes = set(re.findall(r'\.step\([^,]+,\s*"([A-Z]+)"', code)) | set(re.findall(r'record_failure\([^,]+,\s*"([A-Z]+)"', code))
    assert etapes >= {"EXTRACT", "LOAD", "TRANSFORM", "VERIFY", "DW"}
    ddl = (racine / "sql" / "meta" / "01_meta_tables.sql").read_text(encoding="utf-8")
    autorisees = re.findall(r"ADD CONSTRAINT ck_log_etape\s+CHECK \(etape IN \(([^)]*)\)", ddl)
    assert autorisees, "la contrainte doit être redéfinie (mise à niveau des bases existantes)"
    assert etapes <= set(re.findall(r"'([A-Z]+)'", autorisees[0]))
    assert "ck_log_etape" not in (racine / "sql" / "dw" / "01_dimensions.sql").read_text(encoding="utf-8").split("--")[0]


def test_avertissement_snapshot_redis_perime():
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set("online_users", 5)
    assert any("statistics:today absente" in a for a in extract_redis.controler_fraicheur(client))
    client.hset("statistics:today", mapping={"active_students": 1})
    client.expire("statistics:today", 3600)
    assert extract_redis.controler_fraicheur(client) == []
    client.expire("statistics:today", 60)
    assert any("expire dans" in a for a in extract_redis.controler_fraicheur(client))


def test_batch_en_staging_consulte_les_17_tables():
    """Régression L6 : une relance ciblée (--sources s5_redis) doit être vue comme le lot courant."""
    from pipeline.transform import batch_en_staging

    class Curseur:
        def __init__(self, journal): self.journal = journal
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql): self.journal.append(sql)
        def fetchall(self): return [("B20260101T000000",), ("B20260928T011811",)]

    class Connexion:
        def __init__(self): self.journal = []
        def cursor(self): return Curseur(self.journal)

    conn = Connexion()
    assert batch_en_staging(conn) == "B20260928T011811"            # le plus récent
    for o in reg.OBJECTS:
        assert f"staging.{o.stg_table}" in conn.journal[0], o.stg_table
