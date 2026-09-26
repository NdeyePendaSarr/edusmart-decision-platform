"""
sources/s1_postgresql/generate_data.py — Génération de la Source 1 (Lot L2-a)
============================================================================

Produit les 5 tables de la base edusmart_academic (PDF Source 1) :
    etudiants (10 000) · filieres (25) · classes (150) · inscriptions (~18 000)
    · paiements (~40 000)

Étapes
    1. Lecture du référentiel maître (common/referential.py) : les 10 000
       étudiants PostgreSQL (statuts APPARIE et SANS_LMS). Les 500 orphelins
       LMS n'existent pas dans cette source.
    2. Génération de données PROPRES et cohérentes (parcours réalistes).
    3. Injection des 16 types d'anomalies (anomalies.py) + journal.
    4. Écriture dans data/generated/s1_postgresql/ :
       - un CSV par table (chargé ensuite par insert_data.py via COPY) ;
       - summary.json (volumes, taux d'anomalies) ;
       et du journal dans data/anomalies/s1_postgresql_anomalies.csv.

Aucune base n'est nécessaire : ce script est testable hors Docker.

Règles de génération (conventions, voir README de la source)
    - Niveau : moins de 21 ans à l'entrée -> Licence (75 %) ou Certificat
      (25 %) ; sinon Licence 45 %, Master 36 %, Certificat 19 %.
    - Parcours : Licence 3 ans, Master 2 ans, Certificat 1 an ; arrêt à la fin
      de la période (2025-2026). Un certificat peut être suivi d'un autre (25 %).
    - Statuts : ABANDON 6 %/an (fin du parcours), SUSPENDU 2 %/an (reprise
      l'année suivante), EN_COURS pour 2025-2026, DIPLOME en dernière année,
      INSCRIT pour une année intermédiaire achevée.
    - Inscription entre juin et le 30 septembre (avant la rentrée du 1er octobre).
    - Frais annuels = coût total / nombre d'années, après réduction, arrondis
      à 500 XOF, payés en 1, 2 ou 3 tranches (octobre, janvier, avril).

Exécution : python -m sources.s1_postgresql.generate_data
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from common import senegalese_data as sn
from common.academic_catalog import (ANNEES_PAR_NIVEAU, FILIERES, FILIERES_PAR_CODE,
                                     build_teacher_pool, validate_catalog)
from common.config import GenerationConfig, get_settings
from common.logger import get_logger, log_step
from common.referential import STATUT_LMS_ORPHELIN, MasterStudent, load_referential
from common.seed import deterministic_uuid, get_faker, get_rng
from sources.s1_postgresql.anomalies import (MODES_PAIEMENT_CANONIQUES, SOURCE,
                                             inject_anomalies, measure_anomalies)

logger = get_logger("s1_generate")

# Ordre de chargement (respect des clés étrangères) et colonnes du PDF
TABLE_ORDER = ("filieres", "etudiants", "classes", "inscriptions", "paiements")
COLUMNS: dict[str, list[str]] = {
    "etudiants": ["id_etudiant", "matricule", "nom", "prenom", "sexe", "date_naissance", "telephone",
                  "email", "adresse", "ville", "region", "pays", "date_creation"],
    "filieres": ["id_filiere", "code_filiere", "nom_filiere", "departement", "niveau", "duree_mois",
                 "cout_total", "statut"],
    "classes": ["id_classe", "code_classe", "nom_classe", "id_filiere", "annee_academique", "capacite",
                "salle", "responsable"],
    "inscriptions": ["id_inscription", "id_etudiant", "id_classe", "date_inscription", "statut",
                     "type_inscription", "bourse", "reduction"],
    "paiements": ["id_paiement", "id_inscription", "reference", "date_paiement", "montant",
                  "mode_paiement", "statut", "tranche"],
}

# Cibles validées (Étape 2) pour la porte G1
TARGETS = {"etudiants": 10_000, "filieres": 25, "classes": 150, "inscriptions": 18_000, "paiements": 40_000}
TOLERANCE = 0.05

NIVEAU_LABEL = {"LICENCE": "Licence", "MASTER": "Master", "CERTIFICAT": "Certificat"}
TRANCHES = ("1ERE", "2EME", "3EME")
_MODE_WEIGHTS = (40, 35, 10, 10, 5)  # aligné sur MODES_PAIEMENT_CANONIQUES

# Paramètres de parcours (conventions de génération)
P_ABANDON, P_SUSPENSION, P_CERTIFICAT_SUIVANT = 0.06, 0.02, 0.25
P_BOURSE, P_ECHEC_PAIEMENT, P_REMBOURSEMENT, P_EN_ATTENTE = 0.12, 0.03, 0.30, 0.05

# Quartiers : spécifiques pour la région de Dakar, génériques ailleurs
# (noms répandus dans de nombreuses villes sénégalaises)
QUARTIERS_DAKAR = ("Médina", "Plateau", "Ouakam", "Mermoz", "Sacré-Cœur", "Point E", "Grand Yoff",
                   "Parcelles Assainies", "Liberté", "Sicap", "HLM", "Castors", "Cité Keur Gorgui",
                   "Nord Foire", "Yoff", "Fass")
QUARTIERS_GENERIQUES = ("Escale", "Darou Salam", "Médina", "HLM", "Santhiaba", "Diamaguène",
                        "Darou Rahmane", "Keur Mbaye Fall", "Liberté", "Cité Administrative",
                        "Quartier Nord", "Quartier Sud")


class GenerationError(Exception):
    """Erreur bloquante pendant la génération de la Source 1."""


# -----------------------------------------------------------------------------
# Utilitaires
# -----------------------------------------------------------------------------
def _slug(text: str) -> str:
    """'Mame Diarra' -> 'mame.diarra' (ASCII, pour les e-mails)."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", ".", ascii_.lower()).strip(".")


