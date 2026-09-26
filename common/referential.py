"""
common/referential.py — Référentiel maître caché (Lot L1)
=========================================================

Pourquoi un référentiel maître ?
    Aucune source ne relie id_etudiant/matricule (PostgreSQL) à student_code
    (MySQL, MongoDB, Redis). Pour que les 5 générateurs produisent des données
    COHÉRENTES entre elles (le même étudiant fictif habite la même ville dans
    PostgreSQL et se connecte depuis cette ville dans MongoDB), ils puisent
    tous dans ce référentiel unique, généré une seule fois par graine.

Ce que produit ce module
    1. data/referential/referentiel_maitre.csv  (CACHÉ)
       10 500 personnes : 10 000 étudiants PostgreSQL + 500 comptes LMS orphelins.
       Il sert aux générateurs (L2) et aux tests de vérification (Phase 15).
       Le pipeline ETL ne doit JAMAIS le lire : en situation réelle, il n'existe pas.

    2. mappings/mapping_etudiants.csv  (LIVRÉ, artefact d'intégration)
       Uniquement les 9 000 correspondances connues matricule <-> student_code.
       Les 1 000 étudiants sans compte LMS et les 500 codes orphelins n'y
       figurent PAS : l'ETL devra les découvrir par anti-jointure, comme un
       vrai analyste BI (constat « nombre réel d'étudiants », Phases 1 et 11).

    3. mappings/mapping_courses.csv  (SQUELETTE)
       En-tête seul ; il sera rempli lors de la génération MySQL (L2-b).

Conventions (décisions validées, voir README)
    - matricule     : ESM-AAAA-NNNNN (AAAA = année de rentrée), unique.
    - student_code  : LMS-XXXXXX (6 chiffres). Numéros MÉLANGÉS : le code LMS
                      ne se déduit pas du matricule (identifiants réellement
                      indépendants, comme dans deux systèmes distincts).
    - id_etudiant   : UUID v4 reproductible (common/seed.py).
    - Attributs d'identité (nom, prénom, sexe canonique M/F, date de
      naissance, ville, région, année d'entrée) : ajoutés au périmètre demandé
      pour que toutes les sources décrivent les MÊMES personnes. Les variantes
      de sexe (« Homme », « 1 »...) seront introduites comme anomalies en L2.
    - Âge : 18 à 35 ans à la rentrée de l'année d'entrée.

Exécution (depuis la racine du projet)
    python -m common.referential
"""

from __future__ import annotations

import csv
import os
import re
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, fields
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from common import senegalese_data as sn
from common.config import GenerationConfig, get_settings
from common.logger import get_logger, log_step
from common.seed import deterministic_uuid, get_rng

logger = get_logger("referential")

# -----------------------------------------------------------------------------
# Constantes
# -----------------------------------------------------------------------------
STATUT_APPARIE = "APPARIE"            # étudiant PG avec compte LMS
STATUT_SANS_LMS = "SANS_LMS"          # étudiant PG sans compte LMS
STATUT_LMS_ORPHELIN = "LMS_ORPHELIN"  # compte LMS absent de PostgreSQL
STATUTS = (STATUT_APPARIE, STATUT_SANS_LMS, STATUT_LMS_ORPHELIN)

MATRICULE_RE = re.compile(r"^ESM-\d{4}-\d{5}$")
STUDENT_CODE_RE = re.compile(r"^LMS-\d{6}$")

AGE_MIN, AGE_MAX = 18, 35

REFERENTIAL_FILENAME = "referentiel_maitre.csv"
MAPPING_ETUDIANTS_FILENAME = "mapping_etudiants.csv"
MAPPING_ETUDIANTS_COLUMNS = ["id_etudiant", "matricule", "student_code"]
MAPPING_COURSES_FILENAME = "mapping_courses.csv"
MAPPING_COURSES_COLUMNS = [
    "type_objet",             # MODULE, COURSE ou QUIZ
    "code_externe",           # MOD-XX-01, COURSE-n, QUIZ-n (codes MongoDB / Redis)
    "id_mysql",               # UUID MySQL (id_module, id_cours, id_quiz)
    "code_module",            # module parent
    "statut_correspondance",  # APPARIE ou ORPHELIN
]


