"""
common/config.py — Configuration centralisée (Lot L0)
=====================================================

Rôle
    Point d'entrée UNIQUE pour tous les paramètres du projet :
    - connexions aux 5 services Docker (pg_source, pg_dw, mysql, mongo, redis) ;
    - chemins du projet (data, mappings, logs) ;
    - paramètres de génération validés à l'Étape 2 (volumes, période,
      taux d'anomalies, graine).

Choix techniques
    - Les secrets sont lus dans docker/.env (même fichier que Docker Compose) :
      une seule source de vérité, aucun mot de passe dans le code.
    - Dataclasses « frozen » : la configuration ne peut pas être modifiée
      par erreur pendant l'exécution.
    - Les mots de passe sont exclus du repr() : ils n'apparaissent jamais
      dans les logs.
    - Les mots de passe ne sont vérifiés qu'au moment de la connexion
      (require_password) : on peut générer le référentiel sans base active.

Utilisation
    from common.config import get_settings
    settings = get_settings()
    settings.pg_source.connect_kwargs()
    settings.generation.nb_etudiants_pg
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

try:  # python-dotenv est optionnel : sans lui, seules les variables système sont lues
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# -----------------------------------------------------------------------------
# Chemins de base
# -----------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
ENV_FILE: Path = PROJECT_ROOT / "docker" / ".env"

DEFAULT_SEED: int = 2026


class ConfigError(RuntimeError):
    """Erreur de configuration (variable manquante, valeur invalide...)."""


# -----------------------------------------------------------------------------
# Lecture des variables d'environnement
# -----------------------------------------------------------------------------
def _load_env_file() -> None:
    """Charge docker/.env s'il existe, sans écraser les variables déjà définies."""
    if load_dotenv is not None and ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name, str(default))
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"La variable {name} doit être un entier (valeur lue : {raw!r}).") from exc


# -----------------------------------------------------------------------------
# Configurations de connexion
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class _BaseConnection:
    """Champs communs. `password` est masqué dans repr() pour ne jamais être loggé."""

    service: str
    host: str
    port: int
    user: str
    password: str = field(repr=False, default="")

    def require_password(self) -> None:
        """Vérifie qu'un mot de passe réel est configuré avant toute connexion."""
        if not self.password or self.password.startswith("change_me"):
            raise ConfigError(
                f"[{self.service}] mot de passe absent ou non modifié. "
                f"Copiez docker/.env.example en docker/.env et renseignez-le."
            )


@dataclass(frozen=True)
class PostgresConfig(_BaseConnection):
    database: str = ""

    def connect_kwargs(self) -> dict:
        """Paramètres pour psycopg2.connect(**kwargs)."""
        self.require_password()
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            "connect_timeout": 5,
        }


@dataclass(frozen=True)
class MySQLConfig(_BaseConnection):
    database: str = ""

    def connect_kwargs(self) -> dict:
        """Paramètres pour pymysql.connect(**kwargs)."""
        self.require_password()
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": "utf8mb4",
            "connect_timeout": 5,
        }


@dataclass(frozen=True)
class MongoConfig(_BaseConnection):
    database: str = ""

    def uri(self) -> str:
        """URI MongoDB (utilisateur root créé par l'image : authSource=admin)."""
        self.require_password()
        return (
            f"mongodb://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}?authSource=admin"
        )

    def safe_uri(self) -> str:
        """URI sans mot de passe, pour les logs."""
        return f"mongodb://{self.user}:***@{self.host}:{self.port}/{self.database}?authSource=admin"


@dataclass(frozen=True)
class RedisConfig(_BaseConnection):
    db: int = 0

    def connect_kwargs(self) -> dict:
        """Paramètres pour redis.Redis(**kwargs)."""
        self.require_password()
        return {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "password": self.password,
            "decode_responses": True,
            "socket_connect_timeout": 5,
        }


# -----------------------------------------------------------------------------
# Chemins
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class PathsConfig:
    root: Path = PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def referential_dir(self) -> Path:
        """Référentiel maître caché : NE DOIT PAS être lu par le pipeline ETL."""
        return self.data_dir / "referential"

    @property
    def mappings_dir(self) -> Path:
        """Tables de correspondance livrées hors sources (artefacts d'intégration)."""
        return self.root / "mappings"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def generated_dir(self) -> Path:
        """Fichiers intermédiaires produits par les générateurs (un dossier par source)."""
        return self.data_dir / "generated"

    @property
    def anomalies_dir(self) -> Path:
        """Journaux d'anomalies injectées : vérités terrain pour la Phase 15, jamais lus par l'ETL."""
        return self.data_dir / "anomalies"

    @property
    def reports_dir(self) -> Path:
        """Rapports de vérification (portes G1...)."""
        return self.data_dir / "reports"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.referential_dir, self.mappings_dir, self.logs_dir,
                          self.generated_dir, self.anomalies_dir, self.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# Paramètres de génération (décisions validées à l'Étape 2)
# -----------------------------------------------------------------------------
_ACADEMIC_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


