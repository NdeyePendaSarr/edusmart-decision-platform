"""
sources/s3_csv/anomalies.py — Anomalies volontaires de la Source 3
=================================================================

Codes C01 à C19. Les mesures travaillent sur les valeurs TELLES QU'ÉCRITES
dans les fichiers (chaînes) : le vérificateur relit les CSV exactement comme
le fera l'ETL.

Particularités des fichiers RH :
    - Doublons = lignes STRICTEMENT identiques (même identifiant), typiques
      d'un export exécuté deux fois. Ils sont créés EN DERNIER, à partir de
      lignes sans autre anomalie, pour que chaque anomalie soit comptée une fois.
    - departements.csv (12 lignes) est trop petit pour un taux de 2 à 5 % :
      C08 et C09 sont fixés par conception (comme A07 en Source 1).
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

from common import senegalese_data as sn
from common.anomaly_journal import AnomalyJournal, AnomalyType
from common.config import GenerationConfig

SOURCE = "s3_csv"
PDF = "Source 3 - CSV - Ressources Humaines.pdf"

ANOMALY_TYPES: dict[str, AnomalyType] = {t.code: t for t in (
    AnomalyType("C01", "enseignants", "telephone", "Téléphone mal formaté", f"{PDF} - enseignants, Recommandations"),
    AnomalyType("C02", "enseignants", "email", "E-mail manquant", f"{PDF} - enseignants, Recommandations"),
    AnomalyType("C03", "enseignants", "specialite", "Spécialité écrite différemment (IA, Data Science...)",
                f"{PDF} - enseignants, Recommandations"),
    AnomalyType("C04", "enseignants", "grade", "Grade hors référentiel (écriture incohérente)",
                f"{PDF} - enseignants, Recommandations"),
    AnomalyType("C05", "enseignants", "date_naissance", "Date au format DD/MM/YYYY ou MM-DD-YYYY",
                f"{PDF} - Contraintes générales (plusieurs formats de dates)"),
    AnomalyType("C06", "enseignants", "date_embauche", "Date au format DD/MM/YYYY ou MM-DD-YYYY",
                f"{PDF} - Contraintes générales (plusieurs formats de dates)"),
    AnomalyType("C07", "enseignants", "*", "Ligne dupliquée", f"{PDF} - Contraintes générales (lignes dupliquées)"),
    AnomalyType("C08", "departements", "nom_departement", "Même département écrit différemment",
                f"{PDF} - departements, Recommandations"),
    AnomalyType("C09", "departements", "budget_annuel", "Budget manquant", f"{PDF} - departements, Recommandations"),
    AnomalyType("C10", "salaires", "salaire_net", "Salaire négatif", f"{PDF} - salaires, Recommandations"),
    AnomalyType("C11", "salaires", "primes", "Primes incohérentes (supérieures au salaire de base)",
                f"{PDF} - salaires, Recommandations"),
    AnomalyType("C12", "salaires", "*", "Ligne dupliquée", f"{PDF} - salaires, Recommandations"),
    AnomalyType("C13", "salaires", "mode_paiement", "Mode de paiement écrit différemment (Virement, Banque, bank transfer)",
                f"{PDF} - salaires, Recommandations"),
    AnomalyType("C14", "salaires", "mois", "Mois mal orthographié ou dans un autre format",
                f"{PDF} - Contraintes générales (erreurs de saisie, catégories mal orthographiées)"),
    AnomalyType("C15", "absences", "*", "Ligne dupliquée", f"{PDF} - absences, Recommandations"),
    AnomalyType("C16", "absences", "motif", "Absence sans motif", f"{PDF} - absences, Recommandations"),
    AnomalyType("C17", "absences", "date_absence", "Date incohérente (avant l'embauche ou dans le futur)",
                f"{PDF} - absences, Recommandations"),
    AnomalyType("C18", "absences", "duree_heures", "Durée très élevée (plus de 24 h pour une absence datée d'un jour)",
                f"{PDF} - absences, Recommandations"),
    AnomalyType("C19", "absences", "date_absence", "Date au format DD/MM/YYYY ou MM-DD-YYYY",
                f"{PDF} - Contraintes générales (plusieurs formats de dates)"),
)}

FIXED_BY_DESIGN = {"C08", "C09"}

# -----------------------------------------------------------------------------
# Valeurs canoniques
# -----------------------------------------------------------------------------
GRADES = ("ASSISTANT", "MAITRE_ASSISTANT", "MAITRE_CONFERENCE", "PROFESSEUR")  # liste validée
STATUTS = ("Permanent", "Vacataire")                                          # PDF
MODES_PAIEMENT = ("Virement bancaire", "Wave", "Orange Money", "Espèces")
MOIS = ("Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août",
        "Septembre", "Octobre", "Novembre", "Décembre")
MOTIFS = ("Maladie", "Formation", "Mission", "Raison familiale", "Congé de maternité", "Décès d'un proche",
          "Examen médical", "Événement religieux", "Grève des transports", "Participation à un jury")

# Spécialité canonique par département (PDF : « spécialités écrites différemment »)
SPECIALITE_PAR_DEPARTEMENT = {
    "Informatique": "Génie Logiciel",
    "Data": "Science des Données",
    "Intelligence Artificielle": "Intelligence Artificielle",
    "Réseaux et Télécommunications": "Réseaux et Télécommunications",
    "Cybersécurité": "Cybersécurité",
    "Management": "Management",
    "Finance et Comptabilité": "Finance",
    "Marketing Digital": "Marketing Digital",
}
SPECIALITES = frozenset(SPECIALITE_PAR_DEPARTEMENT.values())

VARIANTES_SPECIALITE = {
    "Intelligence Artificielle": ("IA", "Intelligence artificielle", "I.A."),
    "Science des Données": ("Data Science", "Sciences des données", "Data"),
    "Génie Logiciel": ("Informatique", "Génie logiciel", "Dev"),
    "Réseaux et Télécommunications": ("Réseaux", "Télécoms", "Reseaux & Telecom"),
    "Cybersécurité": ("Cyber sécurité", "Sécurité informatique"),
    "Management": ("Gestion", "MANAGEMENT"),
    "Finance": ("Finance / Comptabilité", "Comptabilité"),
    "Marketing Digital": ("Marketing", "Marketing digital"),
}
VARIANTES_GRADE = {
    "ASSISTANT": ("Assistant", "Asst.", "assistant"),
    "MAITRE_ASSISTANT": ("Maître Assistant", "Maitre-Assistant", "MA"),
    "MAITRE_CONFERENCE": ("Maître de Conférences", "MC", "Maitre de conference"),
    "PROFESSEUR": ("Professeur", "Prof.", "Pr"),
}
VARIANTES_MODE = {
    "Virement bancaire": ("Virement", "Banque", "bank transfer", "VIREMENT"),
    "Wave": ("wave", "WAVE"),
    "Orange Money": ("OM", "orange money"),
    "Espèces": ("Especes", "Cash"),
}

# -----------------------------------------------------------------------------
# Lecture des dates et des mois (réutilisable par l'ETL)
# -----------------------------------------------------------------------------
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_FR_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")   # DD/MM/YYYY
_US_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")   # MM-DD-YYYY


def format_date(d: date, fmt: str) -> str:
    return {"ISO": d.strftime("%Y-%m-%d"), "FR": d.strftime("%d/%m/%Y"), "US": d.strftime("%m-%d-%Y")}[fmt]


def parse_date(text: str | None) -> tuple[date | None, str | None]:
    """
    Lit les 3 formats du PDF et renvoie (date, format).
    La convention est déduite du SÉPARATEUR et de la position de l'année :
    'AAAA-MM-JJ' -> ISO ; 'JJ/MM/AAAA' -> FR ; 'MM-JJ-AAAA' -> US.
    Sans cette convention, '03-04-2024' serait ambigu (3 avril ou 4 mars ?).
    """
    if not text:
        return None, None
    for regex, fmt, order in ((_ISO_RE, "ISO", (0, 1, 2)), (_FR_RE, "FR", (2, 1, 0)), (_US_RE, "US", (2, 0, 1))):
        m = regex.match(text.strip())
        if m:
            parts = m.groups()
            try:
                return date(int(parts[order[0]]), int(parts[order[1]]), int(parts[order[2]])), fmt
            except ValueError:
                return None, fmt
    return None, None


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).rstrip(".")


_MOIS_NORMALISES = {_norm(m): i for i, m in enumerate(MOIS, start=1)}
_MOIS_NORMALISES.update({_norm(m)[:4]: i for i, m in enumerate(MOIS, start=1)})  # janv, fevr, sept...
_MOIS_NORMALISES.update({_norm(m)[:3]: i for i, m in enumerate(MOIS, start=1) if _norm(m)[:3] not in ("jui", "mar")})


def normalize_mois(text: str | None) -> int | None:
    """'Février', 'fevrier', 'FEVRIER', 'Févr.', '02', '2' -> 2. None si illisible."""
    if not text:
        return None
    t = text.strip()
    if t.isdigit():
        return int(t) if 1 <= int(t) <= 12 else None
    return _MOIS_NORMALISES.get(_norm(t))


def _variante_mois(numero: int, rng: random.Random) -> str:
    canon = MOIS[numero - 1]
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", canon) if not unicodedata.combining(c))
    candidats = {f"{numero:02d}", canon.upper(), canon.lower(), sans_accent, canon[:4] + "."}
    return rng.choice(sorted(c for c in candidats if c != canon))


def telephone_canonique(value: str | None) -> bool:
    return value is not None and bool(sn.PHONE_CANONICAL_RE.match(value))


def _mal_formate(canonique: str, rng: random.Random) -> str:
    """Formats variants (valides) ou numéros abîmés, comme dans un fichier saisi à la main."""
    prefix, number7 = canonique[5:7], canonique[8:].replace(" ", "")
    choix = [sn.format_phone(prefix, number7, s) for s in sn.PHONE_STYLES[1:]]
    choix += [f"{prefix}-{number7[:3]}-{number7[3:5]}-{number7[5:]}",   # tirets
              f"{prefix} {number7[:3]} {number7[3:5]}",                  # tronqué
              f"221 {prefix}{number7}"]                                  # indicatif sans '+'
    return rng.choice(choix)


def _count_for(rng: random.Random, base: int, gen: GenerationConfig) -> int:
    low, high = math.ceil(gen.taux_anomalie_min * base), math.floor(gen.taux_anomalie_max * base)
    if high < low:
        raise ValueError(f"Table trop petite ({base} lignes) pour un taux de 2 à 5 %.")
    return rng.randint(low, high)


# -----------------------------------------------------------------------------
# Injection
# -----------------------------------------------------------------------------
def inject_anomalies(tables: dict[str, list[dict]], gen: GenerationConfig, rng: random.Random,
                     departements_variantes: dict[int, str]) -> tuple[AnomalyJournal, dict[str, int]]:
    """
    `departements_variantes` : {id_departement: nom canonique} des lignes créées
    comme doublons d'écriture par le générateur (C08, fixé par conception).
    """
    journal = AnomalyJournal(SOURCE, ANOMALY_TYPES)
    bases: dict[str, int] = {}
    ens, dep, sal, abs_ = tables["enseignants"], tables["departements"], tables["salaires"], tables["absences"]
    n_ens, n_sal, n_abs = len(ens), len(sal), len(abs_)
    touches: dict[str, set] = {"enseignants": set(), "salaires": set(), "absences": set()}

    def pick(table: str, rows: list[dict], key: str, k: int, exclude: set = frozenset()) -> list[dict]:
        candidats = [r for r in rows if r[key] not in exclude]
        choisis = rng.sample(candidats, k)
        touches[table].update(r[key] for r in choisis)
        return choisis

    # ---- enseignants : C01 à C06 --------------------------------------------
    for code in ("C01", "C02", "C03", "C04", "C05", "C06"):
        bases[code] = n_ens
    for row in pick("enseignants", ens, "teacher_code", _count_for(rng, n_ens, gen)):
        new = _mal_formate(row["telephone"], rng)
        journal.add("C01", row["teacher_code"], row["telephone"], new)
        row["telephone"] = new
    for row in pick("enseignants", ens, "teacher_code", _count_for(rng, n_ens, gen)):
        journal.add("C02", row["teacher_code"], row["email"], None)
        row["email"] = None

    k03 = _count_for(rng, n_ens, gen)                     # exemples du PDF en premier : IA, Data Science
    ia = [r for r in ens if r["specialite"] == "Intelligence Artificielle"]
    data = [r for r in ens if r["specialite"] == "Science des Données"]
    forcees = [(rng.choice(ia), "IA"), (rng.choice(data), "Data Science")]
    deja = {r["teacher_code"] for r, _ in forcees}
    autres = [(r, rng.choice(VARIANTES_SPECIALITE[r["specialite"]]))
              for r in pick("enseignants", ens, "teacher_code", k03 - 2, deja)]
    touches["enseignants"].update(deja)
    for row, new in forcees + autres:
        journal.add("C03", row["teacher_code"], row["specialite"], new)
        row["specialite"] = new

    avec_grade = [r for r in ens if r["grade"]]
    for row in pick("enseignants", avec_grade, "teacher_code", _count_for(rng, n_ens, gen)):
        new = rng.choice(VARIANTES_GRADE[row["grade"]])
        journal.add("C04", row["teacher_code"], row["grade"], new)
        row["grade"] = new
    for code, col in (("C05", "date_naissance"), ("C06", "date_embauche")):
        for row in pick("enseignants", ens, "teacher_code", _count_for(rng, n_ens, gen)):
            new = format_date(date.fromisoformat(row[col]), rng.choice(("FR", "US")))
            journal.add(code, row["teacher_code"], row[col], new)
            row[col] = new

    # ---- departements : C08 (lignes créées par le générateur), C09 ----------
    bases["C08"] = bases["C09"] = len(dep)
    for row in dep:
        if row["id_departement"] in departements_variantes:
            journal.add("C08", row["id_departement"], departements_variantes[row["id_departement"]],
                        row["nom_departement"])
    for row in rng.sample(dep, 2):                        # « quelques budgets manquants »
        journal.add("C09", row["id_departement"], row["budget_annuel"], None)
        row["budget_annuel"] = None

    # ---- salaires : C10 et C11 disjoints, C13, C14 --------------------------
    for code in ("C10", "C11", "C13", "C14"):
        bases[code] = n_sal
    k10, k11 = _count_for(rng, n_sal, gen), _count_for(rng, n_sal, gen)
    lot = pick("salaires", sal, "id_salaire", k10 + k11)
    for row in lot[:k10]:
        journal.add("C10", row["id_salaire"], row["salaire_net"], -row["salaire_net"])
        row["salaire_net"] = -row["salaire_net"]
    for row in lot[k10:]:
        new = round(row["salaire_base"] * rng.uniform(1.5, 4.0), 2)   # net NON recalculé : incohérence visible
        journal.add("C11", row["id_salaire"], row["primes"], new)
        row["primes"] = new
    for row in pick("salaires", sal, "id_salaire", _count_for(rng, n_sal, gen)):
        new = rng.choice(VARIANTES_MODE[row["mode_paiement"]])
        journal.add("C13", row["id_salaire"], row["mode_paiement"], new)
        row["mode_paiement"] = new
    for row in pick("salaires", sal, "id_salaire", _count_for(rng, n_sal, gen)):
        new = _variante_mois(MOIS.index(row["mois"]) + 1, rng)
        journal.add("C14", row["id_salaire"], row["mois"], new)
        row["mois"] = new

    # ---- absences : C16, C17 / C19 disjoints, C18 ---------------------------
    for code in ("C16", "C17", "C18", "C19"):
        bases[code] = n_abs
    embauche = {r["teacher_code"]: date.fromisoformat(r["_embauche_iso"]) for r in ens}
    for row in pick("absences", abs_, "id_absence", _count_for(rng, n_abs, gen)):
        journal.add("C16", row["id_absence"], row["motif"], None)
        row["motif"] = None
    k17, k19 = _count_for(rng, n_abs, gen), _count_for(rng, n_abs, gen)
    lot = pick("absences", abs_, "id_absence", k17 + k19)
    for row in lot[:k17]:
        if rng.random() < 0.5:
            new = embauche[row["teacher_code"]] - timedelta(days=rng.randint(30, 400))
        else:
            new = gen.date_reference + timedelta(days=rng.randint(30, 400))
        journal.add("C17", row["id_absence"], row["date_absence"], new.isoformat())
        row["date_absence"] = new.isoformat()
    for row in lot[k17:]:
        new = format_date(date.fromisoformat(row["date_absence"]), rng.choice(("FR", "US")))
        journal.add("C19", row["id_absence"], row["date_absence"], new)
        row["date_absence"] = new
    for row in pick("absences", abs_, "id_absence", _count_for(rng, n_abs, gen)):
        new = rng.randint(40, 800)
        journal.add("C18", row["id_absence"], row["duree_heures"], new)
        row["duree_heures"] = new

    # ---- Doublons EN DERNIER, à partir de lignes sans autre anomalie --------
    for code, table, key in (("C07", "enseignants", "teacher_code"), ("C12", "salaires", "id_salaire"),
                             ("C15", "absences", "id_absence")):
        rows = tables[table]
        bases[code] = len(rows)
        sources = rng.sample([r for r in rows if r[key] not in touches[table]], _count_for(rng, len(rows), gen))
        ids_sources = {r[key] for r in sources}
        nouvelles = []
        for r in rows:                                    # copie juste après l'original (export répété)
            nouvelles.append(r)
            if r[key] in ids_sources:
                nouvelles.append(dict(r))
                journal.add(code, r[key], r[key], r[key])
        rows[:] = nouvelles
    return journal, bases


# -----------------------------------------------------------------------------
# Mesure (sur les valeurs telles qu'écrites : chaînes ou nombres)
# -----------------------------------------------------------------------------
def _num(value) -> float | None:
    return None if value in (None, "") else float(value)


def _row_key(row: dict, cols: list[str]) -> tuple:
    return tuple("" if row[c] is None else str(row[c]) for c in cols)


def measure_anomalies(tables: dict[str, list[dict]], cols: dict[str, list[str]],
                      gen: GenerationConfig) -> dict[str, int]:
    ens, dep, sal, abs_ = tables["enseignants"], tables["departements"], tables["salaires"], tables["absences"]
    from common.academic_catalog import DEPARTEMENTS
    embauche = {}
    for r in ens:
        embauche.setdefault(r["teacher_code"], parse_date(r["date_embauche"])[0])

    def duplicates(rows, table):
        return len(rows) - len({_row_key(r, cols[table]) for r in rows})

    def date_non_iso(value):
        return value is not None and parse_date(value)[1] != "ISO"

    def date_incoherente(r):
        d = parse_date(r["date_absence"])[0]
        e = embauche.get(r["teacher_code"])
        return d is not None and (d > gen.date_reference or (e is not None and d < e))

    return {
        "C01": sum(1 for r in _uniques(ens, cols["enseignants"]) if r["telephone"] and not telephone_canonique(r["telephone"])),
        "C02": sum(1 for r in _uniques(ens, cols["enseignants"]) if not r["email"]),
        "C03": sum(1 for r in _uniques(ens, cols["enseignants"]) if r["specialite"] not in SPECIALITES),
        "C04": sum(1 for r in _uniques(ens, cols["enseignants"]) if r["grade"] and r["grade"] not in GRADES),
        "C05": sum(1 for r in _uniques(ens, cols["enseignants"]) if date_non_iso(r["date_naissance"])),
        "C06": sum(1 for r in _uniques(ens, cols["enseignants"]) if date_non_iso(r["date_embauche"])),
        "C07": duplicates(ens, "enseignants"),
        "C08": sum(1 for r in dep if r["nom_departement"] not in DEPARTEMENTS),
        "C09": sum(1 for r in dep if r["budget_annuel"] in (None, "")),
        "C10": sum(1 for r in sal if _num(r["salaire_net"]) < 0),
        "C11": sum(1 for r in sal if _num(r["primes"]) > _num(r["salaire_base"])),
        "C12": duplicates(sal, "salaires"),
        "C13": sum(1 for r in sal if r["mode_paiement"] and r["mode_paiement"] not in MODES_PAIEMENT),
        "C14": sum(1 for r in sal if r["mois"] not in MOIS),
        "C15": duplicates(abs_, "absences"),
        "C16": sum(1 for r in abs_ if not r["motif"]),
        "C17": sum(1 for r in abs_ if date_incoherente(r)),
        "C18": sum(1 for r in abs_ if _num(r["duree_heures"]) > 24),
        "C19": sum(1 for r in abs_ if date_non_iso(r["date_absence"])),
    }


def _uniques(rows: list[dict], cols: list[str]) -> list[dict]:
    """Lignes distinctes (les doublons C07 ne comptent qu'une fois pour C01-C06)."""
    vus, res = set(), []
    for r in rows:
        k = _row_key(r, cols)
        if k not in vus:
            vus.add(k)
            res.append(r)
    return res
