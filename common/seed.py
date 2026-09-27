"""
common/seed.py — Reproductibilité (Lot L1)
==========================================

Rôle
    Garantir que deux exécutions produisent EXACTEMENT les mêmes données.
    C'est indispensable pour :
    - le snapshot Redis régénéré avant chaque extraction (point 6 validé) ;
    - les tests de la Phase 15 (valeurs attendues stables) ;
    - la démonstration SCD2 (le second chargement doit être comparable).

Choix techniques
    1. Une graine GLOBALE (EDUSMART_SEED, 2026 par défaut) dans docker/.env.
    2. Des générateurs INDÉPENDANTS par « espace de noms » (namespace) :
       get_rng("pg_etudiants"), get_rng("mysql_notes")...
       Ajouter un tirage dans un générateur ne décale pas les autres : modifier
       la génération MySQL ne change pas les données PostgreSQL.
    3. La dérivation utilise SHA-256 (et non hash()) : hash() varie d'une
       exécution Python à l'autre (PYTHONHASHSEED), SHA-256 jamais.
    4. uuid.uuid4() n'est pas reproductible (il lit l'aléa du système).
       deterministic_uuid(rng) fabrique un UUID version 4 valide à partir
       d'un générateur graine.

Utilisation
    from common.seed import get_rng, get_faker, deterministic_uuid
    rng = get_rng("referential")
    fake = get_faker("pg_etudiants")
    id_etudiant = deterministic_uuid(rng)
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, timedelta

from common.config import get_settings


def get_global_seed() -> int:
    """Graine globale définie dans docker/.env (EDUSMART_SEED)."""
    return get_settings().generation.seed


def derive_seed(namespace: str, seed: int | None = None) -> int:
    """
    Dérive une graine entière stable pour un espace de noms.

    derive_seed("referential") renvoie toujours la même valeur pour une même
    graine globale, et une valeur différente pour chaque namespace.
    """
    if not namespace or not isinstance(namespace, str):
        raise ValueError("Le namespace doit être une chaîne non vide.")
    base = get_global_seed() if seed is None else seed
    digest = hashlib.sha256(f"{base}:{namespace}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)  # 64 bits suffisent


def get_rng(namespace: str, seed: int | None = None) -> random.Random:
    """Générateur aléatoire indépendant et reproductible."""
    return random.Random(derive_seed(namespace, seed))


def get_faker(namespace: str, locale: str = "fr_FR", seed: int | None = None):
    """
    Instance Faker graine pour un espace de noms.
    Faker est importé ici (import paresseux) pour que les modules qui n'en
    ont pas besoin ne dépendent pas de lui.
    """
    try:
        from faker import Faker
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Faker n'est pas installé : pip install -r requirements.txt") from exc
    fake = Faker(locale)
    fake.seed_instance(derive_seed(namespace, seed))
    return fake


def deterministic_uuid(rng: random.Random) -> str:
    """UUID version 4 valide, mais reproductible car tiré d'un générateur graine."""
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def random_date(rng: random.Random, start: date, end: date) -> date:
    """
    Date uniforme entre start et end (inclus), SANS conversion de fuseau horaire.

    Pourquoi ne pas utiliser fake.date_between_dates() ? Faker convertit via le
    fuseau horaire de la machine et, sous Windows, ignore silencieusement une
    OSError pour les dates antérieures à 1970 : la même graine donnait alors
    des dates décalées d'un jour sous Windows (constaté en L4 sur la Source 3).
    Ici, seul un nombre de jours est tiré : le résultat est identique partout.
    """
    if end < start:
        raise ValueError(f"Intervalle de dates invalide : {start} > {end}")
    return start + timedelta(days=rng.randint(0, (end - start).days))