def _random_date(rng, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _round_500(value: float) -> int:
    return int(round(value / 500.0)) * 500


def _age_at(birth: date, ref: date) -> int:
    return ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))


# -----------------------------------------------------------------------------
# Génération des données propres
# -----------------------------------------------------------------------------
def _build_filieres(rng) -> list[dict]:
    return [{
        "id_filiere": deterministic_uuid(rng),
        "code_filiere": f.code_filiere,
        "nom_filiere": f.nom_filiere,
        "departement": f.departement,
        "niveau": f.niveau,
        "duree_mois": f.duree_mois,
        "cout_total": f.cout_total,
        "statut": "ACTIVE",
    } for f in FILIERES]


def _build_classes(rng, filieres: list[dict], gen: GenerationConfig) -> list[dict]:
    """25 filières x 3 années x 2 groupes = 150 classes. Capacité fixée plus tard."""
    teachers_by_dept = defaultdict(list)
    for t in build_teacher_pool(seed=gen.seed):
        teachers_by_dept[t.departement].append(t)
    classes = []
    for fil in filieres:
        for annee in gen.annees_academiques:
            for groupe in ("A", "B"):
                nom = f"{fil['nom_filiere']} ({NIVEAU_LABEL[fil['niveau']]}) {annee} - Groupe {groupe}"
                classes.append({
                    "id_classe": deterministic_uuid(rng),
                    "code_classe": f"{fil['code_filiere']}-{annee[2:4]}{annee[7:9]}-{groupe}",
                    "nom_classe": nom[:100],
                    "id_filiere": fil["id_filiere"],
                    "annee_academique": annee,
                    "capacite": None,
                    "salle": f"{rng.choice('ABCDE')}{rng.randint(1, 3)}{rng.randint(1, 20):02d}",
                    "responsable": rng.choice(teachers_by_dept[fil["departement"]]).nom_complet,
                })
    return classes


def _build_etudiant(rng, s: MasterStudent, used_emails: set[str]) -> dict:
    base = f"{_slug(s.prenom)}.{_slug(s.nom)}"
    email, n = f"{base}@{rng.choice(sn.EMAIL_DOMAINS)}", 1
    while email in used_emails:
        n += 1
        email = f"{base}{n}@{rng.choice(sn.EMAIL_DOMAINS)}"
    used_emails.add(email)
    quartiers = QUARTIERS_DAKAR if s.region == "Dakar" else QUARTIERS_GENERIQUES
    adresse = f"{rng.choice(('Villa', 'Lot', 'Maison'))} n° {rng.randint(1, 450)}, {rng.choice(quartiers)}"
    return {
        "id_etudiant": s.id_etudiant,
        "matricule": s.matricule,
        "nom": s.nom,
        "prenom": s.prenom,
        "sexe": s.sexe,
        "date_naissance": date.fromisoformat(s.date_naissance),
        "telephone": sn.random_phone(rng),
        "email": email,
        "adresse": adresse,
        "ville": s.ville,
        "region": s.region,
        "pays": s.pays,
        "date_creation": None,  # fixé d'après la première inscription
    }


