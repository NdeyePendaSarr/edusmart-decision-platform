"""
sources/s2_mysql/anomalies.py — Anomalies volontaires de la Source 2
===================================================================

Même principe que la Source 1 : générer propre, dégrader, journaliser,
puis MESURER avec les mêmes règles en mémoire et dans MySQL.

Codes B01 à B16 (les codes A01 à A16 sont ceux de PostgreSQL).
Chaque type touche entre 2 % et 5 % de sa table de référence.

Ordre d'injection important (pour que chaque anomalie soit comptée une fois) :
    - doublons (B12, B15) créés AVANT les autres anomalies de la même table,
      à partir de lignes propres ;
    - les anomalies qui modifient la CLÉ de détection des doublons
      (B13 student_code, B07 id_module) évitent les lignes dupliquées.
"""

from __future__ import annotations

import ipaddress
import math
import random
import re
from collections import Counter

from common.anomaly_journal import AnomalyJournal, AnomalyType
from common.config import GenerationConfig
from common.learning_catalog import APPAREILS, CATEGORIES
from common.seed import deterministic_uuid

SOURCE = "s2_mysql"
PDF = "Source 2 - MySQL - Plateforme pédagogique.pdf"

ANOMALY_TYPES: dict[str, AnomalyType] = {t.code: t for t in (
    AnomalyType("B01", "modules", "categorie", "Catégorie écrite différemment (Data, DATA, data science)",
                f"{PDF} - modules, Recommandations"),
    AnomalyType("B02", "modules", "actif", "Module inactif (mais encore suivi)",
                f"{PDF} - modules, Recommandations"),
    AnomalyType("B03", "cours", "titre", "Titre de cours en double",
                f"{PDF} - cours, Recommandations"),
    AnomalyType("B04", "quiz", "duree_minutes", "Durée de quiz incohérente (nulle, trop courte ou trop longue)",
                f"{PDF} - quiz, Recommandations"),
    AnomalyType("B05", "progression", "pourcentage", "Progression supérieure à 100 %",
                f"{PDF} - progression, Recommandations"),
    AnomalyType("B06", "progression", "pourcentage", "Progression négative",
                f"{PDF} - progression, Recommandations"),
    AnomalyType("B07", "progression", "id_module", "Progression sur un module inexistant",
                f"{PDF} - progression, Recommandations"),
    AnomalyType("B08", "temps_connexion", "date_deconnexion", "Connexion sans déconnexion (durée absente)",
                f"{PDF} - temps_connexion, Recommandations"),
    AnomalyType("B09", "temps_connexion", "duree_minutes", "Durée de connexion négative",
                f"{PDF} - temps_connexion, Recommandations"),
    AnomalyType("B10", "temps_connexion", "adresse_ip", "Adresse IP invalide",
                f"{PDF} - temps_connexion, Recommandations"),
    AnomalyType("B11", "temps_connexion", "appareil", "Appareil écrit différemment (Mobile, mobile, Téléphone)",
                f"{PDF} - temps_connexion, Recommandations"),
    AnomalyType("B12", "notes", "*", "Résultat de quiz en double",
                f"{PDF} - Contraintes générales (doublons)"),
    AnomalyType("B13", "notes", "student_code", "student_code hors format LMS-XXXXXX",
                f"{PDF} - Contraintes générales (identifiants incompatibles)"),
    AnomalyType("B14", "notes", "score", "Score supérieur au score maximal du quiz",
                f"{PDF} - Contraintes générales (incohérences)"),
    AnomalyType("B15", "progression", "*", "Deux progressions pour un même étudiant et un même module",
                f"{PDF} - Contraintes générales (doublons) + règle « une seule progression »"),
    AnomalyType("B16", "temps_connexion", "navigateur", "Navigateur manquant",
                f"{PDF} - Contraintes générales (valeurs manquantes)"),
)}

STUDENT_CODE_RE = re.compile(r"^LMS-\d{6}$")