class ReferentialError(Exception):
    """Erreur de génération, de validation ou de lecture du référentiel."""


@dataclass(frozen=True)
class MasterStudent:
    """Une personne du référentiel maître (étudiant PG et/ou compte LMS)."""

    ref_id: int
    id_etudiant: str | None
    matricule: str | None
    student_code: str | None
    statut_correspondance: str
    nom: str
    prenom: str
    sexe: str
    date_naissance: str  # ISO AAAA-MM-JJ
    ville: str
    region: str
    pays: str
    annee_academique_entree: str


REFERENTIAL_COLUMNS = [f.name for f in fields(MasterStudent)]


# -----------------------------------------------------------------------------
# Génération
# -----------------------------------------------------------------------------
def _random_birth_date(rng, reference: date) -> date:
    """Date de naissance telle que l'âge à `reference` soit entre AGE_MIN et AGE_MAX."""
    oldest = reference.replace(year=reference.year - AGE_MAX - 1) + timedelta(days=1)
    youngest = reference.replace(year=reference.year - AGE_MIN)
    return oldest + timedelta(days=rng.randint(0, (youngest - oldest).days))


def build_referential(gen: GenerationConfig | None = None) -> list[MasterStudent]:
    """Construit le référentiel en mémoire (déterministe pour une graine donnée)."""
    gen = gen or get_settings().generation
    gen.validate()
    rng = get_rng("referential", seed=gen.seed)

    nb_pg = gen.nb_etudiants_pg
    total = nb_pg + gen.nb_lms_orphelins

    # 1. Étudiants PG sans compte LMS : tirés au hasard (et non les derniers)
    sans_lms = set(rng.sample(range(nb_pg), gen.nb_pg_sans_lms))

    # 2. Numéros LMS 1..N mélangés : aucun lien d'ordre avec le matricule
    numeros_lms = list(range(1, gen.nb_student_codes + 1))
    rng.shuffle(numeros_lms)
    iter_lms = iter(numeros_lms)

    compteurs_matricule: Counter[str] = Counter()
    records: list[MasterStudent] = []

    for i in range(total):
        est_pg = i < nb_pg
        sexe = sn.random_sexe(rng)
        prenom = sn.random_first_name(rng, sexe)
        nom = sn.random_last_name(rng)
        region, ville = sn.random_region_and_city(rng)
        annee = rng.choices(gen.annees_academiques, weights=gen.poids_annees_entree, k=1)[0]
        naissance = _random_birth_date(rng, gen.rentree(annee))

        if est_pg:
            id_etudiant = deterministic_uuid(rng)
            compteurs_matricule[annee] += 1
            matricule = f"ESM-{annee[:4]}-{compteurs_matricule[annee]:05d}"
            if i in sans_lms:
                student_code, statut = None, STATUT_SANS_LMS
            else:
                student_code, statut = f"LMS-{next(iter_lms):06d}", STATUT_APPARIE
        else:
            id_etudiant, matricule = None, None
            student_code, statut = f"LMS-{next(iter_lms):06d}", STATUT_LMS_ORPHELIN

        records.append(MasterStudent(
            ref_id=i + 1,
            id_etudiant=id_etudiant,
            matricule=matricule,
            student_code=student_code,
            statut_correspondance=statut,
            nom=nom,
            prenom=prenom,
            sexe=sexe,
            date_naissance=naissance.isoformat(),
            ville=ville,
            region=region,
            pays=gen.pays_defaut,
            annee_academique_entree=annee,
        ))
    return records


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------
def _duplicates(values: Iterable[str | None]) -> list[str]:
    counts = Counter(v for v in values if v is not None)
    return [v for v, n in counts.items() if n > 1]


