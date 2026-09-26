"""
sources/s2_mysql/generate_data.py — Génération de la Source 2 (Lot L2-b)
=======================================================================

Produit les 6 tables de edusmart_learning (PDF Source 2) :
    modules (300) · cours (~800) · quiz (~1 000) · notes (~300 000)
    · progression (~60 000) · temps_connexion (~60 000)
et les correspondances de codes :
    mappings/mapping_courses.csv                (LIVRÉ : 95 % des cours et quiz)
    data/referential/referentiel_contenus.csv   (CACHÉ : 100 %, pour MongoDB/Redis)

Population : les 9 500 comptes LMS du référentiel maître (9 000 APPARIE +
500 LMS_ORPHELIN). Les 1 000 étudiants SANS_LMS n'apparaissent pas ici.

Cohérence avec PostgreSQL (lecture de la vérité terrain, jamais par l'ETL)
    Le générateur recalcule en mémoire les données PROPRES de la Source 1
    (même graine) pour connaître la filière et le parcours de chaque étudiant :
    - 70 % de ses modules relèvent de la catégorie de son département ;
    - son activité commence à la rentrée de son année d'entrée et s'arrête
      à la fin de son parcours (diplôme), au cours de l'année d'abandon, ou
      à la date de référence (15/09/2026).
    Les 500 orphelins LMS ont une catégorie tirée au hasard.

Exécution : python -m sources.s2_mysql.generate_data
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from common.academic_catalog import FILIERES_PAR_CODE
from common.config import GenerationConfig, get_settings
from common.learning_catalog import (APPAREILS, CATEGORIES, DEPARTEMENT_VERS_CATEGORIE, LECONS,
                                     MODULES_PAR_CATEGORIE, NAVIGATEURS_MOBILE, NAVIGATEURS_PC,
                                     NIVEAU_LABEL, NIVEAUX_MODULE, THEMES, TYPES_COURS, course_code,
                                     module_code, quiz_code, validate_learning_catalog)
from common.logger import get_logger, log_step
from common.referential import (MAPPING_COURSES_COLUMNS, MAPPING_COURSES_FILENAME, STATUT_LMS_ORPHELIN,
                                STATUT_SANS_LMS, MasterStudent, _atomic_write_csv, load_referential)
from common.seed import deterministic_uuid, get_faker, get_rng
from sources.s2_mysql.anomalies import SOURCE, inject_anomalies, measure_anomalies

logger = get_logger("s2_generate")

TABLE_ORDER = ("modules", "cours", "quiz", "notes", "progression", "temps_connexion")
COLUMNS: dict[str, list[str]] = {
    "modules": ["id_module", "code_module", "nom_module", "categorie", "niveau", "duree_heures", "actif"],
    "cours": ["id_cours", "id_module", "titre", "ordre", "duree_minutes", "type_cours", "statut"],
    "quiz": ["id_quiz", "id_cours", "titre", "nb_questions", "score_max", "duree_minutes"],
    "notes": ["id_note", "id_quiz", "student_code", "date_passage", "score", "tentative", "valide"],
    "progression": ["id_progression", "student_code", "id_module", "pourcentage", "dernier_cours", "date_maj"],
    "temps_connexion": ["id_connexion", "student_code", "date_connexion", "date_deconnexion", "duree_minutes",
                        "appareil", "navigateur", "adresse_ip"],
}

# Cibles validées (Étape 2) pour la porte G1 ; modules : valeur exacte
TARGETS = {"modules": 300, "cours": 800, "quiz": 1_000, "notes": 300_000,
           "progression": 60_000, "temps_connexion": 60_000}
EXACT_TARGETS = {"modules"}
TOLERANCE = 0.05

REFERENTIEL_CONTENUS_FILENAME = "referentiel_contenus.csv"
REFERENTIEL_CONTENUS_COLUMNS = ["type_objet", "code_externe", "id_mysql", "code_module", "dans_mapping"]
TAUX_ABSENTS_MAPPING = 0.05  # décision validée : 5 % des cours et quiz absents du mapping

NULL = r"\N"  # marqueur NULL de LOAD DATA (MySQL)

# Paramètres de simulation (conventions de génération, documentées dans le README)
P_CATEGORIE_PREFEREE = 0.70
NB_MODULES_MIN, NB_MODULES_MAX = 2, 10
NB_CONNEXIONS_MIN, NB_CONNEXIONS_MAX = 2, 11
SEUIL_VALIDATION = 0.5          # 10/20
P_REPASSER_APRES_REUSSITE = 0.65  # repasser un quiz réussi pour améliorer sa note
TENTATIVES_MAX = (1, 2, 3, 4, 5)
POIDS_TENTATIVES_MAX = (5, 15, 30, 30, 20)


class GenerationError(Exception):
    """Erreur bloquante pendant la génération de la Source 2."""


@dataclass
class ProfilLMS:
    """Ce que le générateur sait d'un compte LMS (issu du référentiel et de la Source 1)."""

    student_code: str
    categorie_preferee: str
    debut: date
    fin: date


