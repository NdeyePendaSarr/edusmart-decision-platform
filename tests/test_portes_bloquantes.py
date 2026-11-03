"""
Tests unitaires — pipeline/run_pipeline.py : une extraction en échec ou une porte KO arrête le lot.

Aucune base n'est nécessaire : les extracteurs, le chargement, la transformation et l'entrepôt sont
remplacés par des doublures qui notent leur appel. Les fonctions qualite() et entrepot() restent les
vraies : ce sont elles qui traduisent le résultat de G3 et de G4 en code de sortie.
"""
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pipeline import load, load_dw, rapport_qualite
from pipeline import run_pipeline as rp
from pipeline import transform, verify_g2, verify_g3, verify_g4

ETAPES = list(rp.ETAPES)
SOURCES = ["s1_postgresql", "s2_mysql"]

G3_VALIDEE = [
    # 159 946 anomalies détectées et traitées : c'est le cas nominal, pas un échec
    verify_g3.ResultatAnomalie("A01", 159_946, 159_946, {"SIGNALE": 159_946}, 0),
    # Clés Redis expirées avant l'extraction : comptées à part, tolérées
    verify_g3.ResultatAnomalie("E01", 100, 90, {"SIGNALE": 90}, 0, non_extraites=10),
]
G3_KO = [verify_g3.ResultatAnomalie("A01", 159_946, 159_945, {"SIGNALE": 159_945}, 0)]


@pytest.fixture
def pipeline(monkeypatch):
    """Pipeline en doublures. Les attributs de l'objet rendu règlent le résultat de chaque étape."""
    etat = SimpleNamespace(appels=[], sources_en_echec=set(), g2_ok=True, g3=G3_VALIDEE, g4_ok=True, meta=MagicMock())

    def extracteur(source: str) -> ModuleType:
        def extract(batch, meta):
            if source in etat.sources_en_echec:
                raise RuntimeError("source injoignable")
            etat.appels.append(f"extract:{source}")

        module = ModuleType(f"extracteur_{source}")
        module.extract = extract
        monkeypatch.setitem(sys.modules, module.__name__, module)
        return module

    def noter(nom: str, retour=None):
        def doublure(*args, **kwargs):
            etat.appels.append(nom)
            return retour
        return doublure

    def charger_staging(batch, sources, meta):
        etat.appels.append(f"load:{','.join(sources)}")

    settings = SimpleNamespace(pg_dw=SimpleNamespace(connect_kwargs=lambda: {}))
    monkeypatch.setattr(rp, "get_settings", lambda: settings)
    monkeypatch.setattr("psycopg2.connect", lambda **kwargs: MagicMock())
    monkeypatch.setattr(rp, "MetaStore", lambda conn: etat.meta)
    monkeypatch.setattr(rp, "emplacements", lambda: {})
    monkeypatch.setattr(rp, "Batch", lambda batch_id: SimpleNamespace(batch_id=batch_id))
    monkeypatch.setattr(rp, "new_batch_id", lambda: "B20260101T000000")
    monkeypatch.setattr(rp, "EXTRACTEURS", {s: extracteur(s).__name__ for s in SOURCES})
    monkeypatch.setattr(load, "load", charger_staging)
    monkeypatch.setattr(verify_g2, "verify", lambda batch, sources: (
        etat.appels.append("verify"),
        [verify_g2.Check("G2.1", "objet", "libellé", etat.g2_ok, "détail")])[1])
    monkeypatch.setattr(verify_g2, "write_report", lambda batch, checks: "rapport")
    monkeypatch.setattr(transform, "transform", noter("transform"))
    monkeypatch.setattr(rapport_qualite, "calculer", noter("qualite", ([], [])))
    monkeypatch.setattr(rapport_qualite, "ecrire_rapport", lambda conn, batch_id, lignes, dims: "rapport")
    monkeypatch.setattr(verify_g3, "verify", lambda conn, batch_id: etat.g3)
    monkeypatch.setattr(verify_g3, "write_report", lambda batch_id, resultats: "rapport")
    monkeypatch.setattr(load_dw, "charger", noter("dw", {}))
    monkeypatch.setattr(verify_g4, "verify", lambda conn: [verify_g4.Check("G4.1", "libellé", etat.g4_ok, "détail")])
    monkeypatch.setattr(verify_g4, "write_report", lambda checks, batch_id: "rapport")
    monkeypatch.setattr(rp, "indicateurs", noter("kpi", 0))
    return etat


def test_anomalies_detectees_ne_bloquent_pas(pipeline):
    """G3 validée avec 159 946 anomalies et des clés Redis expirées : toutes les étapes s'exécutent."""
    assert rp.run(SOURCES, ETAPES) == 0
    assert pipeline.appels == ["extract:s1_postgresql", "extract:s2_mysql", "load:s1_postgresql,s2_mysql",
                               "verify", "transform", "qualite", "dw", "kpi"]


def test_extraction_en_echec_arrete_avant_la_transformation(pipeline):
    """Les autres sources restent extraites, chargées et vérifiées (pipeline/README.md, § 3)."""
    pipeline.sources_en_echec = {"s1_postgresql"}
    assert rp.run(SOURCES, ETAPES) == 1
    assert pipeline.appels == ["extract:s2_mysql", "load:s2_mysql", "verify"]
    pipeline.meta.record_failure.assert_called_once()


def test_g2_ko_arrete_avant_la_transformation(pipeline):
    pipeline.g2_ok = False
    assert rp.run(SOURCES, ETAPES) == 1
    assert pipeline.appels[-1] == "verify"


def test_g3_ko_arrete_avant_l_entrepot(pipeline):
    """Une seule anomalie sans preuve de traitement suffit à faire échouer G3."""
    pipeline.g3 = G3_KO
    assert rp.run(SOURCES, ETAPES) == 1
    assert pipeline.appels[-1] == "qualite"


def test_g4_ko_arrete_avant_les_kpi(pipeline):
    pipeline.g4_ok = False
    assert rp.run(SOURCES, ETAPES) == 1
    assert pipeline.appels[-1] == "dw"


def test_g2_sans_aucun_controle_arrete_le_lot(pipeline, monkeypatch):
    monkeypatch.setattr(verify_g2, "verify", lambda batch, sources: [])
    assert rp.run(SOURCES, ETAPES) == 1
    assert "transform" not in pipeline.appels


def test_option_lots_mixtes_transmise_a_la_transformation(pipeline, monkeypatch):
    recu = {}
    monkeypatch.setattr(transform, "transform", lambda sources, meta, autoriser_lots_mixtes=False: recu.update(option=autoriser_lots_mixtes))
    assert rp.run(SOURCES, ETAPES) == 0
    assert recu == {"option": False}
    assert rp.run(SOURCES, ETAPES, autoriser_lots_mixtes=True) == 0
    assert recu == {"option": True}
