"""
pipeline/registry.py — Registre des objets extraits (Lot L4)
===========================================================

Source UNIQUE de vérité du pipeline : pour chacun des 17 objets sources
(5 tables PostgreSQL, 6 tables MySQL, 4 fichiers CSV, 1 collection MongoDB,
1 base Redis), elle donne :
    - la source et l'objet d'origine ;
    - la table de staging cible (couche bronze) ;
    - les colonnes, reprises des DÉFINITIONS DU VOLET A (et non recopiées) :
      impossible que l'extraction, le chargement et les DDL divergent ;
    - la clé d'ordre (ordre stable des lignes : _row_number reproductible).

Toutes les colonnes source sont chargées en TEXT (JSONB pour MongoDB et Redis) :
aucune valeur n'est interprétée avant la couche clean (principe ELT, doc 04).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sources.s1_postgresql.generate_data import COLUMNS as S1_COLUMNS
from sources.s2_mysql.generate_data import COLUMNS as S2_COLUMNS
from sources.s3_csv.create_source import FILE_ORDER as S3_FILES
from sources.s3_csv.create_source import SCHEMAS as S3_SCHEMAS

PIPELINE_VERSION = "1.0.0"
STAGING_SCHEMA = "staging"
NULL_MARKER = r"\N"                                   # valeur NULL dans les fichiers d'atterrissage
TECH_COLUMNS = ("_batch_id", "_source", "_extracted_at", "_row_number")


@dataclass(frozen=True)
class SourceObject:
    source: str                    # s1_postgresql, s2_mysql, s3_csv, s4_mongodb, s5_redis
    objet: str                     # table, fichier, collection ou « keys »
    technologie: str
    colonnes: tuple[str, ...]      # colonnes source (hors colonnes techniques)
    cle_ordre: str | None          # tri de l'extraction (None : ordre du fichier)
    colonnes_json: tuple[str, ...] = ()   # colonnes JSONB (MongoDB, Redis)
    encodage: str = "UTF-8"
    separateur: str = ""
    description: str = ""

    @property
    def stg_table(self) -> str:
        prefix = {"s1_postgresql": "pg", "s2_mysql": "mysql", "s3_csv": "csv",
                  "s4_mongodb": "mongo", "s5_redis": "redis"}[self.source]
        return f"stg_{prefix}_{self.objet}"

    @property
    def landing_file(self) -> str:
        return f"{self.objet}.csv"

    @property
    def toutes_colonnes(self) -> tuple[str, ...]:
        return self.colonnes + TECH_COLUMNS

    @property
    def version_schema(self) -> str:
        """Empreinte de la structure : change si une colonne est ajoutée, renommée ou retirée (Phase 6)."""
        return hashlib.md5("|".join(self.colonnes).encode("utf-8")).hexdigest()[:12]


_PK = {"etudiants": "id_etudiant", "filieres": "id_filiere", "classes": "id_classe",
       "inscriptions": "id_inscription", "paiements": "id_paiement",
       "modules": "id_module", "cours": "id_cours", "quiz": "id_quiz", "notes": "id_note",
       "progression": "id_progression", "temps_connexion": "id_connexion"}

_DESCRIPTIONS = {
    "etudiants": "Étudiants (gestion académique)", "filieres": "Formations proposées",
    "classes": "Classes par filière et année", "inscriptions": "Inscriptions étudiant / classe",
    "paiements": "Paiements des étudiants", "modules": "Modules de formation", "cours": "Cours des modules",
    "quiz": "Quiz des cours", "notes": "Résultats aux quiz", "progression": "Progression par module",
    "temps_connexion": "Historique des connexions", "enseignants": "Enseignants (export RH)",
    "departements": "Départements (export RH)", "salaires": "Salaires des enseignants (export RH)",
    "absences": "Absences des enseignants (export RH)",
}

OBJECTS: tuple[SourceObject, ...] = (
    *(SourceObject("s1_postgresql", t, "PostgreSQL 15", tuple(S1_COLUMNS[t]), _PK[t], description=_DESCRIPTIONS[t])
      for t in ("etudiants", "filieres", "classes", "inscriptions", "paiements")),
    *(SourceObject("s2_mysql", t, "MySQL 8.0", tuple(S2_COLUMNS[t]), _PK[t], description=_DESCRIPTIONS[t])
      for t in ("modules", "cours", "quiz", "notes", "progression", "temps_connexion")),
    *(SourceObject("s3_csv", k, "Fichier CSV", tuple(S3_SCHEMAS[k].entetes), None,
                   encodage=S3_SCHEMAS[k].encodage.upper(), separateur=S3_SCHEMAS[k].separateur,
                   description=_DESCRIPTIONS[k])
      for k in S3_FILES),
    SourceObject("s4_mongodb", "events", "MongoDB 6", ("_mongo_id", "event_id", "document"), "_id",
                 colonnes_json=("document",), description="Journaux de l'application mobile (document JSON complet)"),
    SourceObject("s5_redis", "keys", "Redis 7", ("cle", "type_redis", "valeur", "ttl"), "cle",
                 colonnes_json=("valeur",), description="Snapshot de toutes les clés (type, valeur, durée de vie)"),
)

SOURCES: tuple[str, ...] = ("s1_postgresql", "s2_mysql", "s3_csv", "s4_mongodb", "s5_redis")


def objects_of(source: str) -> list[SourceObject]:
    return [o for o in OBJECTS if o.source == source]


def get_object(source: str, objet: str) -> SourceObject:
    for o in OBJECTS:
        if o.source == source and o.objet == objet:
            return o
    raise KeyError(f"Objet inconnu : {source}.{objet}")


def staging_ddl() -> str:
    """DDL de la couche staging, produit depuis le registre (voir sql/staging/01_staging_tables.sql)."""
    blocs = [
        "-- =============================================================================",
        "-- EduSmart Data Warehouse — Couche STAGING (bronze), Lot L4",
        "-- Fichier GÉNÉRÉ depuis pipeline/registry.py (python -m pipeline.registry).",
        "-- Ne pas modifier à la main : un test vérifie qu'il correspond au registre.",
        "--",
        "-- Principe ELT : toutes les colonnes source en TEXT (JSONB pour MongoDB et",
        "-- Redis). Aucune valeur n'est interprétée ni corrigée à ce stade : un montant",
        "-- négatif, une date '12/09/2026' ou un sexe 'Garçon' se chargent sans erreur.",
        "-- Colonnes techniques : lot, source, instant d'extraction, rang de la ligne.",
        "-- =============================================================================",
        "",
        f"CREATE SCHEMA IF NOT EXISTS {STAGING_SCHEMA};",
        "",
    ]
    for o in OBJECTS:
        cols = [f"    {c:<20} {'JSONB' if c in o.colonnes_json else 'TEXT'}" for c in o.colonnes]
        cols += ["    _batch_id            TEXT      NOT NULL",
                 "    _source              TEXT      NOT NULL",
                 "    _extracted_at        TIMESTAMP NOT NULL",
                 "    _row_number          INTEGER   NOT NULL",
                 f"    CONSTRAINT pk_{o.stg_table} PRIMARY KEY (_batch_id, _row_number)"]
        blocs += [f"-- {o.source}.{o.objet} : {o.description}",
                  f"CREATE TABLE IF NOT EXISTS {STAGING_SCHEMA}.{o.stg_table} (", ",\n".join(cols), ");",
                  f"COMMENT ON TABLE {STAGING_SCHEMA}.{o.stg_table} IS "
                  f"'Bronze - {o.source}.{o.objet} ({o.technologie}), copie brute';", ""]
    return "\n".join(blocs)


if __name__ == "__main__":
    from pathlib import Path
    cible = Path(__file__).resolve().parent / "sql" / "staging" / "01_staging_tables.sql"
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(staging_ddl(), encoding="utf-8")
    print(f"{len(OBJECTS)} tables de staging écrites dans {cible}")
