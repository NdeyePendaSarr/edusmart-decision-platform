"""
scripts/verifier_g5b.py — Porte G5b : les mesures DAX de Power BI = les KPI SQL (Lot L8)
======================================================================================

    1. python -m scripts.verifier_g5b --modele
       crée powerbi/g5b_valeurs_powerbi.csv : une ligne par KPI, colonne valeur_powerbi VIDE.
       Les valeurs attendues n'y figurent PAS : la saisie reste « à l'aveugle ».
    2. Dans Power BI, page « Contrôle G5b », SANS AUCUN FILTRE : recopier la valeur de chaque mesure
       (format « Nombre décimal », 6 décimales ; virgule ou point acceptés, espaces ignorés).
    3. python -m scripts.verifier_g5b
       compare aux valeurs de référence (data/reports/kpi_reference.json, calculées en SQL)
       et écrit data/reports/G5b.md.

Tolérances : montants au centime ; effectifs et médiane exacts ; ratios et moyennes à 1e-6
près (6 décimales affichées).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
MODELE = RACINE / "powerbi" / "g5b_valeurs_powerbi.csv"
MESURES = {"CA": "CA encaissé", "RECOUVREMENT": "Taux de recouvrement", "REUSSITE": "Taux de réussite",
           "ABANDON": "Taux d'abandon", "PROGRESSION": "Progression moyenne",
           "ACTIFS_30J": "Étudiants actifs (30 j)", "CONNEXION_MEDIANE": "Temps médian de connexion (s)",
           "ETUDIANTS": "Nombre réel d'étudiants"}
TOLERANCES = {"CA": Decimal("0.01"), "RECOUVREMENT": Decimal("1e-6"), "REUSSITE": Decimal("1e-6"),
              "ABANDON": Decimal("1e-6"), "PROGRESSION": Decimal("1e-6"), "ACTIFS_30J": Decimal(0),
              "CONNEXION_MEDIANE": Decimal(0), "ETUDIANTS": Decimal(0)}


def lire_nombre(texte: str) -> Decimal | None:
    """'13 553 901 000,00' | '0,901016' | '1740' -> Decimal ; vide -> None. Les pourcentages sont refusés."""
    t = (texte or "").strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    if not t:
        return None
    if "%" in t:
        raise ValueError(f"« {texte} » : afficher la mesure en nombre décimal (0,901016), pas en pourcentage")
    if "," in t and "." in t:                       # 13,553,901,000.00 (format anglais)
        t = t.replace(",", "")
    t = t.replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation as exc:
        raise ValueError(f"« {texte} » n'est pas un nombre") from exc


def comparer(reference: dict[str, Decimal], saisies: dict[str, Decimal | None]) -> list[tuple[str, str, Decimal, Decimal | None, bool]]:
    res = []
    for code, mesure in MESURES.items():
        attendu, lu = reference[code], saisies.get(code)
        ok = lu is not None and abs(attendu - lu) <= TOLERANCES[code]
        res.append((code, mesure, attendu, lu, ok))
    return res


def charger_reference(chemin: Path) -> tuple[dict[str, Decimal], str]:
    ref = json.loads(chemin.read_text(encoding="utf-8"))
    return {c: Decimal(v["valeur"]) for c, v in ref["kpi"].items()}, ref["batch_id"]


def ecrire_modele() -> str:
    MODELE.parent.mkdir(parents=True, exist_ok=True)
    with MODELE.open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h, delimiter=";")
        w.writerow(["code", "mesure_dax", "valeur_powerbi"])
        for code, mesure in MESURES.items():
            w.writerow([code, mesure, ""])
    return str(MODELE)


def main(argv: list[str] | None = None) -> int:
    from common.config import get_settings
    parser = argparse.ArgumentParser(description="Porte G5b : DAX (Power BI) = KPI SQL")
    parser.add_argument("--modele", action="store_true", help="créer le fichier de saisie vide")
    args = parser.parse_args(argv)
    if args.modele:
        print(f"Fichier de saisie : {ecrire_modele()}")
        return 0
    reports = get_settings().paths.reports_dir
    reference, batch_id = charger_reference(reports / "kpi_reference.json")
    if not MODELE.exists():
        print("Fichier de saisie absent : lancez d'abord python -m scripts.verifier_g5b --modele")
        return 1
    with MODELE.open(encoding="utf-8-sig", newline="") as h:
        saisies = {r["code"]: lire_nombre(r["valeur_powerbi"]) for r in csv.DictReader(h, delimiter=";")}
    resultats = comparer(reference, saisies)
    n_ok = sum(r[4] for r in resultats)
    lignes = [f"# Porte G5b — DAX (Power BI) = SQL (DW), lot {batch_id}", "", f"*Contrôle du {datetime.now():%d/%m/%Y %H:%M}*", "",
              f"**Résultat : {'VALIDÉE' if n_ok == len(resultats) else 'NON VALIDÉE'}** ({n_ok}/{len(resultats)} mesures)", "",
              "| KPI | Mesure DAX | Référence SQL | Power BI | Tolérance | OK |", "|---|---|---:|---:|---:|:-:|",
              *[f"| {c} | {m} | {a} | {'—' if l is None else l} | {TOLERANCES[c]} | {'✅' if ok else '❌'} |" for c, m, a, l, ok in resultats], ""]
    chemin = reports / "G5b.md"
    chemin.write_text("\n".join(lignes), encoding="utf-8")
    for c, m, a, l, ok in resultats:
        print(f"[{'OK' if ok else 'KO'}] {m:<32} SQL={a}  Power BI={'(vide)' if l is None else l}")
    print(f"Porte G5b : {n_ok}/{len(resultats)} - {chemin}")
    return 0 if n_ok == len(resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