def _choose_filiere(rng, age: int, exclude: set[str] = frozenset()):
    niveaux, poids = (("LICENCE", "CERTIFICAT"), (0.75, 0.25)) if age < 21 else \
        (("LICENCE", "MASTER", "CERTIFICAT"), (0.45, 0.36, 0.19))
    niveau = rng.choices(niveaux, weights=poids, k=1)[0]
    return _choose_in_level(rng, niveau, exclude)


def _choose_in_level(rng, niveau: str, exclude: set[str] = frozenset()):
    candidats = [f for f in FILIERES if f.niveau == niveau and f.code_filiere not in exclude]
    return rng.choices(candidats, weights=[f.popularite for f in candidats], k=1)[0]


def _build_parcours(rng, etu: dict, s: MasterStudent, gen: GenerationConfig,
                    classes_index: dict) -> list[dict]:
    """Toutes les inscriptions (propres) d'un étudiant."""
    annees = list(gen.annees_academiques)
    idx = annees.index(s.annee_academique_entree)
    derniere = annees[-1]
    groupe = rng.choice("AB")
    bourse = rng.random() < P_BOURSE
    reduction = (rng.choices((50.0, 75.0, 100.0), weights=(4, 3, 3))[0] if bourse
                 else rng.choices((0.0, 10.0, 20.0), weights=(85, 10, 5))[0])

    filiere = _choose_filiere(rng, _age_at(etu["date_naissance"], gen.rentree(s.annee_academique_entree)))
    deja_suivies: set[str] = set()
    inscriptions: list[dict] = []
    premiere_du_parcours = True
    k = 0  # rang de l'année dans le parcours courant

    while idx < len(annees):
        annee = annees[idx]
        rentree = gen.rentree(annee)
        nb_annees = ANNEES_PAR_NIVEAU[filiere.niveau]
        if premiere_du_parcours:
            date_insc = _random_date(rng, date(rentree.year, 6, 15), rentree - timedelta(days=1))
            type_insc = "Nouvelle"
        else:
            date_insc = _random_date(rng, date(rentree.year, 8, 1), rentree - timedelta(days=1))
            type_insc = "Réinscription"

        u = rng.random()
        if u < P_ABANDON:
            statut = "ABANDON"
        elif u < P_ABANDON + P_SUSPENSION:
            statut = "SUSPENDU"
        elif filiere.niveau == "CERTIFICAT":
            statut = "EN_COURS" if (annee == derniere and filiere.duree_mois == 12) else "DIPLOME"
        elif annee == derniere:
            statut = "EN_COURS"
        elif k == nb_annees - 1:
            statut = "DIPLOME"
        else:
            statut = "INSCRIT"

        inscriptions.append({
            "id_inscription": deterministic_uuid(rng),
            "id_etudiant": etu["id_etudiant"],
            "id_classe": classes_index[(filiere.code_filiere, annee, groupe)]["id_classe"],
            "date_inscription": date_insc,
            "statut": statut,
            "type_inscription": type_insc,
            "bourse": bourse,
            "reduction": reduction,
            "_filiere": filiere,  # champ technique (préfixe _), non exporté
        })
        deja_suivies.add(filiere.code_filiere)
        idx += 1
        if statut == "ABANDON":
            break
        if statut == "DIPLOME" or k == nb_annees - 1:
            # Fin de parcours : un certificat peut être suivi d'un autre
            if filiere.niveau == "CERTIFICAT" and rng.random() < P_CERTIFICAT_SUIVANT:
                filiere = _choose_in_level(rng, "CERTIFICAT", deja_suivies)
                premiere_du_parcours, k = True, 0
                continue
            break
        premiere_du_parcours, k = False, k + 1
    return inscriptions


