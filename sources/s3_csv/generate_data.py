"""
sources/s3_csv/generate_data.py — Génération de la Source 3 (Lot L2-c)
=====================================================================

Produit les 4 exports RH (PDF Source 3) dans sources/s3_csv/output/ :
    enseignants.csv (~120) · departements.csv (12) · salaires.csv (~4 300)
    · absences.csv (~2 500)
avec l'encodage et le séparateur de chaque fichier (décision validée) :
    enseignants, departements -> UTF-8, séparateur ','
    salaires, absences        -> ISO-8859-1, séparateur ';'

Cohérence avec les autres sources
    - Les enseignants sont EXACTEMENT les 120 du vivier commun
      (common/academic_catalog.py) : mêmes codes ENS-NNNN, mêmes noms que les
      responsables de classe de PostgreSQL (convention C18).
    - La spécialité découle du département de l'enseignant.
    - Les responsables de département sont des enseignants du vivier.

Règles de génération (conventions, voir README)
    - Salaires mensuels d'octobre 2023 à août 2026 (35 mois) : le salaire de
      septembre 2026 n'est pas encore versé à la date de référence (15/09/2026).
    - net = base + primes - retenues ; revalorisation de 3 % chaque janvier.
    - Absences : 0, 1 ou 2 par mois travaillé, un jour ouvré, 2 à 8 heures.

Exécution : python -m sources.s3_csv.generate_data
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from common import senegalese_data as sn
from common.academic_catalog import DEPARTEMENTS, Enseignant, build_teacher_pool
from common.config import GenerationConfig, get_settings
from common.logger import get_logger, log_step
from common.seed import get_faker, get_rng
from sources.s3_csv.anomalies import (MODES_PAIEMENT, MOIS, MOTIFS, SOURCE, SPECIALITE_PAR_DEPARTEMENT,
                                      inject_anomalies, measure_anomalies)
from sources.s3_csv.create_source import FILE_ORDER, OUTPUT_DIR, SCHEMAS

logger = get_logger("s3_generate")

COLUMNS = {k: SCHEMAS[k].entetes for k in FILE_ORDER}
TARGETS = {"enseignants": 120, "departements": 12, "salaires": 4_300, "absences": 2_500}
EXACT_TARGETS = {"departements"}
TOLERANCE = 0.05

# Départements en double écriture (C08) : 2 exemples du PDF + 2 autres
VARIANTES_DEPARTEMENT = (
    ("Data", "Développement Data"),
    ("Data", "Data Engineering"),
    ("Informatique", "Département Informatique"),
    ("Réseaux et Télécommunications", "Réseaux & Télécoms"),
)
BATIMENTS = ("Bâtiment A", "Bâtiment B", "Bâtiment C", "Bâtiment D")

# Salaire de base mensuel (XOF) selon le grade ; vacataires sans grade
SALAIRE_PAR_GRADE = {"ASSISTANT": (450_000, 600_000), "MAITRE_ASSISTANT": (650_000, 850_000),
                     "MAITRE_CONFERENCE": (900_000, 1_200_000), "PROFESSEUR": (1_300_000, 1_800_000)}
SALAIRE_VACATAIRE = (150_000, 400_000)
P_PERMANENT, P_EMBAUCHE_PENDANT_PERIODE = 0.65, 0.20  # 20 % des non-responsables
DERNIER_MOIS_PAYE = (2026, 8)   # août 2026 (voir docstring)


class GenerationError(Exception):
    """Erreur bloquante pendant la génération de la Source 3."""


def _mois_periode(gen: GenerationConfig):
    """(année, mois) d'octobre 2023 au dernier mois payé."""
    y, m = gen.periode_debut.year, gen.periode_debut.month
    while (y, m) <= DERNIER_MOIS_PAYE:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _grade(rng: random.Random, statut: str, age: int) -> str | None:
    if statut == "Vacataire":
        return None if rng.random() < 0.7 else "ASSISTANT"
    if age < 35:
        return rng.choices(("ASSISTANT", "MAITRE_ASSISTANT"), weights=(70, 30))[0]
    if age < 45:
        return rng.choices(("MAITRE_ASSISTANT", "MAITRE_CONFERENCE"), weights=(60, 40))[0]
    return rng.choices(("MAITRE_CONFERENCE", "PROFESSEUR"), weights=(55, 45))[0]


def _email(t: Enseignant, used: set[str]) -> str:
    import re
    import unicodedata
    slug = lambda s: re.sub(r"[^a-z0-9]+", ".", unicodedata.normalize("NFKD", s).encode("ascii", "ignore")
                            .decode().lower()).strip(".")
    base, n = f"{slug(t.prenom)}.{slug(t.nom)}", 1
    email = f"{base}@edusmart.sn"
    while email in used:
        n += 1
        email = f"{base}{n}@edusmart.sn"
    used.add(email)
    return email