def validate_referential(records: Sequence[MasterStudent], gen: GenerationConfig | None = None) -> list[str]:
    """Contrôle complet ; retourne la liste des erreurs (vide = référentiel valide)."""
    gen = gen or get_settings().generation
    errors: list[str] = []

    # Volumes (point 1 validé)
    statuts = Counter(r.statut_correspondance for r in records)
    attendus = {
        STATUT_APPARIE: gen.nb_pg_avec_lms,
        STATUT_SANS_LMS: gen.nb_pg_sans_lms,
        STATUT_LMS_ORPHELIN: gen.nb_lms_orphelins,
    }
    for statut, attendu in attendus.items():
        if statuts.get(statut, 0) != attendu:
            errors.append(f"{statut} : {statuts.get(statut, 0)} au lieu de {attendu}")
    inconnus = set(statuts) - set(STATUTS)
    if inconnus:
        errors.append(f"statuts inconnus : {sorted(inconnus)}")

    # Unicité
    for label, values in (("id_etudiant", [r.id_etudiant for r in records]),
                          ("matricule", [r.matricule for r in records]),
                          ("student_code", [r.student_code for r in records])):
        dups = _duplicates(values)
        if dups:
            errors.append(f"{label} en double : {dups[:5]}")

    # Cohérence ligne à ligne
    for r in records:
        prefix = f"ref_id={r.ref_id}"
        if r.statut_correspondance == STATUT_LMS_ORPHELIN:
            if r.id_etudiant or r.matricule:
                errors.append(f"{prefix} : un orphelin LMS ne doit pas exister dans PostgreSQL")
        else:
            try:
                if uuid.UUID(r.id_etudiant or "").version != 4:
                    errors.append(f"{prefix} : UUID non version 4")
            except ValueError:
                errors.append(f"{prefix} : id_etudiant n'est pas un UUID")
            if not MATRICULE_RE.match(r.matricule or ""):
                errors.append(f"{prefix} : matricule mal formé ({r.matricule})")
        if r.statut_correspondance == STATUT_SANS_LMS:
            if r.student_code is not None:
                errors.append(f"{prefix} : un étudiant SANS_LMS ne doit pas avoir de student_code")
        elif not STUDENT_CODE_RE.match(r.student_code or ""):
            errors.append(f"{prefix} : student_code mal formé ({r.student_code})")
        if sn.region_of_city(r.ville) != r.region:
            errors.append(f"{prefix} : la ville {r.ville} n'appartient pas à la région {r.region}")
        if r.sexe not in ("M", "F"):
            errors.append(f"{prefix} : sexe non canonique ({r.sexe})")
        if r.annee_academique_entree not in gen.annees_academiques:
            errors.append(f"{prefix} : année d'entrée hors période ({r.annee_academique_entree})")
        else:
            rentree = gen.rentree(r.annee_academique_entree)
            naissance = date.fromisoformat(r.date_naissance)
            age = rentree.year - naissance.year - ((rentree.month, rentree.day) < (naissance.month, naissance.day))
            if not AGE_MIN <= age <= AGE_MAX:
                errors.append(f"{prefix} : âge {age} ans hors de [{AGE_MIN}, {AGE_MAX}]")
        if len(errors) > 50:  # inutile de tout lister si le référentiel est cassé
            errors.append("... (liste tronquée)")
            break
    return errors