def _build_paiements(rng, insc: dict, gen: GenerationConfig) -> list[dict]:
    """Paiements propres d'une inscription (références attribuées plus tard)."""
    f = insc["_filiere"]
    annuel = f.cout_total / ANNEES_PAR_NIVEAU[f.niveau]
    net = _round_500(annuel * (1 - insc["reduction"] / 100))
    if net <= 0:
        return []  # bourse à 100 % : aucun paiement

    plan = rng.choices((1, 2, 3), weights=(20, 25, 55), k=1)[0]
    montants = [_round_500(net / plan)] * (plan - 1)
    montants.append(net - sum(montants))
    rentree_year = insc["date_inscription"].year  # date propre, avant anomalies
    dates = [insc["date_inscription"] + timedelta(days=rng.randint(0, 10))]
    if plan == 2:
        dates.append(_random_date(rng, date(rentree_year + 1, 2, 1), date(rentree_year + 1, 2, 28)))
    elif plan == 3:
        dates.append(_random_date(rng, date(rentree_year + 1, 1, 5), date(rentree_year + 1, 1, 31)))
        dates.append(_random_date(rng, date(rentree_year + 1, 4, 1), date(rentree_year + 1, 4, 30)))

    nb_payees = plan
    if insc["statut"] == "ABANDON":
        nb_payees = 1
    elif insc["statut"] == "SUSPENDU":
        nb_payees = min(plan, rng.choice((1, 2)))

    paiements = []
    for i in range(nb_payees):
        mode = rng.choices(MODES_PAIEMENT_CANONIQUES, weights=_MODE_WEIGHTS, k=1)[0]
        base = {"id_inscription": insc["id_inscription"], "montant": montants[i], "tranche": TRANCHES[i]}
        if rng.random() < P_ECHEC_PAIEMENT:  # tentative échouée puis nouvelle tentative réussie
            paiements.append({**base, "id_paiement": deterministic_uuid(rng), "date_paiement": dates[i],
                              "mode_paiement": mode, "statut": "ECHOUE"})
            dates[i] += timedelta(days=rng.randint(1, 5))
            mode = rng.choices(MODES_PAIEMENT_CANONIQUES, weights=_MODE_WEIGHTS, k=1)[0]
        statut = "VALIDE"
        if insc["statut"] == "ABANDON" and rng.random() < P_REMBOURSEMENT:
            statut = "REMBOURSE"
        elif (insc["statut"] == "EN_COURS" and i == nb_payees - 1 and nb_payees > 1
              and rng.random() < P_EN_ATTENTE):
            statut = "EN_ATTENTE"
        paiements.append({**base, "id_paiement": deterministic_uuid(rng), "date_paiement": dates[i],
                          "mode_paiement": mode, "statut": statut})
    return paiements