@dataclass(frozen=True)
class GenerationConfig:
    """Volumes et conventions validés. Toute modification doit être documentée."""

    seed: int = DEFAULT_SEED

    # Point 1 validé : couverture LMS en chiffres absolus
    nb_etudiants_pg: int = 10_000
    nb_pg_avec_lms: int = 9_000
    nb_lms_orphelins: int = 500

    # Taux d'anomalies par type (2 à 5 %)
    taux_anomalie_min: float = 0.02
    taux_anomalie_max: float = 0.05

    # Période couverte : 3 années académiques, rentrée au 1er octobre
    annees_academiques: tuple[str, ...] = ("2023-2024", "2024-2025", "2025-2026")
    # Répartition indicative de l'année d'entrée (convention de génération)
    poids_annees_entree: tuple[float, ...] = (0.36, 0.33, 0.31)
    rentree_mois: int = 10
    rentree_jour: int = 1
    periode_debut: date = date(2023, 10, 1)
    periode_fin: date = date(2026, 9, 30)

    pays_defaut: str = "Sénégal"
    devise: str = "XOF"

    # --- Valeurs dérivées ---------------------------------------------------
    @property
    def nb_pg_sans_lms(self) -> int:
        return self.nb_etudiants_pg - self.nb_pg_avec_lms

    @property
    def nb_student_codes(self) -> int:
        return self.nb_pg_avec_lms + self.nb_lms_orphelins

    def rentree(self, annee_academique: str) -> date:
        """Date de rentrée d'une année académique, ex. '2023-2024' -> 2023-10-01."""
        match = _ACADEMIC_YEAR_RE.match(annee_academique)
        if not match or int(match.group(2)) != int(match.group(1)) + 1:
            raise ConfigError(f"Année académique invalide : {annee_academique!r} (attendu 'AAAA-AAAA+1').")
        return date(int(match.group(1)), self.rentree_mois, self.rentree_jour)

    def validate(self) -> None:
        """Contrôle la cohérence interne ; lève ConfigError avec toutes les erreurs."""
        errors: list[str] = []
        if self.nb_etudiants_pg <= 0:
            errors.append("nb_etudiants_pg doit être > 0")
        if not 0 <= self.nb_pg_avec_lms <= self.nb_etudiants_pg:
            errors.append("nb_pg_avec_lms doit être compris entre 0 et nb_etudiants_pg")
        if self.nb_lms_orphelins < 0:
            errors.append("nb_lms_orphelins doit être >= 0")
        if self.nb_student_codes > 999_999:
            errors.append("le format LMS-XXXXXX limite le nombre de student_code à 999 999")
        if not 0 < self.taux_anomalie_min <= self.taux_anomalie_max < 1:
            errors.append("taux d'anomalies : 0 < min <= max < 1")
        if len(self.poids_annees_entree) != len(self.annees_academiques):
            errors.append("poids_annees_entree doit avoir autant de valeurs que annees_academiques")
        if any(p < 0 for p in self.poids_annees_entree) or sum(self.poids_annees_entree) <= 0:
            errors.append("poids_annees_entree doit contenir des valeurs positives")
        try:
            for annee in self.annees_academiques:
                self.rentree(annee)
            if self.annees_academiques and self.periode_debut != self.rentree(self.annees_academiques[0]):
                errors.append("periode_debut doit correspondre à la rentrée de la première année")
        except ConfigError as exc:
            errors.append(str(exc))
        if self.periode_debut >= self.periode_fin:
            errors.append("periode_debut doit précéder periode_fin")
        if errors:
            raise ConfigError("Configuration de génération invalide : " + " ; ".join(errors))


# -----------------------------------------------------------------------------
# Agrégat
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    paths: PathsConfig
    pg_source: PostgresConfig
    pg_dw: PostgresConfig
    mysql: MySQLConfig
    mongo: MongoConfig
    redis: RedisConfig
    generation: GenerationConfig
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Construit (une seule fois) la configuration à partir de docker/.env."""
    _load_env_file()

    settings = Settings(
        paths=PathsConfig(),
        pg_source=PostgresConfig(
            service="pg_source",
            host=_get("PG_SOURCE_HOST", "localhost"),
            port=_get_int("PG_SOURCE_PORT", 5435),
            user=_get("PG_SOURCE_USER", "edusmart"),
            password=_get("PG_SOURCE_PASSWORD", ""),
            database=_get("PG_SOURCE_DB", "edusmart_academic"),
        ),
        pg_dw=PostgresConfig(
            service="pg_dw",
            host=_get("PG_DW_HOST", "localhost"),
            port=_get_int("PG_DW_PORT", 5434),
            user=_get("PG_DW_USER", "edusmart_dw"),
            password=_get("PG_DW_PASSWORD", ""),
            database=_get("PG_DW_DB", "edusmart_dw"),
        ),
        mysql=MySQLConfig(
            service="mysql",
            host=_get("MYSQL_HOST", "localhost"),
            port=_get_int("MYSQL_PORT", 3307),
            user=_get("MYSQL_USER", "edusmart"),
            password=_get("MYSQL_PASSWORD", ""),
            database=_get("MYSQL_DB", "edusmart_learning"),
        ),
        mongo=MongoConfig(
            service="mongo",
            host=_get("MONGO_HOST", "localhost"),
            port=_get_int("MONGO_PORT", 27018),
            user=_get("MONGO_ROOT_USER", "edusmart"),
            password=_get("MONGO_ROOT_PASSWORD", ""),
            database=_get("MONGO_DB", "edusmart_mobile"),
        ),
        redis=RedisConfig(
            service="redis",
            host=_get("REDIS_HOST", "localhost"),
            port=_get_int("REDIS_PORT", 6380),
            user="default",
            password=_get("REDIS_PASSWORD", ""),
            db=_get_int("REDIS_DB", 0),
        ),
        generation=GenerationConfig(seed=_get_int("EDUSMART_SEED", DEFAULT_SEED)),
        log_level=(_get("LOG_LEVEL", "INFO") or "INFO").upper(),
    )
    settings.generation.validate()
    return settings
