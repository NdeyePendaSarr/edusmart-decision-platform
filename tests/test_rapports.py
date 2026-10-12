"""
Tests unitaires — cohérence des rapports (L10, Phases 14, 16, 17). Sans base de données.

Les chiffres des rapports sont écrits à la main : ce test vérifie qu'ils restent ALIGNÉS sur la
référence validée des KPI (pipeline/verify_g6.py, REFERENCE_KPI), qu'aucune variante arrondie
contradictoire ne s'y glisse, et que tous les liens relatifs de la documentation fonctionnent.
"""
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from pipeline.verify_g6 import REFERENCE_KPI

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"
RAPPORTS_KPI = ("14_data_storytelling.md", "17_rapport_decisionnel.md")
RAPPORTS = ("14_data_storytelling.md", "16_rapport_individuel.md", "17_rapport_decisionnel.md")


def _fr(valeur: Decimal, decimales: int) -> str:
    """Decimal -> texte français : 13553.9 -> '13 553,90' (espace des milliers, virgule décimale)."""
    q = valeur.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    entier, _, frac = f"{q:,.{decimales}f}".partition(".")
    return entier.replace(",", " ") + ("," + frac if frac else "")


def formes_canoniques() -> dict[str, str]:
    """Forme écrite de chaque KPI dans les rapports, calculée depuis la référence (jamais recopiée)."""
    r = REFERENCE_KPI
    return {
        "CA": f"{_fr(r['CA'] / Decimal(10**9), 3)} Mds XOF",
        "RECOUVREMENT": f"{_fr(100 * r['RECOUVREMENT'], 2)} %",
        "REUSSITE": f"{_fr(100 * r['REUSSITE'], 2)} %",
        "ABANDON": f"{_fr(100 * r['ABANDON'], 2)} %",
        "PROGRESSION": f"{_fr(r['PROGRESSION'], 2)} %",
        "ACTIFS_30J": _fr(r["ACTIFS_30J"], 0),
        "CONNEXION_MEDIANE": f"{_fr(r['CONNEXION_MEDIANE'], 0)} s",
        "ETUDIANTS": _fr(r["ETUDIANTS"], 0),
    }


def test_formes_canoniques():
    assert formes_canoniques() == {
        "CA": "13,554 Mds XOF", "RECOUVREMENT": "90,10 %", "REUSSITE": "93,13 %", "ABANDON": "6,24 %",
        "PROGRESSION": "65,59 %", "ACTIFS_30J": "3 003", "CONNEXION_MEDIANE": "1 740 s", "ETUDIANTS": "10 500"}


@pytest.mark.parametrize("rapport", RAPPORTS_KPI)
def test_les_8_kpi_sont_cites_avec_la_valeur_de_reference(rapport):
    texte = (DOCS / rapport).read_text(encoding="utf-8")
    absents = [f"{code} ({forme})" for code, forme in formes_canoniques().items() if forme not in texte]
    assert not absents, f"{rapport} : KPI absents ou écrits autrement que la référence : {absents}"


@pytest.mark.parametrize("rapport", RAPPORTS)
def test_aucune_variante_arrondie_contradictoire(rapport):
    """« 93,1 % » à côté de « 93,13 % » ferait croire à deux chiffres différents (arrondis à l'unité tolérés)."""
    texte = (DOCS / rapport).read_text(encoding="utf-8")
    variantes = []
    for code in ("RECOUVREMENT", "REUSSITE", "ABANDON"):
        une_decimale = _fr(100 * REFERENCE_KPI[code], 1)
        if re.search(rf"(?<![\d,]){re.escape(une_decimale)}(?!\d)\s?%", texte):
            variantes.append(une_decimale)
    une_decimale = _fr(REFERENCE_KPI["PROGRESSION"], 1)
    if re.search(rf"(?<![\d,]){re.escape(une_decimale)}(?!\d)", texte):
        variantes.append(une_decimale)
    assert not variantes, f"{rapport} : variantes à une décimale : {variantes}"


def test_liens_relatifs_de_la_documentation():
    fichiers = sorted(DOCS.glob("*.md")) + [RACINE / "README.md", RACINE / "pipeline" / "README.md"]
    casses = []
    for f in fichiers:
        for lien in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", f.read_text(encoding="utf-8")):
            if not lien.startswith(("http://", "https://", "mailto:")) and not (f.parent / lien).exists():
                casses.append(f"{f.relative_to(RACINE)} -> {lien}")
    assert not casses, casses
