"""
common/academic_catalog.py — Catalogue académique partagé (Lot L2-a)
====================================================================

Rôle
    Définir UNE fois les objets académiques utilisés par plusieurs sources :
    - les 8 départements canoniques (réutilisés par departements.csv en L2-c) ;
    - les 25 filières de PostgreSQL (volume validé à l'Étape 2) ;
    - un vivier de 120 enseignants (volume validé) dont les noms servent de
      « responsable pédagogique » des classes PostgreSQL, et qui sera enrichi
      par enseignants.csv en L2-c.

Pourquoi partager ?
    Le PDF Source 1 décrit classes.responsable comme un texte libre, et le
    PDF Source 3 décrit des enseignants identifiés par teacher_code. Si les
    deux générateurs inventaient chacun leurs noms, aucun rapprochement
    enseignant <-> formation ne serait possible (point C.15 de l'Étape 1).
    Avec un vivier commun, le rapprochement reste possible, mais seulement
    par le NOM (fragile, comme en entreprise), jamais par une clé.

Conventions (à valider, voir README de la Source 1)
    - Codes filière : LIC-xxx, MAS-xxx, CERT-xxx (VARCHAR(20), unique).
    - nom_filiere sans le niveau (« Génie Logiciel » + niveau LICENCE).
    - Coûts en XOF (FCFA), valeurs indicatives réalistes.
    - Durées : Licence 36 mois, Master 24 mois, Certificat 6 à 12 mois.
    - teacher_code : ENS-NNNN.
    - Anomalie A07 intégrée au catalogue : la filière IA porte trois libellés
      différents selon le niveau (« Intelligence Artificielle », « IA »,
      « Ingénierie IA »), comme le demande le PDF Source 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from common import senegalese_data as sn
from common.seed import get_rng

# -----------------------------------------------------------------------------
# Départements canoniques
# -----------------------------------------------------------------------------
DEPARTEMENTS: tuple[str, ...] = (
    "Informatique",
    "Data",
    "Intelligence Artificielle",
    "Réseaux et Télécommunications",
    "Cybersécurité",
    "Management",
    "Finance et Comptabilité",
    "Marketing Digital",
)

NIVEAUX_FILIERE: tuple[str, ...] = ("LICENCE", "MASTER", "CERTIFICAT")

# Nombre d'années académiques d'un parcours complet
ANNEES_PAR_NIVEAU: dict[str, int] = {"LICENCE": 3, "MASTER": 2, "CERTIFICAT": 1}

# Libellé IA canonique (sert de référence pour l'anomalie A07)
LIBELLE_IA_CANONIQUE = "Intelligence Artificielle"


@dataclass(frozen=True)
class Filiere:
    code_filiere: str
    nom_filiere: str
    departement: str
    niveau: str
    duree_mois: int
    cout_total: int          # XOF
    popularite: int          # poids de tirage (convention de génération, non stocké)
    libelle_canonique: str   # nom attendu après standardisation (non stocké)


def _f(code, nom, dept, niveau, duree, cout, pop, canon=None) -> Filiere:
    return Filiere(code, nom, dept, niveau, duree, cout, pop, canon or nom)


FILIERES: tuple[Filiere, ...] = (
    # --- Licences (36 mois) --------------------------------------------------
    _f("LIC-GL",    "Génie Logiciel",                "Informatique",                  "LICENCE", 36, 2_100_000, 3),
    _f("LIC-DWM",   "Développement Web et Mobile",   "Informatique",                  "LICENCE", 36, 1_950_000, 3),
    _f("LIC-DATA",  "Science des Données",           "Data",                          "LICENCE", 36, 2_250_000, 3),
    _f("LIC-IA",    "Intelligence Artificielle",     "Intelligence Artificielle",     "LICENCE", 36, 2_400_000, 3),
    _f("LIC-RT",    "Réseaux et Télécommunications", "Réseaux et Télécommunications", "LICENCE", 36, 2_000_000, 2),
    _f("LIC-CYB",   "Cybersécurité",                 "Cybersécurité",                 "LICENCE", 36, 2_300_000, 2),
    _f("LIC-MGT",   "Management des Organisations",  "Management",                    "LICENCE", 36, 1_800_000, 2),
    _f("LIC-FC",    "Finance et Comptabilité",       "Finance et Comptabilité",       "LICENCE", 36, 1_850_000, 2),
    _f("LIC-MKD",   "Marketing Digital",             "Marketing Digital",             "LICENCE", 36, 1_750_000, 1),
    # --- Masters (24 mois) ---------------------------------------------------
    _f("MAS-GL",    "Génie Logiciel",                "Informatique",                  "MASTER", 24, 3_200_000, 2),
    _f("MAS-BI",    "Business Intelligence",         "Data",                          "MASTER", 24, 3_500_000, 3),
    _f("MAS-DE",    "Data Engineering",              "Data",                          "MASTER", 24, 3_500_000, 3),
    _f("MAS-IA",    "IA",                            "Intelligence Artificielle",     "MASTER", 24, 3_800_000, 3,
       LIBELLE_IA_CANONIQUE),
    _f("MAS-CYB",   "Cybersécurité",                 "Cybersécurité",                 "MASTER", 24, 3_600_000, 2),
    _f("MAS-CLOUD", "Cloud Computing et DevOps",     "Réseaux et Télécommunications", "MASTER", 24, 3_400_000, 2),
    _f("MAS-MSI",   "Management des Systèmes d'Information", "Management",            "MASTER", 24, 3_000_000, 1),
    _f("MAS-FIN",   "Finance d'Entreprise",          "Finance et Comptabilité",       "MASTER", 24, 3_100_000, 1),
    _f("MAS-MKD",   "Marketing Digital et E-commerce", "Marketing Digital",           "MASTER", 24, 2_900_000, 1),
    # --- Certificats (6 à 12 mois) -------------------------------------------
    _f("CERT-PY",   "Programmation Python",          "Informatique",                  "CERTIFICAT", 6,  450_000, 3),
    _f("CERT-DA",   "Data Analyst",                  "Data",                          "CERTIFICAT", 9,  750_000, 3),
    _f("CERT-IA",   "Ingénierie IA",                 "Intelligence Artificielle",     "CERTIFICAT", 12, 950_000, 2,
       LIBELLE_IA_CANONIQUE),
    _f("CERT-PBI",  "Power BI et Visualisation",     "Data",                          "CERTIFICAT", 6,  400_000, 2),
    _f("CERT-CYB",  "Sécurité des Réseaux",          "Cybersécurité",                 "CERTIFICAT", 9,  700_000, 1),
    _f("CERT-CM",   "Community Management",          "Marketing Digital",             "CERTIFICAT", 6,  350_000, 1),
    _f("CERT-GP",   "Gestion de Projet Agile",       "Management",                    "CERTIFICAT", 6,  400_000, 1),
)

FILIERES_PAR_CODE: dict[str, Filiere] = {f.code_filiere: f for f in FILIERES}


# -----------------------------------------------------------------------------
# Vivier d'enseignants
# -----------------------------------------------------------------------------
NB_ENSEIGNANTS = 120


@dataclass(frozen=True)
class Enseignant:
    teacher_code: str
    prenom: str
    nom: str
    sexe: str
    departement: str

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}"


@lru_cache(maxsize=4)
def build_teacher_pool(nb: int = NB_ENSEIGNANTS, seed: int | None = None) -> tuple[Enseignant, ...]:
    """
    Vivier déterministe d'enseignants, réparti équitablement entre les
    8 départements. Les noms complets sont uniques (un responsable de classe
    doit désigner une seule personne).
    """
    rng = get_rng("enseignants", seed=seed)
    teachers: list[Enseignant] = []
    used_names: set[str] = set()
    for i in range(nb):
        departement = DEPARTEMENTS[i % len(DEPARTEMENTS)]
        while True:
            sexe = sn.random_sexe(rng)
            prenom, nom = sn.random_first_name(rng, sexe), sn.random_last_name(rng)
            if f"{prenom} {nom}" not in used_names:
                used_names.add(f"{prenom} {nom}")
                break
        teachers.append(Enseignant(f"ENS-{i + 1:04d}", prenom, nom, sexe, departement))
    return tuple(teachers)


def validate_catalog() -> list[str]:
    """Contrôles de cohérence du catalogue (liste vide = OK)."""
    problems: list[str] = []
    if len(FILIERES) != 25:
        problems.append(f"25 filières attendues, {len(FILIERES)} trouvées")
    codes = [f.code_filiere for f in FILIERES]
    if len(codes) != len(set(codes)):
        problems.append("code_filiere en double")
    for f in FILIERES:
        if f.departement not in DEPARTEMENTS:
            problems.append(f"{f.code_filiere} : département inconnu {f.departement}")
        if f.niveau not in NIVEAUX_FILIERE:
            problems.append(f"{f.code_filiere} : niveau inconnu {f.niveau}")
        if f.duree_mois <= 0 or f.cout_total < 0:
            problems.append(f"{f.code_filiere} : durée ou coût invalide")
        if len(f.code_filiere) > 20 or len(f.nom_filiere) > 150:
            problems.append(f"{f.code_filiere} : dépasse la longueur du PDF")
    if {f.nom_filiere for f in FILIERES if f.libelle_canonique == LIBELLE_IA_CANONIQUE} != {
            "Intelligence Artificielle", "IA", "Ingénierie IA"}:
        problems.append("les trois libellés IA du PDF ne sont pas tous présents")
    return problems