# -----------------------------------------------------------------------------
# Écriture et lecture
# -----------------------------------------------------------------------------
def _atomic_write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence]) -> int:
    """
    Écrit un CSV de façon atomique : fichier temporaire puis renommage.
    Un fichier à moitié écrit (crash, disque plein) ne remplace jamais une
    version valide. Retourne le nombre de lignes de données écrites.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for row in rows:
                writer.writerow(["" if v is None else v for v in row])
                count += 1
        os.replace(tmp_name, path)
    except OSError as exc:
        Path(tmp_name).unlink(missing_ok=True)
        raise ReferentialError(f"Écriture impossible de {path} : {exc}") from exc
    return count


def write_referential(records: Sequence[MasterStudent], directory: Path) -> Path:
    path = directory / REFERENTIAL_FILENAME
    n = _atomic_write_csv(path, REFERENTIAL_COLUMNS,
                          ([getattr(r, c) for c in REFERENTIAL_COLUMNS] for r in records))
    logger.info("Référentiel maître écrit : %s (%d lignes)", path, n)
    return path


def write_mapping_etudiants(records: Sequence[MasterStudent], directory: Path) -> Path:
    """Seules les correspondances CONNUES (APPARIE), triées par matricule."""
    pairs = sorted((r for r in records if r.statut_correspondance == STATUT_APPARIE),
                   key=lambda r: r.matricule or "")
    path = directory / MAPPING_ETUDIANTS_FILENAME
    n = _atomic_write_csv(path, MAPPING_ETUDIANTS_COLUMNS,
                          ((r.id_etudiant, r.matricule, r.student_code) for r in pairs))
    logger.info("Table de correspondance écrite : %s (%d paires)", path, n)
    return path


def init_mapping_courses(directory: Path) -> Path:
    """
    Crée le squelette de mapping_courses.csv (en-tête seul).
    Ne remplace JAMAIS un fichier déjà rempli par la génération MySQL.
    """
    path = directory / MAPPING_COURSES_FILENAME
    if path.exists():
        try:
            with path.open(encoding="utf-8") as handle:
                nb_lignes = sum(1 for _ in handle)
        except OSError as exc:
            raise ReferentialError(f"Lecture impossible de {path} : {exc}") from exc
        if nb_lignes > 1:
            logger.info("mapping_courses.csv contient déjà %d lignes : conservé tel quel.", nb_lignes - 1)
            return path
    _atomic_write_csv(path, MAPPING_COURSES_COLUMNS, [])
    logger.info("Squelette créé : %s (rempli en L2-b, génération MySQL)", path)
    return path


def load_referential(path: Path | None = None) -> list[MasterStudent]:
    """Relit le référentiel (utilisé par les générateurs L2 et les tests)."""
    path = path or get_settings().paths.referential_dir / REFERENTIAL_FILENAME
    if not path.exists():
        raise ReferentialError(f"{path} introuvable. Exécutez d'abord : python -m common.referential")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != REFERENTIAL_COLUMNS:
                raise ReferentialError(f"Colonnes inattendues dans {path} : {reader.fieldnames}")
            return [
                MasterStudent(**{
                    **{k: (v if v != "" else None) for k, v in row.items()},
                    "ref_id": int(row["ref_id"]),
                })
                for row in reader
            ]
    except (OSError, ValueError, TypeError) as exc:
        raise ReferentialError(f"Lecture impossible de {path} : {exc}") from exc


def summarize(records: Sequence[MasterStudent]) -> dict:
    """Statistiques descriptives pour le journal et la documentation."""
    return {
        "total": len(records),
        "par_statut": dict(Counter(r.statut_correspondance for r in records)),
        "par_sexe": dict(Counter(r.sexe for r in records)),
        "par_annee_entree": dict(sorted(Counter(r.annee_academique_entree for r in records).items())),
        "par_region": dict(Counter(r.region for r in records).most_common()),
    }


# -----------------------------------------------------------------------------
# Point d'entrée
# -----------------------------------------------------------------------------
def main() -> int:
    settings = get_settings()
    try:
        problems = sn.validate_reference_data()
        if problems:
            raise ReferentialError("Listes sénégalaises incohérentes : " + " ; ".join(problems))

        settings.paths.ensure_directories()
        gen = settings.generation
        logger.info("Graine globale : %d", gen.seed)

        with log_step(logger, "Construction du référentiel maître"):
            records = build_referential(gen)

        with log_step(logger, "Validation du référentiel maître"):
            errors = validate_referential(records, gen)
            if errors:
                raise ReferentialError("Référentiel invalide :\n  - " + "\n  - ".join(errors))

        with log_step(logger, "Écriture des fichiers"):
            write_referential(records, settings.paths.referential_dir)
            write_mapping_etudiants(records, settings.paths.mappings_dir)
            init_mapping_courses(settings.paths.mappings_dir)

        stats = summarize(records)
        logger.info("Total : %d personnes", stats["total"])
        logger.info("Par statut : %s", stats["par_statut"])
        logger.info("Par sexe : %s", stats["par_sexe"])
        logger.info("Par année d'entrée : %s", stats["par_annee_entree"])
        logger.info("Par région : %s", stats["par_region"])
        return 0
    except ReferentialError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:  # erreur imprévue : trace complète dans les logs
        logger.exception("Erreur inattendue pendant la génération du référentiel")
        return 2


if __name__ == "__main__":
    sys.exit(main())
