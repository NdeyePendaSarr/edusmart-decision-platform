"""
sources/s3_csv/create_source.py — Structure de la Source 3 (Lot L2-c)
====================================================================

Le service RH n'a pas de base de données (PDF Source 3) : la « création de la
source » consiste à DÉCRIRE précisément les fichiers exportés. Ce module :

    1. définit SCHEMAS, la source unique de vérité pour les 4 fichiers :
       colonnes, types, contraintes et descriptions du PDF, plus l'encodage
       et le séparateur de chaque fichier (décision validée) ;
    2. crée le dossier de sortie sources/s3_csv/output/ ;
    3. génère sources/s3_csv/dictionnaire_donnees.md, le dictionnaire de
       données (livrable « Description des fichiers CSV et de leur structure »).

generate_data.py et verify_source.py lisent SCHEMAS : impossible que le
générateur et le vérificateur divergent sur la structure.

Exécution : python -m sources.s3_csv.create_source
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from common.logger import get_logger

logger = get_logger("s3_create")

SOURCE = "s3_csv"
SOURCE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SOURCE_DIR / "output"
DICTIONNAIRE_PATH = SOURCE_DIR / "dictionnaire_donnees.md"


@dataclass(frozen=True)
class Colonne:
    nom: str
    type_sql: str
    contraintes: str
    description: str


@dataclass(frozen=True)
class FichierCSV:
    nom: str
    description: str
    encodage: str
    separateur: str
    colonnes: tuple[Colonne, ...]
    regles_metier: tuple[str, ...]

    @property
    def entetes(self) -> list[str]:
        return [c.nom for c in self.colonnes]


SCHEMAS: dict[str, FichierCSV] = {
    "enseignants": FichierCSV(
        "enseignants.csv", "Informations générales des enseignants", "utf-8", ",",
        (
            Colonne("teacher_code", "VARCHAR(20)", "UNIQUE", "Identifiant RH"),
            Colonne("nom", "VARCHAR(100)", "NOT NULL", "Nom"),
            Colonne("prenom", "VARCHAR(100)", "NOT NULL", "Prénom"),
            Colonne("sexe", "CHAR(1)", "CHECK (M,F)", "Sexe"),
            Colonne("date_naissance", "DATE", "NOT NULL", "Date de naissance"),
            Colonne("telephone", "VARCHAR(20)", "NULL", "Téléphone"),
            Colonne("email", "VARCHAR(150)", "NULL", "Adresse e-mail"),
            Colonne("specialite", "VARCHAR(100)", "NOT NULL", "Domaine"),
            Colonne("grade", "VARCHAR(50)", "NULL", "Assistant, Maître Assistant..."),
            Colonne("date_embauche", "DATE", "NOT NULL", "Date d'embauche"),
            Colonne("statut", "VARCHAR(30)", "NOT NULL", "Permanent, Vacataire"),
        ),
        ("Un enseignant possède un code unique.", "Deux enseignants peuvent avoir le même nom.",
         "L'adresse e-mail peut être absente."),
    ),
    "departements": FichierCSV(
        "departements.csv", "Liste des départements auxquels appartiennent les enseignants", "utf-8", ",",
        (
            Colonne("id_departement", "INTEGER", "PRIMARY KEY", "Identifiant"),
            Colonne("nom_departement", "VARCHAR(100)", "UNIQUE", "Département"),
            Colonne("responsable", "VARCHAR(150)", "NULL", "Responsable"),
            Colonne("budget_annuel", "DECIMAL(12,2)", ">= 0", "Budget"),
            Colonne("batiment", "VARCHAR(50)", "NULL", "Localisation"),
        ),
        ("Un département possède un nom unique.", "Le budget doit être positif."),
    ),
    "salaires": FichierCSV(
        "salaires.csv", "Historique des paiements des enseignants", "iso-8859-1", ";",
        (
            Colonne("id_salaire", "INTEGER", "PRIMARY KEY", "Identifiant"),
            Colonne("teacher_code", "VARCHAR(20)", "FOREIGN KEY logique", "Enseignant"),
            Colonne("mois", "VARCHAR(20)", "NOT NULL", "Mois"),
            Colonne("annee", "INTEGER", "NOT NULL", "Année"),
            Colonne("salaire_base", "DECIMAL(12,2)", ">= 0", "Salaire"),
            Colonne("primes", "DECIMAL(12,2)", ">= 0", "Primes"),
            Colonne("retenues", "DECIMAL(12,2)", ">= 0", "Retenues"),
            Colonne("salaire_net", "DECIMAL(12,2)", ">= 0", "Salaire final"),
            Colonne("mode_paiement", "VARCHAR(30)", "NULL", "Banque, Wave..."),
        ),
        ("Un enseignant reçoit un salaire par mois.", "Le salaire net est calculé."),
    ),
    "absences": FichierCSV(
        "absences.csv", "Historique des absences des enseignants", "iso-8859-1", ";",
        (
            Colonne("id_absence", "INTEGER", "PRIMARY KEY", "Identifiant"),
            Colonne("teacher_code", "VARCHAR(20)", "FOREIGN KEY logique", "Enseignant"),
            Colonne("date_absence", "DATE", "NOT NULL", "Date"),
            Colonne("motif", "VARCHAR(100)", "NULL", "Motif"),
            Colonne("justifiee", "BOOLEAN", "NULL", "Oui / Non"),
            Colonne("duree_heures", "INTEGER", ">= 0", "Durée"),
            Colonne("remplace", "BOOLEAN", "NULL", "Remplacement effectué"),
        ),
        ("Une absence appartient à un enseignant.", "La durée est positive."),
    ),
}

FILE_ORDER = ("enseignants", "departements", "salaires", "absences")


def build_dictionnaire() -> str:
    """Dictionnaire de données en Markdown, construit à partir de SCHEMAS."""
    lines = [
        "# Dictionnaire de données — Source 3 : CSV Ressources humaines", "",
        "*Généré par `python -m sources.s3_csv.create_source` à partir de `SCHEMAS`. "
        "Ne pas modifier à la main.*", "",
        "Le service RH ne possède pas de base de données : il exporte des fichiers CSV "
        "(PDF Source 3). Les fichiers sont **indépendants** : les liens `teacher_code` "
        "sont des clés étrangères *logiques*, qu'aucun système ne contrôle.", "",
        "| Fichier | Encodage | Séparateur | Colonnes |", "|---|---|:-:|---:|",
        *[f"| `{s.nom}` | {s.encodage.upper()} | `{s.separateur}` | {len(s.colonnes)} |" for s in SCHEMAS.values()],
        "",
        "**Conventions d'écriture des valeurs (fichiers propres) :**",
        "- dates au format `AAAA-MM-JJ` ;",
        "- booléens `Oui` / `Non` ;",
        "- montants en XOF avec deux décimales et un point décimal ;",
        "- valeur absente = champ vide ;",
        "- fins de ligne Windows (CRLF), comme un export Excel.", "",
    ]
    for key in FILE_ORDER:
        s = SCHEMAS[key]
        lines += [f"## {s.nom}", "", s.description + ".", "",
                  "| Colonne | Type | Contraintes | Description |", "|---|---|---|---|",
                  *[f"| `{c.nom}` | {c.type_sql} | {c.contraintes} | {c.description} |" for c in s.colonnes], "",
                  "**Règles métier :** " + " ".join(s.regles_metier), ""]
    return "\n".join(lines)


def main() -> int:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        DICTIONNAIRE_PATH.write_text(build_dictionnaire(), encoding="utf-8")
        for key in FILE_ORDER:
            s = SCHEMAS[key]
            logger.info("%-17s %-10s sep '%s'  %2d colonnes", s.nom, s.encodage, s.separateur, len(s.colonnes))
        logger.info("Dossier de sortie : %s", OUTPUT_DIR)
        logger.info("Dictionnaire de données : %s", DICTIONNAIRE_PATH)
        return 0
    except OSError as exc:
        logger.error("Création impossible : %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