def responsables_de_classe(gen: GenerationConfig) -> set[str]:
    """
    Noms des responsables de classe de PostgreSQL, recalculés en mémoire à partir
    des données PROPRES de la Source 1 (même graine). Vérité terrain, jamais lue par l'ETL.
    """
    from common.referential import STATUT_LMS_ORPHELIN, load_referential
    from sources.s1_postgresql.generate_data import generate_clean as s1_clean
    etudiants = [s for s in load_referential() if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    return {c["responsable"] for c in s1_clean(etudiants, gen)["classes"]}


def build_enseignants(pool, gen, rng, fake, responsables: set[str]) -> list[dict]:
    """
    Un responsable de classe doit être en poste dès la rentrée 2023 : seuls les
    enseignants qui ne sont responsables d'aucune classe peuvent être embauchés
    pendant la période (sinon, incohérence non voulue entre les sources).
    """
    ref = gen.periode_debut
    rows, used = [], set()
    for t in pool:
        naissance = fake.date_between_dates(date(ref.year - 65, 1, 1), date(ref.year - 28, 12, 31))
        age = ref.year - naissance.year
        tirage = rng.random() < P_EMBAUCHE_PENDANT_PERIODE
        if tirage and t.nom_complet not in responsables:
            embauche = fake.date_between_dates(ref, date(2026, 6, 30))
        else:
            debut = date(max(2005, naissance.year + 25), 1, 1)
            embauche = fake.date_between_dates(min(debut, ref - timedelta(days=30)), ref - timedelta(days=1))
        statut = "Permanent" if rng.random() < P_PERMANENT else "Vacataire"
        rows.append({
            "teacher_code": t.teacher_code, "nom": t.nom, "prenom": t.prenom, "sexe": t.sexe,
            "date_naissance": naissance.isoformat(), "telephone": sn.random_phone(rng), "email": _email(t, used),
            "specialite": SPECIALITE_PAR_DEPARTEMENT[t.departement], "grade": _grade(rng, statut, age),
            "date_embauche": embauche.isoformat(), "statut": statut,
            "_embauche_iso": embauche.isoformat(), "_departement": t.departement,  # champs techniques
        })
    return rows


def build_departements(enseignants, rng) -> tuple[list[dict], dict[int, str]]:
    responsables = {}
    rang = {"PROFESSEUR": 4, "MAITRE_CONFERENCE": 3, "MAITRE_ASSISTANT": 2, "ASSISTANT": 1, None: 0}
    for e in sorted(enseignants, key=lambda e: (-rang[e["grade"]], e["teacher_code"])):
        responsables.setdefault(e["_departement"], f"{e['prenom']} {e['nom']}")
    rows = []
    for i, nom in enumerate(DEPARTEMENTS, start=1):
        rows.append({"id_departement": i, "nom_departement": nom, "responsable": responsables[nom],
                     "budget_annuel": float(rng.randrange(25_000_000, 150_000_000, 500_000)),
                     "batiment": BATIMENTS[(i - 1) % len(BATIMENTS)]})
    variantes = {}
    for j, (canon, variante) in enumerate(VARIANTES_DEPARTEMENT, start=len(DEPARTEMENTS) + 1):
        rows.append({"id_departement": j, "nom_departement": variante,
                     "responsable": rng.choice((responsables[canon], None)),
                     "budget_annuel": float(rng.randrange(5_000_000, 40_000_000, 500_000)), "batiment": None})
        variantes[j] = canon
    return rows, variantes


def build_salaires(enseignants, gen, rng) -> list[dict]:
    rows = []
    for e in enseignants:
        embauche = date.fromisoformat(e["_embauche_iso"])
        base0 = rng.randint(*(SALAIRE_PAR_GRADE[e["grade"]] if e["statut"] == "Permanent"
                              else SALAIRE_VACATAIRE)) // 1000 * 1000
        mode = rng.choices(MODES_PAIEMENT, weights=(70, 15, 10, 5))[0]   # mode habituel de l'enseignant
        for annee, mois in _mois_periode(gen):
            if (annee, mois) < (embauche.year, embauche.month):
                continue
            if e["statut"] == "Permanent":
                base = round(base0 * 1.03 ** (annee - gen.periode_debut.year) / 1000) * 1000  # +3 % chaque janvier
                primes = 0 if rng.random() < 0.6 else round(base * rng.uniform(0.05, 0.15) / 1000) * 1000
            else:  # vacataire : heures variables d'un mois à l'autre
                base, primes = round(base0 * rng.uniform(0.5, 1.3) / 1000) * 1000, 0
            retenues = round(base * rng.uniform(0.08, 0.18) / 1000) * 1000
            rows.append({"teacher_code": e["teacher_code"], "mois": MOIS[mois - 1], "annee": annee,
                         "salaire_base": float(base), "primes": float(primes), "retenues": float(retenues),
                         "salaire_net": float(base + primes - retenues),
                         "mode_paiement": mode if rng.random() < 0.95 else rng.choice(MODES_PAIEMENT)})
    rows.sort(key=lambda r: (r["annee"], MOIS.index(r["mois"]), r["teacher_code"]))
    for i, r in enumerate(rows, start=1):
        r["id_salaire"] = i
    return rows


def build_absences(enseignants, gen, rng) -> list[dict]:
    rows = []
    for e in enseignants:
        embauche = date.fromisoformat(e["_embauche_iso"])
        for annee, mois in _mois_periode(gen):
            for _ in range(rng.choices((0, 1, 2), weights=(48, 45, 7))[0]):
                jours = [date(annee, mois, d) for d in range(1, 29)
                         if date(annee, mois, d).weekday() < 5 and embauche <= date(annee, mois, d) <= gen.date_reference]
                if not jours:
                    continue
                rows.append({"teacher_code": e["teacher_code"], "date_absence": rng.choice(jours).isoformat(),
                             "motif": rng.choice(MOTIFS), "justifiee": "Oui" if rng.random() < 0.75 else "Non",
                             "duree_heures": rng.choice((2, 3, 4, 6, 8)),
                             "remplace": "Oui" if rng.random() < (0.45 if e["statut"] == "Permanent" else 0.25) else "Non"})
    rows.sort(key=lambda r: (r["date_absence"], r["teacher_code"]))
    for i, r in enumerate(rows, start=1):
        r["id_absence"] = i
    return rows


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------
def generate_clean(gen: GenerationConfig):
    rng = get_rng(SOURCE, seed=gen.seed)
    fake = get_faker(SOURCE, seed=gen.seed)
    pool = build_teacher_pool(seed=gen.seed)
    enseignants = build_enseignants(pool, gen, rng, fake, responsables_de_classe(gen))
    departements, variantes = build_departements(enseignants, rng)
    tables = {"enseignants": enseignants, "departements": departements,
              "salaires": build_salaires(enseignants, gen, rng), "absences": build_absences(enseignants, gen, rng)}
    return tables, variantes


def generate(gen: GenerationConfig | None = None):
    """Retourne (tables, journal, bases)."""
    gen = gen or get_settings().generation
    tables, variantes = generate_clean(gen)
    journal, bases = inject_anomalies(tables, gen, get_rng(f"{SOURCE}_anomalies", seed=gen.seed), variantes)
    mesure, attendu = measure_anomalies(tables, COLUMNS, gen), journal.counts()
    if mesure != attendu:
        ecarts = {c: (attendu[c], mesure[c]) for c in attendu if attendu[c] != mesure[c]}
        raise GenerationError(f"Journal et données divergent (journal, mesure) : {ecarts}")
    return tables, journal, bases


def _to_csv_value(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def write_files(tables: dict[str, list[dict]], out_dir: Path = OUTPUT_DIR) -> dict[str, int]:
    """Écrit chaque fichier avec SON encodage et SON séparateur (fins de ligne CRLF, comme Excel)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for key in FILE_ORDER:
        schema = SCHEMAS[key]
        path = out_dir / schema.nom
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{key}_", suffix=".tmp")
        try:
            # errors="strict" : un caractère non représentable en ISO-8859-1 fait échouer (jamais de '?')
            with os.fdopen(fd, "w", encoding=schema.encodage, errors="strict", newline="") as handle:
                writer = csv.writer(handle, delimiter=schema.separateur, lineterminator="\r\n")
                writer.writerow(schema.entetes)
                for row in tables[key]:
                    writer.writerow([_to_csv_value(row[c]) for c in schema.entetes])
            os.replace(tmp, path)
        except (OSError, UnicodeEncodeError) as exc:
            Path(tmp).unlink(missing_ok=True)
            raise GenerationError(f"Écriture impossible de {path} : {exc}") from exc
        counts[key] = len(tables[key])
        logger.info("%-17s %5d lignes  %-10s sep '%s'", schema.nom, counts[key], schema.encodage, schema.separateur)
    return counts


def build_summary(tables, journal_counts, bases, gen) -> dict:
    return {"source": SOURCE, "seed": gen.seed, "volumes": {k: len(tables[k]) for k in FILE_ORDER},
            "cibles": TARGETS,
            "anomalies": {c: {"nombre": n, "base": bases[c], "taux": round(n / bases[c], 4)}
                          for c, n in journal_counts.items()}}


def main() -> int:
    settings = get_settings()
    gen = settings.generation
    try:
        settings.paths.ensure_directories()
        with log_step(logger, "Génération Source 3 (CSV RH)"):
            tables, journal, bases = generate(gen)
        with log_step(logger, "Écriture des 4 fichiers et du journal"):
            write_files(tables)
            n = journal.write_csv(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv")
            logger.info("Journal d'anomalies : %d lignes", n)
            summary = build_summary(tables, journal.counts(), bases, gen)
            summary_dir = settings.paths.generated_dir / SOURCE
            summary_dir.mkdir(parents=True, exist_ok=True)
            (summary_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
        for code, info in summary["anomalies"].items():
            logger.info("%s : %4d / %4d = %5.2f %%", code, info["nombre"], info["base"], 100 * info["taux"])
        return 0
    except (GenerationError, OSError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la génération de la Source 3")
        return 2


if __name__ == "__main__":
    sys.exit(main())
