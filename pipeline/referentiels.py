"""
pipeline/referentiels.py — Référentiels de la couche clean (Lot L5)
==================================================================

Remplit les tables clean.ref_* utilisées par les règles de standardisation :

    ref_villes             49 villes et leur région (géographie publique du Sénégal)
    ref_synonymes          écritures observées -> valeur canonique, par domaine
    ref_mapping_etudiants  mappings/mapping_etudiants.csv (artefact d'intégration livré)
    ref_mapping_contenus   mappings/mapping_courses.csv   (artefact d'intégration livré)

Origine des synonymes : PROFILAGE des valeurs distinctes du staging
(SELECT DISTINCT ... sur le lot L4), comme le ferait un gestionnaire de données.
Toute valeur ABSENTE de ces listes n'est pas devinée : la règle
« ..._INCONNU(E) » la signale. Le journal des anomalies (vérité terrain) n'est
JAMAIS lu ici.
"""

from __future__ import annotations

import csv

from common import senegalese_data as sn
from common.config import get_settings
from common.referential import MAPPING_COURSES_FILENAME, MAPPING_ETUDIANTS_FILENAME

# domaine -> {valeur canonique: [écritures observées]} (la valeur canonique est toujours incluse)
SYNONYMES: dict[str, dict[str, list[str]]] = {
    "sexe": {"M": ["M", "Homme", "Garçon", "1"], "F": ["F", "Femme", "Fille", "0"]},
    "mode_paiement": {
        "Orange Money": ["Orange Money", "OM", "orange money", "Orange-Money"],
        "Wave": ["Wave"],
        "Espèces": ["Espèces", "Especes", "Cash"],
        "Virement bancaire": ["Virement bancaire", "Virement", "Banque", "bank transfer"],
        "Carte bancaire": ["Carte bancaire", "CB", "Carte"],
    },
    "libelle_filiere": {"Intelligence Artificielle": ["Intelligence Artificielle", "IA", "Ingénierie IA"]},
    "categorie_module": {
        "Développement": ["Développement", "Developpement", "DEV"],
        "Data": ["Data", "data science"],
        "IA": ["IA", "AI", "Intelligence Artificielle"],
        "Réseaux": ["Réseaux"],
        "Cybersécurité": ["Cybersécurité", "Cyber"],
        "Management": ["Management", "Mgmt"],
        "Finance": ["Finance"],
        "Marketing": ["Marketing", "Marketing Digital"],
    },
    "appareil": {"Mobile": ["Mobile", "Téléphone", "Smartphone"], "PC": ["PC", "Ordinateur", "Desktop"],
                 "Tablette": ["Tablette", "Tablet"]},
    "os": {"Android": ["Android", "Android OS"], "iOS": ["iOS", "iPhone OS"]},
    "specialite": {
        "Intelligence Artificielle": ["Intelligence Artificielle", "IA", "I.A."],
        "Science des Données": ["Science des Données", "Data Science", "Sciences des données", "Data"],
        "Génie Logiciel": ["Génie Logiciel", "Informatique", "Dev"],
        "Réseaux et Télécommunications": ["Réseaux et Télécommunications", "Réseaux", "Télécoms", "Reseaux & Telecom"],
        "Cybersécurité": ["Cybersécurité", "Cyber sécurité", "Sécurité informatique"],
        "Management": ["Management", "Gestion"],
        "Finance": ["Finance", "Finance / Comptabilité", "Comptabilité"],
        "Marketing Digital": ["Marketing Digital", "Marketing"],
    },
    "grade": {
        "ASSISTANT": ["ASSISTANT", "Assistant", "Asst."],
        "MAITRE_ASSISTANT": ["MAITRE_ASSISTANT", "Maître Assistant", "Maitre-Assistant", "MA"],
        "MAITRE_CONFERENCE": ["MAITRE_CONFERENCE", "Maître de Conférences", "MC", "Maitre de conference"],
        "PROFESSEUR": ["PROFESSEUR", "Professeur", "Prof.", "Pr"],
    },
    "departement": {
        "Informatique": ["Informatique", "Département Informatique"],
        "Data": ["Data", "Développement Data", "Data Engineering"],
        "Intelligence Artificielle": ["Intelligence Artificielle"],
        "Réseaux et Télécommunications": ["Réseaux et Télécommunications", "Réseaux & Télécoms"],
        "Cybersécurité": ["Cybersécurité"], "Management": ["Management"],
        "Finance et Comptabilité": ["Finance et Comptabilité"], "Marketing Digital": ["Marketing Digital"],
    },
}


def charger(conn) -> dict[str, int]:
    """Recharge tous les référentiels (idempotent). Retourne le nombre de lignes par table."""
    paths = get_settings().paths
    with conn.cursor() as cur:
        cur.execute("TRUNCATE clean.ref_villes, clean.ref_synonymes, clean.ref_mapping_etudiants, clean.ref_mapping_contenus")
        for ville, region in sn.CITY_TO_REGION.items():
            cur.execute("INSERT INTO clean.ref_villes VALUES (clean.cle(%s), %s, %s)", (ville, ville, region))
        for domaine, valeurs in SYNONYMES.items():
            for canonique, variantes in valeurs.items():
                for v in variantes:
                    cur.execute("""INSERT INTO clean.ref_synonymes (domaine, cle, valeur, variante)
                                   VALUES (%s, clean.cle(%s), %s, %s) ON CONFLICT DO NOTHING""", (domaine, v, canonique, v))
        with (paths.mappings_dir / MAPPING_ETUDIANTS_FILENAME).open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                cur.execute("INSERT INTO clean.ref_mapping_etudiants VALUES (%s, %s, %s)",
                            (r["id_etudiant"], r["matricule"], r["student_code"]))
        with (paths.mappings_dir / MAPPING_COURSES_FILENAME).open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                cur.execute("INSERT INTO clean.ref_mapping_contenus VALUES (%s, %s, %s, %s)",
                            (r["code_externe"], r["type_objet"], r["id_mysql"], r["code_module"]))
        comptes = {}
        for t in ("ref_villes", "ref_synonymes", "ref_mapping_etudiants", "ref_mapping_contenus"):
            cur.execute(f"SELECT COUNT(*) FROM clean.{t}")
            comptes[t] = cur.fetchone()[0]
    return comptes