# -----------------------------------------------------------------------------
# Profils des étudiants (lien avec la Source 1)
# -----------------------------------------------------------------------------
def _parcours_pg(students: list[MasterStudent], gen: GenerationConfig) -> dict[str, dict]:
    """
    Recalcule les données PROPRES de PostgreSQL (même graine) et résume le
    parcours de chaque étudiant : département principal, début, fin d'activité.
    """
    from sources.s1_postgresql.generate_data import generate_clean  # import local : dépendance explicite

    pg_students = [s for s in students if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    tables = generate_clean(pg_students, gen)
    code_filiere = {c["id_classe"]: c["code_classe"].rsplit("-", 2)[0] for c in tables["classes"]}
    annee_classe = {c["id_classe"]: c["annee_academique"] for c in tables["classes"]}
    par_etudiant: dict[str, list[dict]] = defaultdict(list)
    for i in tables["inscriptions"]:
        par_etudiant[i["id_etudiant"]].append(i)

    resume = {}
    for id_etudiant, inscriptions in par_etudiant.items():
        inscriptions.sort(key=lambda i: i["date_inscription"])
        derniere = inscriptions[-1]
        annee = annee_classe[derniere["id_classe"]]
        rentree = gen.rentree(annee)
        if derniere["statut"] == "ABANDON":
            fin = rentree + timedelta(days=120)          # arrêt en cours d'année
        elif derniere["statut"] in ("DIPLOME", "INSCRIT", "SUSPENDU"):
            fin = date(rentree.year + 1, 9, 30)          # fin de l'année académique
        else:                                            # EN_COURS
            fin = gen.date_reference
        departement = FILIERES_PAR_CODE[code_filiere[inscriptions[0]["id_classe"]]].departement
        resume[id_etudiant] = {"categorie": DEPARTEMENT_VERS_CATEGORIE[departement],
                               "debut": gen.rentree(annee_classe[inscriptions[0]["id_classe"]]),
                               "fin": min(fin, gen.date_reference)}
    return resume


def build_profils(students: list[MasterStudent], gen: GenerationConfig) -> list[ProfilLMS]:
    rng = get_rng(f"{SOURCE}_profils", seed=gen.seed)
    parcours = _parcours_pg(students, gen)
    profils = []
    for s in students:
        if s.statut_correspondance == STATUT_SANS_LMS:
            continue
        if s.statut_correspondance == STATUT_LMS_ORPHELIN:
            profils.append(ProfilLMS(s.student_code, rng.choice(CATEGORIES),
                                     gen.rentree(s.annee_academique_entree), gen.date_reference))
        else:
            p = parcours[s.id_etudiant]
            profils.append(ProfilLMS(s.student_code, p["categorie"], p["debut"], p["fin"]))
    return profils


# -----------------------------------------------------------------------------
# Contenus : modules, cours, quiz
# -----------------------------------------------------------------------------
def build_contenus(rng: random.Random) -> tuple[list[dict], list[dict], list[dict]]:
    modules, cours, quiz = [], [], []
    for categorie in CATEGORIES:
        combinaisons = [(theme, niveau) for theme in THEMES[categorie] for niveau in NIVEAUX_MODULE]
        choisies = rng.sample(combinaisons, MODULES_PAR_CATEGORIE[categorie])
        choisies.sort(key=lambda tn: (THEMES[categorie].index(tn[0]), NIVEAUX_MODULE.index(tn[1])))
        for numero, (theme, niveau) in enumerate(choisies, start=1):
            duree = {"DEBUTANT": (10, 20), "INTERMEDIAIRE": (15, 30), "AVANCE": (20, 40)}[niveau]
            modules.append({
                "id_module": deterministic_uuid(rng),
                "code_module": module_code(categorie, numero),
                "nom_module": f"{theme} - {NIVEAU_LABEL[niveau]}",
                "categorie": categorie,
                "niveau": niveau,
                "duree_heures": rng.randint(*duree),
                "actif": True,
            })

    for m in modules:
        nb_cours = rng.choices((1, 2, 3, 4, 5), weights=(10, 35, 35, 15, 5), k=1)[0]
        lecons = rng.sample(LECONS, nb_cours)
        for ordre, lecon in enumerate(lecons, start=1):
            type_cours = rng.choices(TYPES_COURS, weights=(50, 20, 20, 10), k=1)[0]
            duree = {"Vidéo": (10, 45), "PDF": (15, 60), "TP": (30, 120), "Projet": (60, 240)}[type_cours]
            cours.append({
                "id_cours": deterministic_uuid(rng),
                "id_module": m["id_module"],
                "titre": f"{m['nom_module']} - Leçon {ordre} : {lecon}",
                "ordre": ordre,
                "duree_minutes": rng.randint(*duree),
                "type_cours": type_cours,
                "statut": "PUBLIE",
                "_code_module": m["code_module"],
            })

    for c in cours:
        nb_quiz = rng.choices((0, 1, 2), weights=(15, 45, 40), k=1)[0]
        for k in range(1, nb_quiz + 1):
            nb_questions = rng.randint(5, 30)
            quiz.append({
                "id_quiz": deterministic_uuid(rng),
                "id_cours": c["id_cours"],
                "titre": f"Quiz {k} - {c['titre'].split(' - Leçon')[0]} (Leçon {c['ordre']})"[:150],
                "nb_questions": nb_questions,
                "score_max": rng.choices((20.0, 10.0, 100.0), weights=(70, 15, 15), k=1)[0],
                "duree_minutes": max(1, round(nb_questions * rng.uniform(1.0, 2.0))),
                "_code_module": c["_code_module"],
            })
    return modules, cours, quiz


def build_codes(modules, cours, quiz, rng: random.Random) -> list[dict]:
    """Codes externes (MongoDB/Redis) : MOD-XX-NN, COURSE-n, QUIZ-n ; 5 % hors mapping."""
    lignes = [{"type_objet": "MODULE", "code_externe": m["code_module"], "id_mysql": m["id_module"],
               "code_module": m["code_module"], "dans_mapping": True} for m in modules]
    for type_objet, objets, id_col, make_code in (("COURSE", cours, "id_cours", course_code),
                                                  ("QUIZ", quiz, "id_quiz", quiz_code)):
        absents = set(rng.sample(range(len(objets)), round(TAUX_ABSENTS_MAPPING * len(objets))))
        for n, obj in enumerate(objets, start=1):
            lignes.append({"type_objet": type_objet, "code_externe": make_code(n), "id_mysql": obj[id_col],
                           "code_module": obj["_code_module"], "dans_mapping": (n - 1) not in absents})
    return lignes


# -----------------------------------------------------------------------------
# Activité : progression, notes, connexions
# -----------------------------------------------------------------------------
def _random_datetime(rng: random.Random, start: date, end: date) -> datetime:
    jour = start + timedelta(days=rng.randint(0, max(0, (end - start).days)))
    heure = rng.choices(range(6, 24), weights=[1, 2, 3, 3, 3, 3, 3, 3, 3, 4, 4, 5, 6, 7, 8, 8, 6, 3], k=1)[0]
    return datetime.combine(jour, time(heure, rng.randint(0, 59), rng.randint(0, 59)))


def build_activite(profils: list[ProfilLMS], modules, cours, quiz, gen: GenerationConfig,
                   rng: random.Random, fake) -> tuple[list[dict], list[dict], list[dict]]:
    cours_par_module = defaultdict(list)
    for c in cours:
        cours_par_module[c["id_module"]].append(c)
    quiz_par_module = defaultdict(list)
    ordre_cours = {c["id_cours"]: c["ordre"] for c in cours}
    module_du_cours = {c["id_cours"]: c["id_module"] for c in cours}
    for q in quiz:
        quiz_par_module[module_du_cours[q["id_cours"]]].append(q)
    for lst in quiz_par_module.values():
        lst.sort(key=lambda q: ordre_cours[q["id_cours"]])
    modules_par_categorie = defaultdict(list)
    for m in modules:
        modules_par_categorie[m["categorie"]].append(m)

    progression, notes, connexions = [], [], []
    for p in profils:
        fin_active = max(p.debut + timedelta(days=30), p.fin)
        # --- Modules suivis (70 % dans la catégorie de la filière) ----------
        nb_modules = rng.randint(NB_MODULES_MIN, NB_MODULES_MAX)
        choisis: dict[str, dict] = {}
        while len(choisis) < nb_modules:
            pool = (modules_par_categorie[p.categorie_preferee] if rng.random() < P_CATEGORIE_PREFEREE
                    else modules)
            m = rng.choice(pool)
            choisis.setdefault(m["id_module"], m)
        capacite = min(1.1, max(0.15, rng.gauss(0.58, 0.15)))  # niveau de l'étudiant

        for m in choisis.values():
            debut_module = _random_datetime(rng, p.debut, max(p.debut, fin_active - timedelta(days=14)))
            fin_module = min(datetime.combine(fin_active, time(23, 0)), debut_module + timedelta(days=150))
            r = rng.random()
            pct = 100.0 if r < 0.35 else (round(rng.uniform(10, 99.5), 2) if r < 0.90
                                           else round(rng.uniform(0, 10), 2))
            lecons = cours_par_module[m["id_module"]]
            dernier = None if pct == 0 else lecons[max(0, -(-int(pct) * len(lecons) // 100) - 1)]["id_cours"]

            # --- Notes : quiz passés au prorata de la progression -----------
            quiz_module = quiz_par_module[m["id_module"]]
            passes = quiz_module[:round(len(quiz_module) * pct / 100)]
            t = debut_module
            for q in passes:
                max_tentatives = rng.choices(TENTATIVES_MAX, weights=POIDS_TENTATIVES_MAX, k=1)[0]
                for tentative in range(1, max_tentatives + 1):
                    t += timedelta(hours=rng.randint(1, 72), minutes=rng.randint(0, 59))
                    if t > fin_module:
                        break
                    frac = min(1.0, max(0.0, capacite + 0.07 * (tentative - 1) + rng.gauss(0, 0.12)))
                    score = round(frac * q["score_max"], 2)
                    valide = score >= SEUIL_VALIDATION * q["score_max"]
                    notes.append({"id_note": deterministic_uuid(rng), "id_quiz": q["id_quiz"],
                                  "student_code": p.student_code, "date_passage": t.replace(microsecond=0),
                                  "score": score, "tentative": tentative, "valide": valide})
                    if valide and rng.random() > P_REPASSER_APRES_REUSSITE:
                        break
            date_maj = min(fin_module, t + timedelta(hours=rng.randint(0, 48)))
            progression.append({"id_progression": deterministic_uuid(rng), "student_code": p.student_code,
                                "id_module": m["id_module"], "pourcentage": pct, "dernier_cours": dernier,
                                "date_maj": date_maj.replace(microsecond=0)})

        # --- Connexions -----------------------------------------------------
        for _ in range(rng.randint(NB_CONNEXIONS_MIN, NB_CONNEXIONS_MAX)):
            debut = _random_datetime(rng, p.debut, fin_active)
            duree = max(1, min(480, int(rng.lognormvariate(3.4, 0.7))))
            appareil = rng.choices(APPAREILS, weights=(55, 35, 10), k=1)[0]
            navigateur = (rng.choices(NAVIGATEURS_PC, weights=(55, 15, 20, 5, 5), k=1)[0] if appareil == "PC"
                          else rng.choices(NAVIGATEURS_MOBILE, weights=(60, 30, 10), k=1)[0])
            connexions.append({
                "id_connexion": deterministic_uuid(rng), "student_code": p.student_code,
                "date_connexion": debut, "date_deconnexion": debut + timedelta(minutes=duree),
                "duree_minutes": duree, "appareil": appareil, "navigateur": navigateur,
                # Faker : adresses IP publiques réalistes (90 % IPv4, 10 % IPv6)
                "adresse_ip": fake.ipv4_public() if rng.random() < 0.9 else fake.ipv6(),
            })
    return progression, notes, connexions


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------
def generate_clean(gen: GenerationConfig, students: list[MasterStudent]):
    """Tables PROPRES + codes + profils (aucune anomalie)."""
    problems = validate_learning_catalog()
    if problems:
        raise GenerationError("Catalogue pédagogique incohérent : " + " ; ".join(problems))
    rng = get_rng(SOURCE, seed=gen.seed)
    fake = get_faker(SOURCE, seed=gen.seed)
    modules, cours, quiz = build_contenus(rng)
    codes = build_codes(modules, cours, quiz, get_rng(f"{SOURCE}_codes", seed=gen.seed))
    profils = build_profils(students, gen)
    progression, notes, connexions = build_activite(profils, modules, cours, quiz, gen, rng, fake)
    for row in cours + quiz:
        row.pop("_code_module")
    tables = {"modules": modules, "cours": cours, "quiz": quiz, "notes": notes,
              "progression": progression, "temps_connexion": connexions}
    return tables, codes, profils


def generate(gen: GenerationConfig | None = None, students: list[MasterStudent] | None = None):
    """Retourne (tables, journal, bases, codes). Aucun accès base ni fichier (hors référentiel)."""
    gen = gen or get_settings().generation
    students = students if students is not None else load_referential()
    tables, codes, _ = generate_clean(gen, students)
    journal, bases = inject_anomalies(tables, gen, get_rng(f"{SOURCE}_anomalies", seed=gen.seed))
    mesure, attendu = measure_anomalies(tables), journal.counts()
    if mesure != attendu:
        ecarts = {c: (attendu[c], mesure[c]) for c in attendu if attendu[c] != mesure[c]}
        raise GenerationError(f"Journal et données divergent (journal, mesure) : {ecarts}")
    return tables, journal, bases, codes


def _to_csv_value(value):
    if value is None:
        return NULL
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def write_tables(tables: dict[str, list[dict]], out_dir: Path) -> dict[str, int]:
    """CSV au format LOAD DATA : séparateur ',', guillemets si besoin, NULL = \\N, fins de ligne \\n."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table in TABLE_ORDER:
        path = out_dir / f"{table}.csv"
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{table}_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(COLUMNS[table])
                for row in tables[table]:
                    writer.writerow([_to_csv_value(row[c]) for c in COLUMNS[table]])
            os.replace(tmp, path)
        except OSError as exc:
            Path(tmp).unlink(missing_ok=True)
            raise GenerationError(f"Écriture impossible de {path} : {exc}") from exc
        counts[table] = len(tables[table])
        logger.info("%-16s %7d lignes -> %s", table, counts[table], path.name)
    return counts


def write_codes(codes: list[dict], mappings_dir: Path, referential_dir: Path) -> tuple[int, int]:
    """Écrit le référentiel caché (100 %) et le mapping livré (codes présents seulement)."""
    _atomic_write_csv(referential_dir / REFERENTIEL_CONTENUS_FILENAME, REFERENTIEL_CONTENUS_COLUMNS,
                      ([c[k] if k != "dans_mapping" else ("true" if c[k] else "false")
                        for k in REFERENTIEL_CONTENUS_COLUMNS] for c in codes))
    livres = [c for c in codes if c["dans_mapping"]]
    _atomic_write_csv(mappings_dir / MAPPING_COURSES_FILENAME, MAPPING_COURSES_COLUMNS,
                      ([c["type_objet"], c["code_externe"], c["id_mysql"], c["code_module"], "APPARIE"]
                       for c in livres))
    return len(codes), len(livres)


def build_summary(tables, journal_counts, bases, codes, gen) -> dict:
    return {
        "source": SOURCE,
        "seed": gen.seed,
        "volumes": {t: len(tables[t]) for t in TABLE_ORDER},
        "cibles": TARGETS,
        "codes": {t: {"total": sum(1 for c in codes if c["type_objet"] == t),
                      "dans_mapping": sum(1 for c in codes if c["type_objet"] == t and c["dans_mapping"])}
                  for t in ("MODULE", "COURSE", "QUIZ")},
        "anomalies": {code: {"nombre": n, "base": bases[code], "taux": round(n / bases[code], 4)}
                      for code, n in journal_counts.items()},
    }


def main() -> int:
    settings = get_settings()
    gen = settings.generation
    out_dir = settings.paths.generated_dir / SOURCE
    try:
        settings.paths.ensure_directories()
        with log_step(logger, "Génération Source 2 (MySQL)"):
            tables, journal, bases, codes = generate(gen)
        with log_step(logger, "Écriture des CSV, du mapping et du journal"):
            write_tables(tables, out_dir)
            total, livres = write_codes(codes, settings.paths.mappings_dir, settings.paths.referential_dir)
            logger.info("Codes de contenus : %d au total, %d dans mapping_courses.csv", total, livres)
            n = journal.write_csv(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv")
            logger.info("Journal d'anomalies : %d lignes", n)
            summary = build_summary(tables, journal.counts(), bases, codes, gen)
            (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
        for code, info in summary["anomalies"].items():
            logger.info("%s : %6d / %6d = %5.2f %%", code, info["nombre"], info["base"], 100 * info["taux"])
        return 0
    except (GenerationError, OSError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la génération de la Source 2")
        return 2


if __name__ == "__main__":
    sys.exit(main())