def generate_clean(students: list[MasterStudent], gen: GenerationConfig) -> dict[str, list[dict]]:
    """Génère les 5 tables sans anomalie."""
    rng = get_rng(SOURCE, seed=gen.seed)
    fake = get_faker(SOURCE, seed=gen.seed)

    filieres = _build_filieres(rng)
    classes = _build_classes(rng, filieres, gen)
    code_by_id = {f["id_filiere"]: f["code_filiere"] for f in filieres}
    classes_index = {(code_by_id[c["id_filiere"]], c["annee_academique"], c["code_classe"][-1]): c
                     for c in classes}

    etudiants, inscriptions, used_emails = [], [], set()
    for s in students:
        etu = _build_etudiant(rng, s, used_emails)
        parcours = _build_parcours(rng, etu, s, gen, classes_index)
        premiere = min(i["date_inscription"] for i in parcours)
        # Faker : horodatage de création de la fiche, dans le mois précédant l'inscription
        etu["date_creation"] = fake.date_time_between(
            start_date=datetime.combine(premiere - timedelta(days=30), time.min),
            end_date=datetime.combine(premiere, time(18, 0)),
        ).replace(microsecond=0)
        etudiants.append(etu)
        inscriptions.extend(parcours)

    # Capacité : au-dessus de l'effectif réel (pas d'anomalie de sureffectif demandée)
    effectifs = Counter(i["id_classe"] for i in inscriptions)
    for c in classes:
        besoin = effectifs.get(c["id_classe"], 0) * rng.uniform(1.05, 1.30)
        c["capacite"] = max(30, int(-(-besoin // 5) * 5))

    paiements = []
    for insc in inscriptions:
        paiements.extend(_build_paiements(rng, insc, gen))
    # Références chronologiques : PAY-AAAA-NNNNNN
    paiements.sort(key=lambda p: (p["date_paiement"], p["id_paiement"]))
    for seq, p in enumerate(paiements, start=1):
        p["reference"] = f"PAY-{p['date_paiement'].year}-{seq:06d}"

    for insc in inscriptions:
        insc.pop("_filiere")
    return {"etudiants": etudiants, "filieres": filieres, "classes": classes,
            "inscriptions": inscriptions, "paiements": paiements}


# -----------------------------------------------------------------------------
# Écriture
# -----------------------------------------------------------------------------
def _to_csv_value(value):
    if value is None:
        return ""                 # NULL (COPY ... NULL '')
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def write_tables(tables: dict[str, list[dict]], out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table in TABLE_ORDER:
        path = out_dir / f"{table}.csv"
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{table}_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(COLUMNS[table])
                for row in tables[table]:
                    writer.writerow([_to_csv_value(row[c]) for c in COLUMNS[table]])
            os.replace(tmp, path)
        except OSError as exc:
            Path(tmp).unlink(missing_ok=True)
            raise GenerationError(f"Écriture impossible de {path} : {exc}") from exc
        counts[table] = len(tables[table])
        logger.info("%-13s %6d lignes -> %s", table, counts[table], path.name)
    return counts


def build_summary(tables, journal_counts, bases, gen) -> dict:
    return {
        "source": SOURCE,
        "seed": gen.seed,
        "volumes": {t: len(tables[t]) for t in TABLE_ORDER},
        "cibles": TARGETS,
        "anomalies": {
            code: {"nombre": n, "base": bases[code], "taux": round(n / bases[code], 4)}
            for code, n in journal_counts.items()
        },
    }


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------
def generate(gen: GenerationConfig | None = None, students: list[MasterStudent] | None = None):
    """Génère tables + journal + bases (en mémoire). Utilisé par main() et les tests."""
    gen = gen or get_settings().generation
    problems = validate_catalog()
    if problems:
        raise GenerationError("Catalogue académique incohérent : " + " ; ".join(problems))
    if students is None:
        students = load_referential()
    students = [s for s in students if s.statut_correspondance != STATUT_LMS_ORPHELIN]
    if len(students) != gen.nb_etudiants_pg:
        raise GenerationError(f"{len(students)} étudiants PG dans le référentiel, "
                              f"{gen.nb_etudiants_pg} attendus")

    tables = generate_clean(students, gen)
    journal, bases = inject_anomalies(tables, gen, get_rng(f"{SOURCE}_anomalies", seed=gen.seed))

    # Contrôle interne : la mesure doit égaler le journal
    mesure, attendu = measure_anomalies(tables, gen), journal.counts()
    if mesure != attendu:
        ecarts = {c: (attendu[c], mesure[c]) for c in attendu if attendu[c] != mesure[c]}
        raise GenerationError(f"Journal et données divergent (journal, mesure) : {ecarts}")
    return tables, journal, bases


def main() -> int:
    settings = get_settings()
    gen = settings.generation
    out_dir = settings.paths.generated_dir / SOURCE
    try:
        settings.paths.ensure_directories()
        with log_step(logger, "Génération Source 1 (PostgreSQL)"):
            tables, journal, bases = generate(gen)
        with log_step(logger, "Écriture des CSV"):
            write_tables(tables, out_dir)
            n = journal.write_csv(settings.paths.anomalies_dir / f"{SOURCE}_anomalies.csv")
            logger.info("Journal d'anomalies : %d lignes", n)
            summary = build_summary(tables, journal.counts(), bases, gen)
            (out_dir / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        for code, info in summary["anomalies"].items():
            logger.info("%s : %5d / %5d = %5.2f %%", code, info["nombre"], info["base"], 100 * info["taux"])
        return 0
    except (GenerationError, OSError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Erreur inattendue pendant la génération de la Source 1")
        return 2


if __name__ == "__main__":
    sys.exit(main())
