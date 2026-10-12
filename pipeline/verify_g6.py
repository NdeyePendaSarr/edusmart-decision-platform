"""
pipeline/verify_g6.py — Porte G6 : le pipeline est-il fiable de bout en bout ? (Lot L9, Phase 15)
================================================================================================

PDF Phase 15, TP : « Créer des tests permettant de vérifier :
    toutes les lignes ont-elles été extraites ? · toutes les lignes ont-elles été chargées ?
    des données ont-elles été perdues ? · des erreurs sont-elles apparues ?
    les clés sont-elles toujours valides ? »

Une section de contrôles par question, plus une non-régression des KPI :

    G6.1 Extraction   source (recomptée maintenant) = manifeste du lot = journal EXTRACT (17 objets).
                      Redis est volatile (PDF Source 5) : sa référence est l'instant d'extraction
                      (manifeste = journal), jamais un recomptage tardif.
    G6.2 Chargement   staging (lignes du lot) = manifeste = journal LOAD, et aucune ligne d'un autre lot.
    G6.3 Pertes       équation de conservation, couche par couche :
                        staging = clean + lignes rejetées DISTINCTES (16 tables, une ligne = une ligne) ;
                        Redis par famille de clés (clé, message ou membre selon la famille) ;
                        clean = fait du DW (8 faits) ; quality.synthese conforme aux comptages réels.
    G6.4 Erreurs      journal du lot : chaque étape attendue présente, dernière exécution SUCCES,
                      aucune étape restée EN_COURS, aucune erreur ; metadata_sources à jour.
    G6.5 Clés         clés étrangères des 8 faits, membres « Inconnu », version courante unique (SCD 2),
                      clés primaires de la couche clean, intégrité référentielle garantie par les rejets.
    G6.6 Non-régression  les 8 KPI (dw.v_kpi) = valeurs validées en L7 (G5a 8/8), à tolérance explicite.

Ce que G6 apporte par rapport à G2, G3, G4 : une vue de BOUT EN BOUT (source -> staging -> clean +
rejets -> DW) et une référence figée des KPI. Les listes de contrôles de G4 (FK, faits) et du rapport
qualité (tables) sont RÉUTILISÉES, jamais recopiées.

Toutes les requêtes sont en LECTURE seule : G6 peut s'exécuter dans une transaction que l'on annule
(c'est ce que font les tests de mutation de tests/test_pipeline_integration.py).
G6 n'écrit pas dans meta.etl_execution_log : son propre résultat fausserait le contrôle G6.4
lors de l'exécution suivante (décision D-L9-03, docs/15_tests_pipeline.md).

Rapport : data/reports/G6_<lot>.md
    python -m pipeline.verify_g6
    python -m pipeline.verify_g6 --sans-recomptage     # n'interroge pas les 4 sources (G6.1 partiel)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Iterable

from common.config import get_settings
from common.logger import get_logger
from pipeline.registry import OBJECTS, SOURCES, STAGING_SCHEMA

logger = get_logger("verify_g6")

# -----------------------------------------------------------------------------
# Les questions du PDF (Phase 15) : une section de contrôles par question
# -----------------------------------------------------------------------------
QUESTIONS = {
    "G6.1": "Toutes les lignes ont-elles été extraites ?",
    "G6.2": "Toutes les lignes ont-elles été chargées ?",
    "G6.3": "Des données ont-elles été perdues ?",
    "G6.4": "Des erreurs sont-elles apparues ?",
    "G6.5": "Les clés sont-elles toujours valides ?",
    "G6.6": "Les KPI validés en L7 sont-ils inchangés ? (non-régression)",
}

# -----------------------------------------------------------------------------
# Référence des KPI : valeurs validées en L7 (porte G5a 8/8, SQL = Python),
# confirmées en L8 (G5b 8/8, DAX), transmises le 12/10/2026. Toute modification du
# pipeline qui change un de ces chiffres doit être EXPLIQUÉE avant de mettre à jour la référence.
# -----------------------------------------------------------------------------
REFERENCE_KPI: dict[str, Decimal] = {
    "CA": Decimal("13553901000"),                  # XOF : égalité exacte
    "RECOUVREMENT": Decimal("0.9010161429"),       # ratio, 10 décimales transmises
    "REUSSITE": Decimal("0.9312865375"),
    "ABANDON": Decimal("0.0624163807"),
    "PROGRESSION": Decimal("65.58830429"),         # pourcentage moyen, 8 décimales transmises
    "ACTIFS_30J": Decimal("3003"),                 # effectif : égalité exacte
    "CONNEXION_MEDIANE": Decimal("1740"),          # secondes : égalité exacte
    "ETUDIANTS": Decimal("10500"),                 # effectif : égalité exacte
}
# Tolérance par KPI : nulle pour les montants et les effectifs ; pour les valeurs transmises tronquées,
# un ordre de grandeur au-dessus de la troncature (10 décimales -> 1e-9 ; 8 décimales -> 1e-6).
TOLERANCE_KPI: dict[str, Decimal] = {
    "CA": Decimal(0), "ACTIFS_30J": Decimal(0), "CONNEXION_MEDIANE": Decimal(0), "ETUDIANTS": Decimal(0),
    "RECOUVREMENT": Decimal("1e-9"), "REUSSITE": Decimal("1e-9"), "ABANDON": Decimal("1e-9"),
    "PROGRESSION": Decimal("1e-6"),
}

# -----------------------------------------------------------------------------
# Étapes attendues dans meta.etl_execution_log pour un lot complet (run_pipeline.py)
# -----------------------------------------------------------------------------
ETAPES_JOURNAL = ("EXTRACT", "LOAD", "TRANSFORM", "VERIFY", "DW")

# Clé de substitution de chaque dimension (membre « Inconnu » = -1)
CLES_DIMENSIONS = {"dim_temps": "date_key", "dim_region": "region_key", "dim_formation": "formation_key",
                   "dim_module": "module_key", "dim_quiz": "quiz_key", "dim_enseignant": "enseignant_key",
                   "dim_etudiant": "etudiant_key"}

# Intégrité référentielle de la couche clean, GARANTIE par une règle de rejet de L5 :
# (libellé, table enfant, colonne, table parent, colonne, règle de rejet qui la garantit)
INTEGRITE_CLEAN = (
    ("paiements -> inscriptions", "paiements", "id_inscription", "inscriptions", "id_inscription", "PG_PAIEMENT_ORPHELIN"),
    ("inscriptions -> etudiants", "inscriptions", "id_etudiant", "etudiants", "id_etudiant", "PG_INSCRIPTION_ORPHELINE"),
    ("inscriptions -> classes", "inscriptions", "id_classe", "classes", "id_classe", "PG_INSCRIPTION_ORPHELINE"),
    ("progression -> modules", "progression", "id_module", "modules", "id_module", "MY_PROGRESSION_MODULE_INCONNU"),
)

# Familles de clés Redis (PDF Source 5) et table clean qui les reçoit
FAMILLES_ETUDIANT = ("last_course", "last_quiz", "progress", "notifications")
CLEAN_FAMILLE = {"last_course": "redis_last_course", "last_quiz": "redis_last_quiz", "progress": "redis_progress"}
COMPTEURS_REDIS = {"online_users": 1, "statistics:today": 4}   # lignes produites dans clean.redis_compteurs


@dataclass
class Check:
    code: str
    libelle: str
    ok: bool
    detail: str


@dataclass
class Contexte:
    """Ce dont les sections ont besoin : le lot contrôlé, son manifeste, la façon de recompter une source."""
    batch_id: str
    manifeste: dict | None                        # None : manifeste introuvable (data/landing/<lot>/)
    recompter: Callable[[str, str], int] | None   # None : pas de recomptage des sources (--sans-recomptage)
    journal: dict = field(default_factory=dict)   # (etape, source, objet) -> dernière ligne du journal
    echecs_anterieurs: int = 0                    # lignes ECHEC remplacées ensuite par un SUCCES


# =============================================================================
# Fonctions PURES (testées sans base : tests/test_verify_g6.py)
# =============================================================================
def fmt(n) -> str:
    """12345 -> '12 345' (espace fine des rapports existants)."""
    return f"{n:,}".replace(",", " ") if isinstance(n, int) else str(n)


def derniers_par_cle(lignes: Iterable[tuple]) -> tuple[dict, int]:
    """
    lignes : (id_execution, etape, code_source, objet, statut, nb_lignes, nb_erreurs).
    Retourne ({(etape, source, objet): (statut, nb_lignes, nb_erreurs)} pour la DERNIÈRE exécution de
    chaque étape, nombre d'échecs ensuite relancés avec succès).
    Une étape relancée (ex. rechargement idempotent) n'est jugée que sur sa dernière exécution.
    """
    derniers, echecs = {}, {}
    for id_exec, etape, source, objet, statut, nb, nb_err in sorted(lignes, key=lambda r: r[0]):
        cle = (etape, source, objet)
        derniers[cle] = (statut, nb, nb_err or 0)
        if statut == "ECHEC":
            echecs[cle] = echecs.get(cle, 0) + 1
    rattrapes = sum(n for cle, n in echecs.items() if derniers[cle][0] == "SUCCES")
    return derniers, rattrapes


def attendus_journal() -> dict[str, set]:
    """Clés (etape, source, objet) qu'un lot COMPLET doit avoir dans meta.etl_execution_log (run_pipeline.py)."""
    return {
        "EXTRACT": {("EXTRACT", o.source, o.objet) for o in OBJECTS},
        "LOAD": {("LOAD", o.source, o.objet) for o in OBJECTS},
        "TRANSFORM": {("TRANSFORM", s, "*") for s in SOURCES},
        "VERIFY": {("VERIFY", "*", "G3")},
        "DW": {("DW", "*", "dw")},
    }


def evaluer_couverture(attendus: set, derniers: dict) -> tuple[bool, str]:
    """Chaque étape attendue est présente et sa dernière exécution est un SUCCES."""
    absentes = sorted(f"{s}.{o}" for e, s, o in attendus if (e, s, o) not in derniers)
    ko = sorted(f"{s}.{o}={derniers[(e, s, o)][0]}" for e, s, o in attendus
                if (e, s, o) in derniers and derniers[(e, s, o)][0] != "SUCCES")
    if not absentes and not ko:
        return True, f"{len(attendus)}/{len(attendus)} présentes, dernière exécution SUCCES"
    morceaux = ([f"absentes : {', '.join(absentes[:5])}{' …' if len(absentes) > 5 else ''}"] if absentes else []) + \
               ([f"en échec : {', '.join(ko[:5])}{' …' if len(ko) > 5 else ''}"] if ko else [])
    return False, " ; ".join(morceaux)


def evaluer_extraction(n_source: int | None, n_manifeste: int | None, journal: tuple | None,
                       volatile: bool = False) -> tuple[bool, str]:
    """
    Q1 : source = manifeste = journal EXTRACT (SUCCES).
    volatile (Redis) ou n_source None (recomptage désactivé) : manifeste = journal seulement.
    """
    if n_manifeste is None:
        return False, "objet absent du manifeste du lot"
    if journal is None:
        return False, f"manifeste={fmt(n_manifeste)}, aucune trace EXTRACT dans le journal"
    statut, n_journal, _ = journal
    if statut != "SUCCES":
        return False, f"journal EXTRACT = {statut}"
    ok = n_journal == n_manifeste
    if volatile:
        return ok, (f"manifeste={fmt(n_manifeste)}, journal={fmt(n_journal)} "
                    f"(source volatile : référence = instant d'extraction)")
    if n_source is None:
        return ok, f"manifeste={fmt(n_manifeste)}, journal={fmt(n_journal)} (source non recomptée)"
    return ok and n_source == n_manifeste, f"source={fmt(n_source)}, manifeste={fmt(n_manifeste)}, journal={fmt(n_journal)}"


def evaluer_chargement(n_lot: int, n_total: int, n_manifeste: int | None, journal: tuple | None) -> tuple[bool, str]:
    """Q2 : staging (lignes du lot) = manifeste = journal LOAD (SUCCES), et aucune ligne d'un autre lot."""
    if n_manifeste is None:
        return False, f"staging={fmt(n_lot)}, objet absent du manifeste"
    if journal is None:
        return False, f"staging={fmt(n_lot)}, aucune trace LOAD dans le journal"
    statut, n_journal, _ = journal
    autres = n_total - n_lot
    ok = statut == "SUCCES" and n_lot == n_manifeste == n_journal and autres == 0
    detail = f"staging={fmt(n_lot)}, manifeste={fmt(n_manifeste)}, journal LOAD={fmt(n_journal)} ({statut})"
    return ok, detail + (f" ; {fmt(autres)} ligne(s) d'un autre lot" if autres else "")


def equation_conservation(entree: int, sorties: dict[str, int]) -> tuple[bool, str]:
    """Q3 : entree = somme des sorties. sorties : {'clean': n, 'rejetées': n, ...} (ordre conservé)."""
    total = sum(sorties.values())
    ecart = entree - total
    detail = f"{fmt(entree)} = " + " + ".join(f"{fmt(n)} {nom}" for nom, n in sorties.items())
    if ecart:
        detail = detail.replace(" = ", " ≠ ", 1) + f" (écart {'+' if ecart > 0 else ''}{fmt(ecart)})"
    return ecart == 0, detail


def famille_redis(cle: str) -> str | None:
    """Famille d'une clé Redis (PDF Source 5) ; None = clé que la couche clean ne sait pas router."""
    if cle.startswith("session:"):
        return "session"
    if cle.startswith("leaderboard:"):
        return "leaderboard"
    if cle in COMPTEURS_REDIS:
        return "compteur"
    prefixe = cle.split(":", 1)[0]
    return prefixe if prefixe in FAMILLES_ETUDIANT and ":" in cle else None


def compter_familles(cles: Iterable[str]) -> tuple[dict[str, int], list[str]]:
    """({famille: nombre de clés}, clés non routées)."""
    comptes, inconnues = {}, []
    for cle in cles:
        f = famille_redis(cle)
        if f is None:
            inconnues.append(cle)
        else:
            comptes[f] = comptes.get(f, 0) + 1
    return comptes, inconnues


def comparer_kpi(valeurs: dict[str, Decimal], reference: dict[str, Decimal] = REFERENCE_KPI,
                 tolerances: dict[str, Decimal] = TOLERANCE_KPI) -> list[tuple[str, bool, str]]:
    """Q6 : (code, ok, détail) pour chaque KPI de la référence."""
    res = []
    for code, attendu in reference.items():
        obtenu = valeurs.get(code)
        if obtenu is None:
            res.append((code, False, f"absent de dw.v_kpi (attendu {attendu})"))
            continue
        ecart = abs(Decimal(obtenu) - attendu)
        tol = tolerances[code]
        ok = ecart <= tol
        regle = "égalité exacte" if tol == 0 else f"tolérance {tol:.0e}"
        res.append((code, ok, f"obtenu {obtenu}, référence {attendu} ({regle}{'' if ok else f', écart {ecart}'})"))
    return res


def resume_par_question(checks: list[Check]) -> list[tuple[str, str, int, int]]:
    """[(code, question, réussis, total)] dans l'ordre des questions."""
    return [(q, libelle, sum(c.ok for c in checks if c.code == q), sum(1 for c in checks if c.code == q))
            for q, libelle in QUESTIONS.items()]


def rendre_rapport(checks: list[Check], batch_id: str, maintenant: datetime | None = None) -> str:
    """Rapport Markdown de la porte (même tableau de détail que G4, précédé d'un résumé par question)."""
    ok = all(c.ok for c in checks)
    lignes = [f"# Porte G6 — Tests du pipeline de bout en bout, lot {batch_id}", "",
              f"*Rapport du {(maintenant or datetime.now()):%d/%m/%Y %H:%M}*", "",
              f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** ({sum(c.ok for c in checks)}/{len(checks)} contrôles)", "",
              "## Les questions de la Phase 15", "",
              "| Code | Question | Contrôles réussis |", "|---|---|:-:|",
              *[f"| {q} | {libelle} | {n_ok}/{n} {'✅' if n_ok == n and n else '❌'} |"
                for q, libelle, n_ok, n in resume_par_question(checks)], "",
              "## Détail", "",
              "| Contrôle | Libellé | Détail | OK |", "|---|---|---|:-:|",
              *[f"| {c.code} | {c.libelle} | {c.detail} | {'✅' if c.ok else '❌'} |" for c in checks], ""]
    return "\n".join(lignes)


# =============================================================================
# Accès à la base
# =============================================================================
def _v(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def _staging(obj) -> str:
    return f"{STAGING_SCHEMA}.{obj.stg_table}"


def _tables_conservation():
    """16 tables « une ligne staging = une ligne clean ou rejetée », reprises du rapport qualité (L5)."""
    from pipeline.rapport_qualite import TABLES
    return [(src, table, stg, clean_t) for src, table, stg, filtre, clean_t in TABLES
            if src != "s5_redis" and filtre is None and clean_t]


def charger_journal(cur, batch_id: str) -> tuple[dict, int]:
    cur.execute("""SELECT id_execution, etape, code_source, objet, statut, nb_lignes, nb_erreurs
                   FROM meta.etl_execution_log WHERE batch_id = %s""", (batch_id,))
    return derniers_par_cle(cur.fetchall())


# =============================================================================
# Les 6 sections : chacune prend un curseur et le contexte, et rend ses contrôles
# =============================================================================
def controles_extraction(cur, ctx: Contexte) -> list[Check]:
    checks = []
    objets = (ctx.manifeste or {}).get("objets", {})
    for o in OBJECTS:
        cle = f"{o.source}.{o.objet}"
        n_manifeste = objets.get(cle, {}).get("nb_lignes")
        volatile = o.source == "s5_redis"
        n_source = None
        if ctx.recompter is not None and not volatile and n_manifeste is not None:
            try:
                n_source = ctx.recompter(o.source, o.objet)
            except Exception as exc:                     # source injoignable : contrôle en échec, G6 continue
                checks.append(Check("G6.1", f"Extraction de {cle}", False, f"source injoignable : {exc}"))
                continue
        ok, detail = evaluer_extraction(n_source, n_manifeste, ctx.journal.get(("EXTRACT", o.source, o.objet)), volatile)
        checks.append(Check("G6.1", f"Extraction de {cle}", ok, detail))
    return checks


def controles_chargement(cur, ctx: Contexte) -> list[Check]:
    checks = []
    objets = (ctx.manifeste or {}).get("objets", {})
    for o in OBJECTS:
        cle = f"{o.source}.{o.objet}"
        n_lot = _v(cur, f"SELECT COUNT(*) FROM {_staging(o)} WHERE _batch_id = %s", (ctx.batch_id,))
        n_total = _v(cur, f"SELECT COUNT(*) FROM {_staging(o)}")
        ok, detail = evaluer_chargement(n_lot, n_total, objets.get(cle, {}).get("nb_lignes"),
                                        ctx.journal.get(("LOAD", o.source, o.objet)))
        checks.append(Check("G6.2", f"Chargement de {cle} -> {_staging(o)}", ok, detail))
    return checks


def controles_pertes(cur, ctx: Contexte) -> list[Check]:
    from pipeline.verify_g4 import SOURCE_CLEAN
    checks, b = [], ctx.batch_id

    # 1. staging -> clean + rejets : 16 tables où une ligne de staging donne une ligne clean OU une ligne rejetée
    doubles, synthese_ko, synthese_absente = 0, [], 0
    for src, table, stg, clean_t in _tables_conservation():
        n_stg = _v(cur, f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{stg} WHERE _batch_id = %s", (b,))
        n_clean = _v(cur, f"SELECT COUNT(*) FROM clean.{clean_t}")
        cur.execute("""SELECT COUNT(DISTINCT rang), COUNT(*) FROM quality.rejets
                       WHERE batch_id = %s AND code_source = %s AND table_source = %s""", (b, src, table))
        n_rej, n_rej_total = cur.fetchone()
        doubles += n_rej_total - n_rej
        ok, detail = equation_conservation(n_stg, {"clean": n_clean, "rejetées": n_rej})
        checks.append(Check("G6.3", f"staging -> clean + rejets : {src}.{table}", ok, detail))
        cur.execute("""SELECT lignes_extraites, lignes_rejetees, lignes_clean FROM quality.synthese
                       WHERE batch_id = %s AND code_source = %s AND table_source = %s""", (b, src, table))
        ligne = cur.fetchone()
        if ligne is None:
            synthese_absente += 1
        elif tuple(ligne) != (n_stg, n_rej_total, n_clean):
            synthese_ko.append(f"{table} {tuple(ligne)} ≠ {(n_stg, n_rej_total, n_clean)}")
    checks.append(Check("G6.3", "Aucune ligne rejetée deux fois (16 tables)", doubles == 0,
                        "chaque ligne rejetée l'est par une seule règle" if doubles == 0
                        else f"{fmt(doubles)} rejet(s) en double : quality.synthese surestime les rejets"))
    ok = synthese_absente == 0 and not synthese_ko
    checks.append(Check("G6.3", "quality.synthese = comptages réels (extraites, rejetées, clean)", ok,
                        "16 tables conformes" if ok else
                        (f"{synthese_absente} table(s) absente(s) du rapport qualité du lot ; " if synthese_absente else "")
                        + "; ".join(synthese_ko[:3])))

    # 2. Redis : une ligne de staging = une clé ; l'unité de la couche clean dépend de la famille
    checks += controles_pertes_redis(cur, b)

    # 3. clean -> DW : chaque fait contient exactement les lignes de sa table clean (même liste que G4.3)
    for fait, sql_clean in SOURCE_CLEAN.items():
        n_clean, n_dw = _v(cur, sql_clean), _v(cur, f"SELECT COUNT(*) FROM dw.{fait}")
        ok, detail = equation_conservation(n_clean, {f"dans dw.{fait}": n_dw})
        checks.append(Check("G6.3", f"clean -> DW : {fait}", ok, detail))
    return checks


def controles_pertes_redis(cur, b: str) -> list[Check]:
    checks = []
    cur.execute("SELECT cle FROM staging.stg_redis_keys WHERE _batch_id = %s", (b,))
    familles, inconnues = compter_familles(r[0] for r in cur.fetchall())
    checks.append(Check("G6.3", "Redis : chaque clé appartient à une famille traitée", not inconnues,
                        f"{fmt(sum(familles.values()))} clés : " + ", ".join(f"{f} {fmt(n)}" for f, n in sorted(familles.items()))
                        + (f" ; non routées : {', '.join(inconnues[:5])}" if inconnues else "")))

    n = _v(cur, "SELECT COUNT(*) FROM clean.redis_sessions")
    ok, detail = equation_conservation(familles.get("session", 0), {"sessions clean": n})
    checks.append(Check("G6.3", "Redis : clés session -> clean.redis_sessions", ok, detail))

    def rejetees(famille: str) -> int:
        return _v(cur, """SELECT COUNT(DISTINCT rang) FROM quality.rejets WHERE batch_id = %s AND code_source = 's5_redis'
                          AND table_source = 'cles_etudiant' AND ligne ->> 'famille' = %s""", (b, famille))

    for famille, table in CLEAN_FAMILLE.items():
        ok, detail = equation_conservation(familles.get(famille, 0), {"clean": _v(cur, f"SELECT COUNT(*) FROM clean.{table}"),
                                                                       "rejetées (E06)": rejetees(famille)})
        checks.append(Check("G6.3", f"Redis : clés {famille} -> clean.{table} + rejets", ok, detail))

    # notifications, au niveau de la CLÉ (une liste Redis n'est jamais vide : elle disparaît avec son dernier élément)
    n_cles_clean = _v(cur, "SELECT COUNT(DISTINCT student_code) FROM clean.redis_notifications")
    ok, detail = equation_conservation(familles.get("notifications", 0),
                                       {"clean": n_cles_clean, "rejetées (E06)": rejetees("notifications")})
    checks.append(Check("G6.3", "Redis : clés notifications -> clean + rejets", ok, detail))

    # notifications, au niveau du MESSAGE : messages = messages des clés rejetées + messages clean + doublons rejetés
    total = _v(cur, """SELECT COALESCE(SUM(jsonb_array_length(valeur)), 0) FROM staging.stg_redis_keys
                       WHERE _batch_id = %s AND cle LIKE 'notifications:%%' AND jsonb_typeof(valeur) = 'array'""", (b,))
    msg_cles_rejetees = _v(cur, """SELECT COALESCE(SUM(jsonb_array_length(ligne -> 'valeur')), 0) FROM quality.rejets
                                   WHERE batch_id = %s AND code_source = 's5_redis' AND table_source = 'cles_etudiant'
                                     AND ligne ->> 'famille' = 'notifications'
                                     AND jsonb_typeof(ligne -> 'valeur') = 'array'""", (b,))
    doublons = _v(cur, """SELECT COUNT(*) FROM quality.rejets WHERE batch_id = %s AND code_source = 's5_redis'
                          AND table_source = 'notifications'""", (b,))
    ok, detail = equation_conservation(total, {"clean": _v(cur, "SELECT COUNT(*) FROM clean.redis_notifications"),
                                               "en double (E04)": doublons, "d'étudiants inconnus": msg_cles_rejetees})
    checks.append(Check("G6.3", "Redis : messages de notification", ok, detail))

    # compteurs : online_users -> 1 ligne, statistics:today -> 4 lignes
    cur.execute("SELECT cle FROM staging.stg_redis_keys WHERE _batch_id = %s AND cle = ANY(%s)", (b, list(COMPTEURS_REDIS)))
    attendu = sum(COMPTEURS_REDIS[c] for (c,) in cur.fetchall())
    ok, detail = equation_conservation(attendu, {"lignes de clean.redis_compteurs": _v(cur, "SELECT COUNT(*) FROM clean.redis_compteurs")})
    checks.append(Check("G6.3", "Redis : compteurs -> clean.redis_compteurs", ok, detail.replace(f"{fmt(attendu)} =", f"{fmt(attendu)} attendues =", 1)))

    # classement : un membre inconnu de MySQL est écarté par un filtre, SANS trace dans quality.rejets (constat L9-A1)
    membres = _v(cur, """SELECT COALESCE(SUM(jsonb_array_length(valeur)), 0) FROM staging.stg_redis_keys
                         WHERE _batch_id = %s AND cle LIKE 'leaderboard:%%' AND jsonb_typeof(valeur) = 'array'""", (b,))
    gardes = _v(cur, "SELECT COUNT(*) FROM clean.redis_leaderboard")
    ecartes = membres - gardes
    checks.append(Check("G6.3", "Redis : membres du classement (information)", True,
                        f"{fmt(membres)} membres, {fmt(gardes)} en clean" +
                        (f", {fmt(ecartes)} écartés SANS trace dans quality.rejets (constat L9-A1)" if ecartes
                         else ", aucun écarté")))
    return checks


def controles_erreurs(cur, ctx: Contexte) -> list[Check]:
    checks = []
    for etape, attendus in attendus_journal().items():
        ok, detail = evaluer_couverture(attendus, ctx.journal)
        checks.append(Check("G6.4", f"Journal : étape {etape}", ok, detail))
    en_cours = sorted(f"{e} {s}.{o}" for (e, s, o), (statut, _, _) in ctx.journal.items() if statut == "EN_COURS")
    checks.append(Check("G6.4", "Aucune étape restée EN_COURS (arrêt brutal)", not en_cours,
                        "aucune" if not en_cours else ", ".join(en_cours[:5])))
    erreurs = sum(nb_err for (statut, _, nb_err) in ctx.journal.values())
    checks.append(Check("G6.4", "Aucune erreur sur la dernière exécution de chaque étape", erreurs == 0,
                        f"{erreurs} erreur(s) ; {len(ctx.journal)} étapes journalisées"))
    checks.append(Check("G6.4", "Échecs relancés avec succès (information)", True,
                        f"{ctx.echecs_anterieurs} échec(s) antérieur(s) dans ce lot, tous rattrapés"
                        if ctx.echecs_anterieurs else "aucun échec dans ce lot"))
    objets = (ctx.manifeste or {}).get("objets", {})
    cur.execute("SELECT code_source, objet, dernier_batch_id, derniere_nb_lignes, dernier_statut FROM meta.metadata_sources")
    etat = {(s, o): (bid, n, st) for s, o, bid, n, st in cur.fetchall()}
    ecarts = [f"{o.source}.{o.objet} {etat.get((o.source, o.objet))}" for o in OBJECTS
              if etat.get((o.source, o.objet)) != (ctx.batch_id, objets.get(f"{o.source}.{o.objet}", {}).get("nb_lignes"), "SUCCES")]
    checks.append(Check("G6.4", "metadata_sources à jour pour les 17 objets", not ecarts,
                        f"17/17 sur le lot {ctx.batch_id}" if not ecarts else "; ".join(ecarts[:3])))
    return checks


def controles_cles(cur, ctx: Contexte) -> list[Check]:
    from pipeline.transform import TABLES_CLEAN
    from pipeline.verify_g4 import FK
    checks = []
    for fait, fks in FK.items():
        orphelines = {}
        for col, dim, cle in fks:
            n = _v(cur, f"SELECT COUNT(*) FROM dw.{fait} f WHERE NOT EXISTS (SELECT 1 FROM dw.{dim} d WHERE d.{cle} = f.{col})")
            if n:
                orphelines[col] = n
        checks.append(Check("G6.5", f"Clés étrangères de {fait} ({len(fks)})", not orphelines,
                            "toutes valides" if not orphelines else
                            ", ".join(f"{c} : {fmt(n)} orpheline(s)" for c, n in orphelines.items())))
    absents = [dim for dim, cle in CLES_DIMENSIONS.items()
               if not _v(cur, f"SELECT COUNT(*) FROM dw.{dim} WHERE {cle} = -1")]
    checks.append(Check("G6.5", "Membre « Inconnu » (-1) présent dans les 7 dimensions", not absents,
                        "7/7" if not absents else f"absent de : {', '.join(absents)}"))
    plusieurs = _v(cur, """SELECT COUNT(*) FROM (SELECT etudiant_id FROM dw.dim_etudiant WHERE est_courant
                           GROUP BY 1 HAVING COUNT(*) > 1) x""")
    checks.append(Check("G6.5", "Clé durable : une seule version courante par étudiant (SCD 2)", plusieurs == 0,
                        f"{plusieurs} étudiant(s) en défaut"))
    cur.execute("""SELECT table_name FROM information_schema.table_constraints
                   WHERE table_schema = 'clean' AND constraint_type = 'PRIMARY KEY'""")
    avec_pk = {r[0] for r in cur.fetchall()}
    attendues = [t for tables in TABLES_CLEAN.values() for t in tables]
    sans_pk = [t for t in attendues if t not in avec_pk]
    checks.append(Check("G6.5", f"Clés primaires de la couche clean ({len(attendues)} tables)", not sans_pk,
                        "unicité garantie par le moteur" if not sans_pk else f"sans clé primaire : {', '.join(sans_pk)}"))
    for libelle, enfant, col, parent, col_p, regle in INTEGRITE_CLEAN:
        n = _v(cur, f"""SELECT COUNT(*) FROM clean.{enfant} e
                        WHERE NOT EXISTS (SELECT 1 FROM clean.{parent} p WHERE p.{col_p} = e.{col})""")
        checks.append(Check("G6.5", f"Intégrité clean : {libelle}", n == 0,
                            f"{fmt(n)} orpheline(s) (garantie par la règle {regle})"))
    return checks


def controles_kpi(cur, ctx: Contexte) -> list[Check]:
    try:
        _savepoint(cur, "SAVEPOINT g6_kpi")
        cur.execute("SELECT code, valeur FROM dw.v_kpi")
        valeurs = {c: Decimal(v) for c, v in cur.fetchall()}
        _savepoint(cur, "RELEASE SAVEPOINT g6_kpi")
    except Exception as exc:                                  # vue absente : DW reconstruit sans l'étape kpi
        _savepoint(cur, "ROLLBACK TO SAVEPOINT g6_kpi")
        return [Check("G6.6", f"KPI {code}", False, f"dw.v_kpi illisible ({type(exc).__name__}) : "
                      "lancer python -m pipeline.run_pipeline --steps kpi") for code in REFERENCE_KPI]
    return [Check("G6.6", f"KPI {code}", ok, detail) for code, ok, detail in comparer_kpi(valeurs)]


def _savepoint(cur, sql: str) -> None:
    """Points de sauvegarde : seulement dans une transaction (inutiles, et refusés, en autocommit)."""
    if not cur.connection.autocommit:
        cur.execute(sql)


SECTIONS = (controles_extraction, controles_chargement, controles_pertes, controles_erreurs, controles_cles, controles_kpi)


# =============================================================================
# Porte G6
# =============================================================================
def contexte(conn, batch_id: str | None = None, recompter: Callable | None = None,
             manifeste: dict | None | bool = True) -> Contexte:
    """
    batch_id : lot à contrôler (par défaut celui présent en staging, comme G3 et G4) ;
    manifeste : True = lu dans data/landing/<lot>/manifest.json ; un dict = fourni (tests).
    """
    from pipeline.transform import batch_en_staging
    batch_id = batch_id or batch_en_staging(conn)
    if manifeste is True:
        from pipeline.landing import Batch, read_manifest
        try:
            manifeste = read_manifest(Batch(batch_id))
        except FileNotFoundError:
            logger.error("Manifeste du lot %s introuvable dans data/landing/ : G6.1 et G6.2 en échec", batch_id)
            manifeste = None
    with conn.cursor() as cur:
        journal, rattrapes = charger_journal(cur, batch_id)
    return Contexte(batch_id, manifeste or None, recompter, journal, rattrapes)


def verify(conn, ctx: Contexte | None = None, sections=SECTIONS) -> list[Check]:
    """Exécute les sections demandées (toutes par défaut). Lecture seule : aucune écriture, aucun COMMIT."""
    ctx = ctx or contexte(conn)
    checks: list[Check] = []
    with conn.cursor() as cur:
        for section in sections:
            checks += section(cur, ctx)
    return checks


def write_report(checks: list[Check], batch_id: str) -> str:
    path = get_settings().paths.reports_dir / f"G6_{batch_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendre_rapport(checks, batch_id), encoding="utf-8")
    return str(path)


def main(argv: list[str] | None = None) -> int:
    import psycopg2
    from pipeline.verify_g2 import compter_source
    parser = argparse.ArgumentParser(description="Porte G6 : tests du pipeline de bout en bout (Phase 15)")
    parser.add_argument("--sans-recomptage", action="store_true",
                        help="ne pas interroger les 4 sources persistantes (G6.1 compare alors manifeste et journal)")
    args = parser.parse_args(argv)
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        conn.autocommit = True                           # lecture seule : aucune transaction à maintenir
        ctx = contexte(conn, recompter=None if args.sans_recomptage else compter_source)
        checks = verify(conn, ctx)
    except Exception:
        logger.exception("Porte G6 interrompue")
        return 2
    finally:
        conn.close()
    for c in checks:
        (logger.info if c.ok else logger.error)("[%s] %s %-56s %s", "OK" if c.ok else "KO", c.code, c.libelle, c.detail)
    for q, libelle, n_ok, n in resume_par_question(checks):
        logger.info("%s %-60s %d/%d", q, libelle, n_ok, n)
    logger.info("Porte G6 : %d/%d - %s", sum(c.ok for c in checks), len(checks), write_report(checks, ctx.batch_id))
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
