"""
sources/s1_postgresql/anomalies.py — Anomalies volontaires de la Source 1
========================================================================

Rôle
    1. inject_anomalies() : dégrade des données PROPRES selon le PDF Source 1
       et consigne chaque modification dans le journal (common/anomaly_journal).
    2. measure_anomalies() : recompte chaque type d'anomalie à partir des
       données (en mémoire, CSV ou base PostgreSQL). La porte G1 exige que la
       mesure soit ÉGALE au journal : c'est la preuve que les anomalies sont
       réellement présentes dans la source, ni plus ni moins.

Principe « générer propre, puis dégrader »
    Le générateur produit des données cohérentes ; ce module les abîme ensuite.
    On sait donc exactement ce qui est anormal, ce qui rend l'ETL testable.

Taux
    Chaque type touche entre 2 % et 5 % de sa table de référence (décision
    validée), tiré au hasard dans cet intervalle. Exception : A07 (libellés
    IA) est fixé par le catalogue (2 filières sur 25), comme le décrit le PDF.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

from common import senegalese_data as sn
from common.academic_catalog import FILIERES_PAR_CODE, LIBELLE_IA_CANONIQUE
from common.anomaly_journal import AnomalyJournal, AnomalyType
from common.config import GenerationConfig
from common.seed import deterministic_uuid

SOURCE = "s1_postgresql"
PDF = "Source 1 - PostgreSQL - Gestion Académique.pdf"

# -----------------------------------------------------------------------------
# Catalogue des 16 types d'anomalies (chacun justifié par le PDF)
# -----------------------------------------------------------------------------
ANOMALY_TYPES: dict[str, AnomalyType] = {t.code: t for t in (
    AnomalyType("A01", "etudiants", "sexe", "Sexe non standard (Homme/Femme, Garçon/Fille, 1/0)",
                f"{PDF} - etudiants, Recommandations"),
    AnomalyType("A02", "etudiants", "telephone", "Téléphone manquant",
                f"{PDF} - etudiants, Recommandations (valeurs manquantes)"),
    AnomalyType("A03", "etudiants", "telephone", "Téléphone dans un format non standard",
                f"{PDF} - Contraintes générales (formats différents : téléphones)"),
    AnomalyType("A04", "etudiants", "adresse", "Adresse manquante",
                f"{PDF} - etudiants, Recommandations (valeurs manquantes)"),
    AnomalyType("A05", "etudiants", "ville", "Erreur de saisie sur la ville (casse, espaces, accents)",
                f"{PDF} - Contraintes générales (erreurs de saisie)"),
    AnomalyType("A06", "etudiants", "nom", "Erreur de saisie sur le nom (casse)",
                f"{PDF} - Contraintes générales (erreurs de saisie)"),
    AnomalyType("A07", "filieres", "nom_filiere", "Libellés IA incohérents (IA / Intelligence Artificielle / Ingénierie IA)",
                f"{PDF} - filieres, Recommandations"),
    AnomalyType("A08", "classes", "salle", "Salle écrite différemment (A101 / Salle A101 / A-101)",
                f"{PDF} - classes, Recommandations"),
    AnomalyType("A09", "classes", "annee_academique", "Année académique dans un format non standard",
                f"{PDF} - Contraintes générales (formats différents : dates)"),
    AnomalyType("A10", "inscriptions", "*", "Inscription en double",
                f"{PDF} - inscriptions, Recommandations"),
    AnomalyType("A11", "inscriptions", "reduction", "Réduction supérieure à 100 %",
                f"{PDF} - inscriptions, Recommandations"),
    AnomalyType("A12", "inscriptions", "date_inscription", "Inscription après le début de l'année (1er octobre)",
                f"{PDF} - inscriptions, Recommandations"),
    AnomalyType("A13", "paiements", "reference", "Référence de paiement dupliquée",
                f"{PDF} - paiements, Recommandations"),
    AnomalyType("A14", "paiements", "montant", "Montant négatif",
                f"{PDF} - paiements, Recommandations"),
    AnomalyType("A15", "paiements", "mode_paiement", "Mode de paiement écrit différemment (OM / Orange Money / orange money)",
                f"{PDF} - paiements, Recommandations"),
    AnomalyType("A16", "paiements", "id_inscription", "Paiement orphelin (inscription inexistante)",
                f"{PDF} - paiements, Recommandations + Contraintes générales (violations de FK)"),
)}

# Anomalies dont le taux n'est pas tiré dans [2 %, 5 %]
FIXED_BY_DESIGN = {"A07"}

# -----------------------------------------------------------------------------
# Valeurs canoniques et variantes
# -----------------------------------------------------------------------------
MODES_PAIEMENT_CANONIQUES = ("Orange Money", "Wave", "Espèces", "Virement bancaire", "Carte bancaire")
VARIANTES_MODE_PAIEMENT = {
    "Orange Money": ("OM", "orange money", "ORANGE MONEY", "Orange-Money"),
    "Wave": ("wave", "WAVE"),
    "Espèces": ("Especes", "espèces", "Cash"),
    "Virement bancaire": ("Virement", "virement", "Banque"),
    "Carte bancaire": ("CB", "Carte"),
}
VARIANTES_SEXE = {"M": ("Homme", "Garçon", "1"), "F": ("Femme", "Fille", "0")}

SALLE_CANONIQUE_RE = re.compile(r"^[A-E][1-3]\d{2}$")
ANNEE_CANONIQUE_RE = re.compile(r"^(\d{4})-(\d{4})$")
CODE_CLASSE_ANNEE_RE = re.compile(r"-(\d{2})(\d{2})-[A-Z]$")

_TOUS_LES_NOMS = frozenset(sn.NOMS_DE_FAMILLE)
_TOUTES_LES_VILLES = frozenset(sn.CITY_TO_REGION)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def rentree_depuis_code_classe(code_classe: str, gen: GenerationConfig) -> date:
    """
    Date de rentrée d'une classe, lue dans son code (ex. LIC-GL-2324-A -> 2023-10-01).
    Le code reste canonique ; annee_academique, elle, peut être altérée (A09).
    """
    m = CODE_CLASSE_ANNEE_RE.search(code_classe)
    if not m:
        raise ValueError(f"code_classe inattendu : {code_classe!r}")
    return date(2000 + int(m.group(1)), gen.rentree_mois, gen.rentree_jour)


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _count_for(rng: random.Random, base: int, gen: GenerationConfig) -> int:
    """Nombre de lignes à altérer : entier tiré dans [ceil(2 % base), floor(5 % base)]."""
    low = math.ceil(gen.taux_anomalie_min * base)
    high = math.floor(gen.taux_anomalie_max * base)
    if high < low:
        raise ValueError(f"Table trop petite ({base} lignes) pour un taux de 2 à 5 %.")
    return rng.randint(low, high)


# -----------------------------------------------------------------------------
# Injection
# -----------------------------------------------------------------------------
def inject_anomalies(tables: dict[str, list[dict]], gen: GenerationConfig,
                     rng: random.Random) -> tuple[AnomalyJournal, dict[str, int]]:
    """
    Modifie `tables` EN PLACE. Retourne (journal, bases) où bases[code] est
    la taille de la table de référence utilisée pour calculer le taux.
    """
    journal = AnomalyJournal(SOURCE, ANOMALY_TYPES)
    bases: dict[str, int] = {}
    etudiants, filieres = tables["etudiants"], tables["filieres"]
    classes, inscriptions, paiements = tables["classes"], tables["inscriptions"], tables["paiements"]

    n_etu, n_cls = len(etudiants), len(classes)
    n_ins, n_pay = len(inscriptions), len(paiements)  # tailles AVANT ajout de lignes
    rentree_par_classe = {c["id_classe"]: rentree_depuis_code_classe(c["code_classe"], gen) for c in classes}

    # ---- A01 : sexe ---------------------------------------------------------
    bases["A01"] = n_etu
    for row in rng.sample(etudiants, _count_for(rng, n_etu, gen)):
        new = rng.choice(VARIANTES_SEXE[row["sexe"]])
        journal.add("A01", row["id_etudiant"], row["sexe"], new)
        row["sexe"] = new

    # ---- A02 / A03 : téléphone (ensembles disjoints) ------------------------
    bases["A02"] = bases["A03"] = n_etu
    k02, k03 = _count_for(rng, n_etu, gen), _count_for(rng, n_etu, gen)
    cibles = rng.sample(etudiants, k02 + k03)
    for row in cibles[:k02]:
        journal.add("A02", row["id_etudiant"], row["telephone"], None)
        row["telephone"] = None
    for row in cibles[k02:]:
        canonique = row["telephone"]                       # +221 77 123 45 67
        prefix, number7 = canonique[5:7], canonique[8:].replace(" ", "")
        new = sn.format_phone(prefix, number7, rng.choice(sn.PHONE_STYLES[1:]))
        journal.add("A03", row["id_etudiant"], canonique, new)
        row["telephone"] = new

    # ---- A04 : adresse ------------------------------------------------------
    bases["A04"] = n_etu
    for row in rng.sample(etudiants, _count_for(rng, n_etu, gen)):
        journal.add("A04", row["id_etudiant"], row["adresse"], None)
        row["adresse"] = None

    # ---- A05 : ville (erreurs de saisie) ------------------------------------
    bases["A05"] = n_etu
    for row in rng.sample(etudiants, _count_for(rng, n_etu, gen)):
        ville = row["ville"]
        candidats = {ville.upper(), ville.lower(), f" {ville} ", _strip_accents(ville).upper()}
        candidats = sorted(c for c in candidats if c not in _TOUTES_LES_VILLES)
        new = rng.choice(candidats)
        journal.add("A05", row["id_etudiant"], ville, new)
        row["ville"] = new

    # ---- A06 : nom (casse) --------------------------------------------------
    bases["A06"] = n_etu
    for row in rng.sample(etudiants, _count_for(rng, n_etu, gen)):
        new = rng.choice((row["nom"].upper(), row["nom"].lower()))
        journal.add("A06", row["id_etudiant"], row["nom"], new)
        row["nom"] = new

    # ---- A07 : libellés IA (intégrés au catalogue, journalisés ici) ---------
    bases["A07"] = len(filieres)
    for row in filieres:
        f = FILIERES_PAR_CODE[row["code_filiere"]]
        if f.libelle_canonique == LIBELLE_IA_CANONIQUE and row["nom_filiere"] != LIBELLE_IA_CANONIQUE:
            journal.add("A07", row["id_filiere"], LIBELLE_IA_CANONIQUE, row["nom_filiere"])

    # ---- A08 : salle --------------------------------------------------------
    bases["A08"] = n_cls
    for row in rng.sample(classes, _count_for(rng, n_cls, gen)):
        salle = row["salle"]
        new = rng.choice((f"Salle {salle}", f"{salle[0]}-{salle[1:]}"))
        journal.add("A08", row["id_classe"], salle, new)
        row["salle"] = new

    # ---- A09 : format de l'année académique ---------------------------------
    bases["A09"] = n_cls
    for row in rng.sample(classes, _count_for(rng, n_cls, gen)):
        a, b = ANNEE_CANONIQUE_RE.match(row["annee_academique"]).groups()
        new = rng.choice((f"{a}/{b}", f"{a}-{b[2:]}", f"{a[2:]}-{b[2:]}", f"{a} - {b}"))
        journal.add("A09", row["id_classe"], row["annee_academique"], new)
        row["annee_academique"] = new

    # ---- A10 : doublons d'inscriptions (nouvel identifiant, même contenu) ---
    # Réalisé AVANT A11/A12 : les copies sont faites à partir de lignes propres.
    bases["A10"] = n_ins
    for row in rng.sample(inscriptions[:n_ins], _count_for(rng, n_ins, gen)):
        copie = dict(row, id_inscription=deterministic_uuid(rng))
        inscriptions.append(copie)
        journal.add("A10", copie["id_inscription"], row["id_inscription"], copie["id_inscription"])

    # ---- A11 / A12 : uniquement sur les inscriptions d'origine ---------------
    # (les copies A10 gardent les valeurs propres : chaque anomalie est comptée une fois)
    bases["A11"] = bases["A12"] = n_ins
    for row in rng.sample(inscriptions[:n_ins], _count_for(rng, n_ins, gen)):
        new = round(rng.uniform(100.5, 200.0), 2)
        journal.add("A11", row["id_inscription"], row["reduction"], new)
        row["reduction"] = new
    for row in rng.sample(inscriptions[:n_ins], _count_for(rng, n_ins, gen)):
        new = rentree_par_classe[row["id_classe"]] + timedelta(days=rng.randint(10, 150))
        journal.add("A12", row["id_inscription"], row["date_inscription"], new)
        row["date_inscription"] = new

    # ---- A13 : références dupliquées (paires disjointes : groupes de 2) -----
    bases["A13"] = n_pay
    k13 = _count_for(rng, n_pay, gen)
    choisis = rng.sample(paiements, 2 * k13)
    for cible, modele in zip(choisis[:k13], choisis[k13:]):
        journal.add("A13", cible["id_paiement"], cible["reference"], modele["reference"])
        cible["reference"] = modele["reference"]

    # ---- A14 : montants négatifs --------------------------------------------
    bases["A14"] = n_pay
    for row in rng.sample(paiements, _count_for(rng, n_pay, gen)):
        journal.add("A14", row["id_paiement"], row["montant"], -row["montant"])
        row["montant"] = -row["montant"]

    # ---- A15 : écritures du mode de paiement --------------------------------
    bases["A15"] = n_pay
    for row in rng.sample(paiements, _count_for(rng, n_pay, gen)):
        new = rng.choice(VARIANTES_MODE_PAIEMENT[row["mode_paiement"]])
        journal.add("A15", row["id_paiement"], row["mode_paiement"], new)
        row["mode_paiement"] = new

    # ---- A16 : paiements orphelins (nouvelles lignes) -----------------------
    bases["A16"] = n_pay
    modeles = rng.sample(paiements[:n_pay], _count_for(rng, n_pay, gen))
    seq = len(paiements)
    for modele in modeles:
        seq += 1
        orphelin = dict(
            modele,
            id_paiement=deterministic_uuid(rng),
            id_inscription=deterministic_uuid(rng),   # n'existe pas dans inscriptions
            reference=f"PAY-{_as_date(modele['date_paiement']).year}-{seq:06d}",
            montant=abs(modele["montant"]),
            mode_paiement=rng.choice(MODES_PAIEMENT_CANONIQUES),
            statut="VALIDE",
        )
        paiements.append(orphelin)
        journal.add("A16", orphelin["id_paiement"], None, orphelin["id_inscription"])

    return journal, bases


# -----------------------------------------------------------------------------
# Mesure (mêmes règles pour la mémoire, les CSV et la base)
# -----------------------------------------------------------------------------
def measure_anomalies(tables: dict[str, list[dict]], gen: GenerationConfig) -> dict[str, int]:
    """Recompte chaque type d'anomalie directement dans les données."""
    etu, fil = tables["etudiants"], tables["filieres"]
    cls, ins, pay = tables["classes"], tables["inscriptions"], tables["paiements"]
    rentree = {c["id_classe"]: rentree_depuis_code_classe(c["code_classe"], gen) for c in cls}
    ids_inscriptions = {str(i["id_inscription"]) for i in ins}
    refs = Counter(p["reference"] for p in pay)

    return {
        "A01": sum(1 for e in etu if e["sexe"] not in ("M", "F")),
        "A02": sum(1 for e in etu if e["telephone"] is None),
        "A03": sum(1 for e in etu if e["telephone"] is not None
                   and not sn.PHONE_CANONICAL_RE.match(e["telephone"])),
        "A04": sum(1 for e in etu if e["adresse"] is None),
        "A05": sum(1 for e in etu if e["ville"] not in _TOUTES_LES_VILLES),
        "A06": sum(1 for e in etu if e["nom"] not in _TOUS_LES_NOMS),
        "A07": sum(1 for f in fil if f["nom_filiere"] in ("IA", "Ingénierie IA")),
        "A08": sum(1 for c in cls if not SALLE_CANONIQUE_RE.match(c["salle"] or "")),
        "A09": sum(1 for c in cls if not ANNEE_CANONIQUE_RE.match(c["annee_academique"])),
        "A10": len(ins) - len({(str(i["id_etudiant"]), str(i["id_classe"])) for i in ins}),
        "A11": sum(1 for i in ins if i["reduction"] is not None and i["reduction"] > 100),
        "A12": sum(1 for i in ins if _as_date(i["date_inscription"]) >= rentree[i["id_classe"]]),
        "A13": sum(n - 1 for n in refs.values() if n > 1),
        "A14": sum(1 for p in pay if p["montant"] < 0),
        "A15": sum(1 for p in pay if p["mode_paiement"] not in MODES_PAIEMENT_CANONIQUES),
        "A16": sum(1 for p in pay if str(p["id_inscription"]) not in ids_inscriptions),
    }
