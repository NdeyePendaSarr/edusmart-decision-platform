"""
scripts/constats_sources.py — Constats chiffrés des documents de recherche (Lot L3)
==================================================================================

Recalcule, à partir des 5 sources générées, TOUS les chiffres cités dans
docs/01_operationnel_vers_decision.md et docs/02_besoin_metier.md.
Chaque affirmation chiffrée des documents est ainsi vérifiable.

Ces calculs sont EXPLORATOIRES : ils appliquent des règles volontairement
simples (règle « naïve » contre règle « réaliste ») pour montrer l'effet de
la dispersion et des anomalies. Les valeurs officielles des indicateurs
seront celles du Data Warehouse (lots L5 à L7).

Prérequis : les 5 sources générées (generate_data). Aucune base nécessaire.
Exécution : python -m scripts.constats_sources
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime

from common.config import get_settings
from common.logger import get_logger

logger = get_logger("constats")
LMS_RE = re.compile(r"^LMS-\d{6}$")


def _csv(path, **kw):
    with open(path, encoding=kw.pop("encoding", "utf-8"), newline="") as h:
        return list(csv.DictReader(h, **kw))


def constats() -> dict:
    p = get_settings().paths
    g1, g2 = p.generated_dir / "s1_postgresql", p.generated_dir / "s2_mysql"
    etu, pay = _csv(g1 / "etudiants.csv"), _csv(g1 / "paiements.csv")
    ins, cls, fil = _csv(g1 / "inscriptions.csv"), _csv(g1 / "classes.csv"), _csv(g1 / "filieres.csv")
    notes, con = _csv(g2 / "notes.csv"), _csv(g2 / "temps_connexion.csv")
    prog = _csv(g2 / "progression.csv")
    null = lambda v: None if v in ("", r"\N") else v
    r: dict = {}

    # --- Nombre d'étudiants ------------------------------------------------------
    codes_mysql = {x["student_code"] for t in (notes, prog, con) for x in t}
    r["etudiants_pg"] = len(etu)
    r["codes_mysql_bruts"] = len(codes_mysql)
    r["codes_mysql_valides"] = sum(1 for c in codes_mysql if LMS_RE.match(c))
    r["somme_naive_pg_mysql"] = len(etu) + len(codes_mysql)
    with open(p.mappings_dir / "mapping_etudiants.csv", encoding="utf-8") as h:
        r["paires_mapping"] = sum(1 for _ in h) - 1
    r["personnes_reelles"] = r["etudiants_pg"] + (r["codes_mysql_valides"] - r["paires_mapping"])

    # --- Chiffre d'affaires (PostgreSQL) ----------------------------------------------
    ids_ins = {x["id_inscription"] for x in ins}
    montant = lambda x: float(x["montant"])
    valides = [x for x in pay if x["statut"] == "VALIDE"]
    rattaches = [x for x in valides if x["id_inscription"] in ids_ins]
    r["ca_naif"] = sum(montant(x) for x in pay)
    r["ca_valide"] = sum(montant(x) for x in valides)
    r["ca_valide_rattache"] = sum(montant(x) for x in rattaches)
    r["ca_valide_rattache_abs"] = sum(abs(montant(x)) for x in rattaches)
    r["paiements_orphelins_valides"] = len(valides) - len(rattaches)
    r["paiements_negatifs_rattaches"] = sum(1 for x in rattaches if montant(x) < 0)
    refs = Counter(x["reference"] for x in pay)
    r["lignes_reference_dupliquee"] = sum(n for n in refs.values() if n > 1)
    r["modes_paiement_distincts"] = len({x["mode_paiement"] for x in pay})

    # --- Réussite aux quiz (MySQL) --------------------------------------------------
    r["reussite_naive"] = sum(x["valide"] == "1" for x in notes) / len(notes)
    uniques = {(x["id_quiz"], x["student_code"], x["tentative"], x["date_passage"]): x for x in notes}
    r["notes_sans_doublons"] = len(uniques)
    meilleure = defaultdict(bool)
    for x in uniques.values():
        meilleure[(x["student_code"], x["id_quiz"])] |= x["valide"] == "1"
    r["reussite_par_quiz_etudiant"] = sum(meilleure.values()) / len(meilleure)

    # --- Temps de connexion -----------------------------------------------------------
    durees = [int(x["duree_minutes"]) for x in con if null(x["duree_minutes"]) is not None]
    r["connexion_moyenne_naive"] = statistics.mean(durees)
    r["connexion_moyenne_sans_negatifs"] = statistics.mean(d for d in durees if d >= 0)
    r["connexion_mediane"] = statistics.median(durees)
    r["connexions_sans_fin"] = sum(1 for x in con if null(x["date_deconnexion"]) is None)
    r["connexions_negatives"] = sum(1 for d in durees if d < 0)

    # --- Formations les plus suivies (PostgreSQL) -----------------------------------
    filiere_de = {c["id_classe"]: c["id_filiere"] for c in cls}
    fmap = {f["id_filiere"]: f for f in fil}
    par_libelle, ia = Counter(), 0
    for x in ins:
        f = fmap[filiere_de[x["id_classe"]]]
        par_libelle[f["nom_filiere"]] += 1
        ia += f["departement"] == "Intelligence Artificielle"
    r["top_libelles"] = par_libelle.most_common(3)
    r["ia_par_libelle"] = {k: par_libelle[k] for k in ("Intelligence Artificielle", "IA", "Ingénierie IA")}
    r["ia_unifiee"] = ia

    # --- Qualité des référentiels -----------------------------------------------------
    r["valeurs_sexe"] = dict(Counter(x["sexe"] for x in etu).most_common())
    r["villes_distinctes_pg"] = len({x["ville"] for x in etu})

    # --- MongoDB ------------------------------------------------------------------------
    from sources.s4_mongodb.generate_data import read_events
    ev = list(read_events(p.generated_dir / "s4_mongodb" / "events.jsonl.gz"))
    r["mongo_evenements"] = len(ev)
    r["mongo_ca_payment_success"] = sum(e["metadata"]["amount"] for e in ev if e.get("event_type") == "PAYMENT_SUCCESS"
                                        and isinstance(e.get("metadata"), dict))
    villes = Counter(e.get("city") for e in ev)
    r["mongo_ecritures_dakar"] = {v: n for v, n in villes.items() if isinstance(v, str) and "dak" in v.lower()}
    r["mongo_types_timestamp"] = dict(Counter(type(e.get("timestamp")).__name__ for e in ev))
    sessions = defaultdict(dict)
    for e in ev:
        t = e.get("timestamp")
        if isinstance(t, datetime) and e.get("event_type") in ("LOGIN", "LOGOUT") and e.get("session_id"):
            sessions[e["session_id"]].setdefault(e["event_type"], t)
    durees_m = [(s["LOGOUT"] - s["LOGIN"]).total_seconds() / 60 for s in sessions.values()
                if "LOGIN" in s and "LOGOUT" in s and s["LOGOUT"] >= s["LOGIN"]]
    r["mongo_session_moyenne_min"] = statistics.mean(durees_m)

    # --- CSV RH et Redis --------------------------------------------------------------
    ens = _csv(get_settings().paths.root / "sources" / "s3_csv" / "output" / "enseignants.csv")
    r["enseignants_lignes"], r["enseignants_distincts"] = len(ens), len({x["teacher_code"] for x in ens})
    snap = json.loads((p.generated_dir / "s5_redis" / "snapshot.json").read_text(encoding="utf-8"))
    verite = json.loads((p.referential_dir / "redis_verite.json").read_text(encoding="utf-8"))
    r["redis_online_users_affiche"] = int(snap["online_users"]["value"])
    r["redis_active_students"] = int(snap["statistics:today"]["value"]["active_students"])
    r["redis_sessions_actives_reelles"] = verite["sessions_actives"]
    return r


def main() -> int:
    try:
        r = constats()
    except FileNotFoundError as exc:
        logger.error("Fichier introuvable : %s (générez d'abord les 5 sources)", exc.filename)
        return 1
    for k, v in r.items():
        if isinstance(v, float):
            v = f"{v / 1e9:.3f} Mds XOF" if k.startswith(("ca_", "mongo_ca")) else f"{v:.4f}"
        logger.info("%-34s %s", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