VARIANTES_CATEGORIE: dict[str, tuple[str, ...]] = {
    "Data": ("DATA", "data science", "data", "Data Science"),
    "IA": ("Intelligence Artificielle", "ia", "AI"),
    "Développement": ("Developpement", "développement", "DEV"),
    "Réseaux": ("Reseaux", "réseaux", "RESEAUX"),
    "Cybersécurité": ("Cybersecurite", "cybersécurité", "Cyber"),
    "Management": ("management", "MANAGEMENT", "Mgmt"),
    "Finance": ("finance", "FINANCE"),
    "Marketing": ("marketing", "MARKETING", "Marketing Digital"),
}
VARIANTES_APPAREIL: dict[str, tuple[str, ...]] = {
    "Mobile": ("mobile", "Téléphone", "MOBILE", "Smartphone"),
    "PC": ("pc", "Ordinateur", "Desktop"),
    "Tablette": ("tablette", "Tablet", "TABLETTE"),
}


def _count_for(rng: random.Random, base: int, gen: GenerationConfig) -> int:
    low, high = math.ceil(gen.taux_anomalie_min * base), math.floor(gen.taux_anomalie_max * base)
    if high < low:
        raise ValueError(f"Table trop petite ({base} lignes) pour un taux de 2 à 5 %.")
    return rng.randint(low, high)


def quiz_duree_incoherente(duree, nb_questions) -> bool:
    """Durée nulle ou négative, ou moins de 15 s / plus de 10 min par question."""
    if duree is None or nb_questions in (None, 0):
        return False
    return duree <= 0 or duree / nb_questions < 0.25 or duree / nb_questions > 10


def ip_invalide(value) -> bool:
    if value is None:
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        return True


def _invalid_ip(rng: random.Random) -> str:
    a, b, c = rng.randint(1, 255), rng.randint(0, 255), rng.randint(0, 255)
    return rng.choice((
        f"{rng.randint(256, 999)}.{a}.{b}.{c}",     # octet hors borne
        f"{a}.{b}.{c}",                              # octet manquant
        f"{a}.{b}.{c}.{rng.randint(0, 255)}.{b}",    # octet en trop
        "abc.def.ghi.jkl",                           # texte
        f"2001:db8::{rng.randint(0, 9)}zz",          # IPv6 invalide
        "localhost",
    ))


def _bad_student_code(code: str, rng: random.Random) -> str:
    num = code[4:]
    return rng.choice((f"LMS{num}", code.lower(), f"LMS-{int(num)}", f"LMS_{num}", f" {code}"))


# -----------------------------------------------------------------------------
# Injection
# -----------------------------------------------------------------------------
def inject_anomalies(tables: dict[str, list[dict]], gen: GenerationConfig,
                     rng: random.Random) -> tuple[AnomalyJournal, dict[str, int]]:
    journal = AnomalyJournal(SOURCE, ANOMALY_TYPES)
    bases: dict[str, int] = {}
    modules, cours, quiz = tables["modules"], tables["cours"], tables["quiz"]
    notes, progression, connexions = tables["notes"], tables["progression"], tables["temps_connexion"]
    n_mod, n_cou, n_qui = len(modules), len(cours), len(quiz)
    n_not, n_pro, n_con = len(notes), len(progression), len(connexions)

    # ---- B01 : catégories (les 2 premières reprennent l'exemple du PDF) -----
    bases["B01"] = n_mod
    k = _count_for(rng, n_mod, gen)
    data_mods = [m for m in modules if m["categorie"] == "Data"]
    forcees = rng.sample(data_mods, 2)
    ids_forcees = {m["id_module"] for m in forcees}
    autres = rng.sample([m for m in modules if m["id_module"] not in ids_forcees], k - 2)
    for row, new in zip(forcees, ("DATA", "data science")):
        journal.add("B01", row["id_module"], row["categorie"], new)
        row["categorie"] = new
    for row in autres:
        new = rng.choice(VARIANTES_CATEGORIE[row["categorie"]])
        journal.add("B01", row["id_module"], row["categorie"], new)
        row["categorie"] = new

    # ---- B02 : modules inactifs ---------------------------------------------
    bases["B02"] = n_mod
    for row in rng.sample(modules, _count_for(rng, n_mod, gen)):
        journal.add("B02", row["id_module"], 1, 0)
        row["actif"] = False

    # ---- B03 : titres de cours en double (paires disjointes) ----------------
    bases["B03"] = n_cou
    k = _count_for(rng, n_cou, gen)
    choisis = rng.sample(cours, 2 * k)
    for cible, modele in zip(choisis[:k], choisis[k:]):
        journal.add("B03", cible["id_cours"], cible["titre"], modele["titre"])
        cible["titre"] = modele["titre"]

    # ---- B04 : durées de quiz incohérentes ----------------------------------
    bases["B04"] = n_qui
    for row in rng.sample(quiz, _count_for(rng, n_qui, gen)):
        nb = row["nb_questions"]
        new = rng.choice((0, max(1, nb // 6), nb * rng.randint(15, 40)))
        journal.add("B04", row["id_quiz"], row["duree_minutes"], new)
        row["duree_minutes"] = new

    # ---- B15 : doublons de progression (AVANT B05-B07) ----------------------
    bases["B15"] = n_pro
    dupliquees = rng.sample(range(n_pro), _count_for(rng, n_pro, gen))
    for i in dupliquees:
        copie = dict(progression[i], id_progression=deterministic_uuid(rng))
        progression.append(copie)
        journal.add("B15", copie["id_progression"], progression[i]["id_progression"], copie["id_progression"])

    # ---- B05 / B06 / B07 : ensembles disjoints de progressions d'origine ----
    bases["B05"] = bases["B06"] = bases["B07"] = n_pro
    k5, k6, k7 = (_count_for(rng, n_pro, gen) for _ in range(3))
    sources_dup = set(dupliquees)
    candidats_b07 = [i for i in range(n_pro) if i not in sources_dup]  # B07 modifie la clé des doublons
    idx7 = rng.sample(candidats_b07, k7)
    set7 = set(idx7)
    reste = [i for i in range(n_pro) if i not in set7]
    idx56 = rng.sample(reste, k5 + k6)
    for i in idx56[:k5]:
        row = progression[i]
        new = round(rng.uniform(100.5, 150.0), 2)
        journal.add("B05", row["id_progression"], row["pourcentage"], new)
        row["pourcentage"] = new
    for i in idx56[k5:]:
        row = progression[i]
        new = round(rng.uniform(-50.0, -0.5), 2)
        journal.add("B06", row["id_progression"], row["pourcentage"], new)
        row["pourcentage"] = new
    for i in idx7:
        row = progression[i]
        new = deterministic_uuid(rng)  # aucun module ne porte cet identifiant
        journal.add("B07", row["id_progression"], row["id_module"], new)
        row["id_module"] = new

    # ---- B12 : doublons de notes (AVANT B13 / B14) --------------------------
    bases["B12"] = n_not
    dup_notes = rng.sample(range(n_not), _count_for(rng, n_not, gen))
    for i in dup_notes:
        copie = dict(notes[i], id_note=deterministic_uuid(rng))
        notes.append(copie)
        journal.add("B12", copie["id_note"], notes[i]["id_note"], copie["id_note"])

    # ---- B13 : student_code incompatibles (hors lignes dupliquées) ----------
    bases["B13"] = n_not
    sources_dup_notes = set(dup_notes)
    candidats = [i for i in range(n_not) if i not in sources_dup_notes]
    for i in rng.sample(candidats, _count_for(rng, n_not, gen)):
        row = notes[i]
        new = _bad_student_code(row["student_code"], rng)
        journal.add("B13", row["id_note"], row["student_code"], new)
        row["student_code"] = new

    # ---- B14 : score > score_max --------------------------------------------
    bases["B14"] = n_not
    score_max = {q["id_quiz"]: q["score_max"] for q in quiz}
    for i in rng.sample(range(n_not), _count_for(rng, n_not, gen)):
        row = notes[i]
        smax = score_max[row["id_quiz"]]
        new = min(999.99, round(smax * rng.uniform(1.05, 1.5), 2))
        journal.add("B14", row["id_note"], row["score"], new)
        row["score"] = new

    # ---- B08 / B09 / B10 / B11 / B16 : connexions ---------------------------
    for code in ("B08", "B09", "B10", "B11", "B16"):
        bases[code] = n_con
    k8, k9 = _count_for(rng, n_con, gen), _count_for(rng, n_con, gen)
    idx = rng.sample(range(n_con), k8 + k9)            # B08 et B09 disjoints
    for i in idx[:k8]:
        row = connexions[i]
        journal.add("B08", row["id_connexion"], row["date_deconnexion"], None)
        row["date_deconnexion"], row["duree_minutes"] = None, None
    for i in idx[k8:]:
        row = connexions[i]
        journal.add("B09", row["id_connexion"], row["duree_minutes"], -row["duree_minutes"])
        row["duree_minutes"] = -row["duree_minutes"]
    for row in rng.sample(connexions, _count_for(rng, n_con, gen)):
        new = _invalid_ip(rng)
        journal.add("B10", row["id_connexion"], row["adresse_ip"], new)
        row["adresse_ip"] = new
    k11 = _count_for(rng, n_con, gen)
    mobiles = [c for c in connexions if c["appareil"] == "Mobile"]
    forcees = rng.sample(mobiles, 2)                   # exemples du PDF : mobile, Téléphone
    ids_forcees = {c["id_connexion"] for c in forcees}
    autres = rng.sample([c for c in connexions if c["id_connexion"] not in ids_forcees], k11 - 2)
    for row, new in zip(forcees, ("mobile", "Téléphone")):
        journal.add("B11", row["id_connexion"], row["appareil"], new)
        row["appareil"] = new
    for row in autres:
        new = rng.choice(VARIANTES_APPAREIL[row["appareil"]])
        journal.add("B11", row["id_connexion"], row["appareil"], new)
        row["appareil"] = new
    for row in rng.sample(connexions, _count_for(rng, n_con, gen)):
        journal.add("B16", row["id_connexion"], row["navigateur"], None)
        row["navigateur"] = None

    return journal, bases


# -----------------------------------------------------------------------------
# Mesure (mêmes règles en mémoire et dans MySQL)
# -----------------------------------------------------------------------------
def measure_anomalies(tables: dict[str, list[dict]]) -> dict[str, int]:
    modules, cours, quiz = tables["modules"], tables["cours"], tables["quiz"]
    notes, progression, connexions = tables["notes"], tables["progression"], tables["temps_connexion"]
    ids_modules = {m["id_module"] for m in modules}
    score_max = {q["id_quiz"]: q["score_max"] for q in quiz}
    titres = Counter(c["titre"] for c in cours)
    canon_cat, canon_app = set(CATEGORIES), set(APPAREILS)
    return {
        "B01": sum(1 for m in modules if m["categorie"] not in canon_cat),
        "B02": sum(1 for m in modules if not m["actif"]),
        "B03": sum(n - 1 for n in titres.values() if n > 1),
        "B04": sum(1 for q in quiz if quiz_duree_incoherente(q["duree_minutes"], q["nb_questions"])),
        "B05": sum(1 for p in progression if p["pourcentage"] is not None and p["pourcentage"] > 100),
        "B06": sum(1 for p in progression if p["pourcentage"] is not None and p["pourcentage"] < 0),
        "B07": sum(1 for p in progression if p["id_module"] not in ids_modules),
        "B08": sum(1 for c in connexions if c["date_deconnexion"] is None),
        "B09": sum(1 for c in connexions if c["duree_minutes"] is not None and c["duree_minutes"] < 0),
        "B10": sum(1 for c in connexions if ip_invalide(c["adresse_ip"])),
        "B11": sum(1 for c in connexions if c["appareil"] not in canon_app),
        "B12": len(notes) - len({(n["id_quiz"], n["student_code"], n["tentative"], n["date_passage"])
                                 for n in notes}),
        "B13": sum(1 for n in notes if not STUDENT_CODE_RE.match(n["student_code"])),
        "B14": sum(1 for n in notes if n["score"] > score_max[n["id_quiz"]]),
        "B15": len(progression) - len({(p["student_code"], p["id_module"]) for p in progression}),
        "B16": sum(1 for c in connexions if c["navigateur"] is None),
    }
