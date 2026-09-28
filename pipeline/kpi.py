"""
pipeline/kpi.py — KPI d'EduSmart et porte G5 (Phase 11, Lot L7)
==============================================================

    1. crée les vues SQL dw.v_kpi et dw.v_kpi_annee (pipeline/sql/olap/10_kpi.sql) ;
    2. RECALCULE chaque KPI indépendamment : en Python, depuis la COUCHE CLEAN et non depuis le DW ;
    3. porte G5a : valeur SQL (DW) = valeur Python (clean), pour les 8 KPI ;
    4. écrit les valeurs de référence (data/reports/kpi_reference.json), que les mesures DAX de
       Power BI devront retrouver en L8 (porte G5b), et le rapport data/reports/kpi_<lot>.md.

Deux langages (SQL et Python), deux couches (dw et clean), deux chemins de calcul : un écart
révélerait une erreur de modélisation (grain, jointure, SCD 2) ou de définition.

    python -m pipeline.kpi
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median

from common.config import get_settings
from common.logger import get_logger

logger = get_logger("kpi")
SQL_KPI = Path(__file__).resolve().parent / "sql" / "olap" / "10_kpi.sql"
DATE_REFERENCE = date(2026, 9, 15)          # C20
FENETRE_ACTIFS = 30
TOLERANCE_RATIO = Decimal("1e-9")


@dataclass(frozen=True)
class Kpi:
    """Fiche d'un KPI (Phase 11 : définition, formule, source, fréquence, cible, justification, limites)."""
    code: str
    libelle: str
    definition: str
    formule: str
    unite: str
    sources: str
    frequence: str
    cible: str
    decideur: str
    justification: str
    limites: str


KPIS: tuple[Kpi, ...] = (
    Kpi("CA", "Chiffre d'affaires encaissé",
        "Somme des paiements au statut VALIDE, rattachés à une inscription existante, montants négatifs exclus.",
        "SUM(montant_ca)", "XOF", "PostgreSQL (paiements, inscriptions)", "Mensuelle (par tranche)",
        "Proposition : ≥ CA de l'année précédente à date", "DG, Direction financière",
        "Premier indicateur demandé par le DG (Phase 1) ; mesure la santé financière.",
        "1 700 paiements négatifs (A14) exclus : s'il s'agit d'erreurs de signe, le CA réel est plus élevé. "
        "Paiements EN_ATTENTE, ECHOUE et REMBOURSE exclus."),
    Kpi("RECOUVREMENT", "Taux de recouvrement",
        "CA encaissé rapporté au montant dû (frais annuels de la classe après réduction).",
        "SUM(montant_ca) / SUM(montant_du)", "%", "PostgreSQL (paiements, inscriptions, classes, filières)", "Mensuelle",
        "Proposition : ≥ 90 % en fin d'année académique", "Direction financière",
        "Le CA seul ne dit pas si les étudiants paient ce qu'ils doivent ; le recouvrement mesure les impayés.",
        "Frais annuels = coût total / nombre d'années (convention L6). 541 réductions neutralisées (A11) comptées "
        "sans réduction. L'année en cours n'est pas close : son taux progresse jusqu'en septembre."),
    Kpi("REUSSITE", "Taux de réussite aux quiz",
        "Part des couples (étudiant, quiz) validés au moins une fois parmi les couples tentés.",
        "COUNT(couples validés) / COUNT(couples tentés)", "%", "MySQL (notes)", "Hebdomadaire",
        "Proposition : ≥ 85 %", "Direction pédagogique",
        "Demandé par le DG. Compter par couple, et non par tentative, évite de pénaliser les étudiants qui retentent.",
        "Mesure la réussite aux quiz en ligne, PAS la réussite au diplôme (aucune source ne la contient : gap L3). "
        "14 473 scores neutralisés (B14) : la validation reste connue."),
    Kpi("ABANDON", "Taux d'abandon",
        "Part des inscriptions au statut ABANDON.",
        "SUM(est_abandon) / COUNT(inscriptions)", "%", "PostgreSQL (inscriptions)", "Trimestrielle",
        "Proposition : ≤ 5 %", "DG, Direction pédagogique",
        "Exemple du PDF ; un abandon est un CA futur perdu et un signal pédagogique.",
        "La source ne date pas l'abandon : on ne sait pas QUAND il a eu lieu. Les inscriptions SUSPENDU (360) "
        "ne sont pas comptées comme abandons."),
    Kpi("PROGRESSION", "Progression moyenne",
        "Moyenne des pourcentages de progression par couple (étudiant, module), dernière valeur connue.",
        "AVG(pourcentage)", "%", "MySQL (progression)", "Hebdomadaire",
        "Proposition : ≥ 70 %", "Direction pédagogique",
        "Exemple du PDF ; mesure l'avancement réel dans les contenus en ligne.",
        "Mesure semi-additive : on la moyenne, on ne la somme jamais. 3 180 valeurs hors [0, 100] neutralisées "
        "(B05, B06) et ignorées. Instantané : pas d'historique de la progression."),
    Kpi("ACTIFS_30J", "Étudiants actifs (30 jours)",
        "Nombre de personnes distinctes ayant au moins une connexion, une note ou une activité de quiz "
        "au cours des 30 jours précédant la date de référence.",
        "COUNT(DISTINCT étudiant) sur la fenêtre", "étudiants", "MySQL (connexions, notes), MongoDB (quiz)",
        "Quotidienne", "Proposition : ≥ 30 % des étudiants", "DG",
        "Exemple du PDF ; mesure l'engagement réel, que le nombre d'inscrits ne dit pas.",
        "Les événements MongoDB hors quiz (vidéos, téléchargements) ne sont pas dans le DW : ils ne comptent pas. "
        "Fenêtre fixe au 15/09/2026 (date de référence de la simulation)."),
    Kpi("CONNEXION_MEDIANE", "Temps médian de connexion",
        "Médiane des durées de connexion à la plateforme, en secondes.",
        "MEDIAN(duree_secondes)", "secondes", "MySQL (temps_connexion)", "Hebdomadaire",
        "Proposition : ≥ 20 minutes", "Direction pédagogique",
        "Demandé par le DG. La médiane (définition L3) résiste aux sessions anormalement longues, contrairement à la moyenne.",
        "1 658 connexions sans déconnexion (B08) exclues, faute de durée. Ne mesure pas l'attention réelle."),
    Kpi("ETUDIANTS", "Nombre réel d'étudiants",
        "Personnes distinctes : étudiants inscrits (PostgreSQL) et comptes LMS sans inscription (MySQL).",
        "COUNT(DISTINCT étudiant) courant", "étudiants", "PostgreSQL, MySQL (via le rapprochement)", "Mensuelle",
        "Suivi (pas de cible)", "DG",
        "Première question du DG (Phase 1) : la somme naïve des sources donnait 26 476, le nombre réel est 10 500.",
        "500 comptes LMS sans inscription et 1 000 inscrits sans compte LMS : ils ne peuvent pas être rapprochés "
        "et comptent chacun pour une personne."),
)
KPI_NON_CALCULABLE = {
    "code": "SATISFACTION", "libelle": "Satisfaction des étudiants",
    "raison": "Aucune des 5 sources ne contient d'avis, de note de satisfaction ni d'enquête (gap documenté en L3).",
    "recommandation": "Collecter un score de satisfaction (échelle de 1 à 5) à la fin de chaque module, dans la "
                      "plateforme pédagogique ; il deviendrait une mesure d'un nouveau fait « fact_evaluations ».",
    "a_eviter": "Aucun indicateur de substitution (taux de réussite, temps de connexion) : présenter un taux "
                "d'engagement comme une « satisfaction » tromperait le décideur.",
}


# -----------------------------------------------------------------------------
# Recalcul INDÉPENDANT depuis la couche clean (fonctions pures, testables)
# -----------------------------------------------------------------------------
def _arrondi(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calc_ca(paiements) -> Decimal:
    """paiements : (statut, montant, inscription_existe)."""
    return sum((m for s, m, ok in paiements if ok and s == "VALIDE" and m is not None and m >= 0), Decimal(0))


def calc_montant_du(inscriptions) -> Decimal:
    """inscriptions : (cout_total, niveau, reduction ou None)."""
    annees = {"LICENCE": 3, "MASTER": 2}
    total = Decimal(0)
    for cout, niveau, reduction in inscriptions:
        frais = _arrondi(Decimal(cout) / annees.get(niveau, 1))
        total += _arrondi(frais * (1 - (reduction or Decimal(0)) / 100))
    return total


def calc_reussite(notes) -> Decimal:
    """notes : (etudiant_id, id_quiz, valide)."""
    couples: dict = {}
    for etu, quiz, valide in notes:
        couples[(etu, quiz)] = couples.get((etu, quiz), False) or bool(valide)
    return Decimal(sum(couples.values())) / Decimal(len(couples))


def calc_abandon(statuts) -> Decimal:
    statuts = list(statuts)
    return Decimal(sum(1 for s in statuts if s == "ABANDON")) / Decimal(len(statuts))


def calc_progression(pourcentages) -> Decimal:
    valeurs = [p for p in pourcentages if p is not None]
    return sum(valeurs, Decimal(0)) / Decimal(len(valeurs))


def calc_actifs(activites, reference: date = DATE_REFERENCE, fenetre: int = FENETRE_ACTIFS) -> int:
    """activites : (etudiant_id, date) ; fenêtre de `fenetre` jours inclus, terminée à `reference`."""
    debut = reference - timedelta(days=fenetre - 1)
    return len({e for e, d in activites if e is not None and debut <= d <= reference})


def calc_mediane(durees) -> Decimal:
    return Decimal(str(median([d for d in durees if d is not None])))


def recalculer(conn) -> dict[str, Decimal]:
    """Les 8 KPI recalculés en Python depuis la couche CLEAN (sans lire le DW)."""
    def lignes(sql):
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    ident = "COALESCE(c.id_etudiant::TEXT, 'LMS:' || c.student_code)"      # clé durable (même règle que le DW)
    res = {
        "CA": calc_ca(lignes("""SELECT p.statut, p.montant, i.id_inscription IS NOT NULL
                                FROM clean.paiements p LEFT JOIN clean.inscriptions i USING (id_inscription)""")),
        "REUSSITE": calc_reussite(lignes(f"""SELECT {ident}, n.id_quiz, n.valide FROM clean.notes n
                                             JOIN clean.comptes_lms c USING (student_code)""")),
        "ABANDON": calc_abandon(s for (s,) in lignes("SELECT statut FROM clean.inscriptions")),
        "PROGRESSION": calc_progression(p for (p,) in lignes("SELECT pourcentage FROM clean.progression")),
        "ACTIFS_30J": Decimal(calc_actifs(lignes(f"""
            SELECT {ident}, x.jour FROM (
                SELECT student_code, date_connexion::DATE AS jour FROM clean.temps_connexion
                UNION ALL SELECT student_code, date_passage::DATE FROM clean.notes
                UNION ALL SELECT student_code, horodatage::DATE FROM clean.evenements
                          WHERE event_type IN ('QUIZ_STARTED', 'QUIZ_SUBMITTED')) x
            JOIN clean.comptes_lms c USING (student_code)"""))),
        "CONNEXION_MEDIANE": calc_mediane(d for (d,) in lignes("SELECT duree_secondes FROM clean.temps_connexion")),
        "ETUDIANTS": Decimal(lignes("""SELECT (SELECT COUNT(*) FROM clean.etudiants)
                                            + (SELECT COUNT(*) FROM clean.comptes_lms WHERE NOT a_inscription)""")[0][0]),
    }
    du = calc_montant_du(lignes("""SELECT f.cout_total, f.niveau, i.reduction FROM clean.inscriptions i
                                   JOIN clean.classes c USING (id_classe) JOIN clean.filieres f USING (id_filiere)"""))
    res["RECOUVREMENT"] = res["CA"] / du
    return res


# -----------------------------------------------------------------------------
# Porte G5a
# -----------------------------------------------------------------------------
def valeurs_sql(conn) -> dict[str, Decimal]:
    with conn.cursor() as cur:
        cur.execute(SQL_KPI.read_text(encoding="utf-8"))
        cur.execute("SELECT code, valeur FROM dw.v_kpi ORDER BY ordre")
        res = {c: Decimal(v) for c, v in cur.fetchall()}
    conn.commit()
    return res


def comparer(sql: dict[str, Decimal], py: dict[str, Decimal]) -> list[tuple[str, bool, Decimal, Decimal]]:
    """Égalité exacte pour les montants et les effectifs ; à 1e-9 près pour les ratios et les moyennes."""
    res = []
    for k in KPIS:
        a, b = sql.get(k.code), py.get(k.code)
        ok = a is not None and b is not None and (abs(a - b) <= TOLERANCE_RATIO if k.unite in ("%", "ratio") else a == b)
        res.append((k.code, ok, a, b))
    return res


def formater(k: Kpi, v: Decimal) -> str:
    if k.code in ("RECOUVREMENT", "REUSSITE", "ABANDON"):
        return f"{100 * v:.2f} %"
    if k.code == "PROGRESSION":
        return f"{v:.2f} %"
    if k.code == "CA":
        return f"{v / Decimal(1e9):.3f} Mds XOF"
    if k.code == "CONNEXION_MEDIANE":
        return f"{int(v)} s ({v / 60:.1f} min)"
    return f"{int(v):,}".replace(",", " ")


def ecrire(batch_id: str, comparaison, annees) -> tuple[str, str]:
    reports = get_settings().paths.reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    par_code = {k.code: k for k in KPIS}
    reference = {"batch_id": batch_id, "date_reference": DATE_REFERENCE.isoformat(), "genere_le": datetime.now().isoformat(timespec="seconds"),
                 "kpi": {c: {"libelle": par_code[c].libelle, "valeur": str(a), "affichage": formater(par_code[c], a)}
                         for c, _, a, _ in comparaison},
                 "par_annee": [{k: str(v) for k, v in zip(("annee_academique", "ca", "montant_du", "taux_recouvrement",
                                                           "inscriptions", "abandons", "taux_abandon"), r)} for r in annees]}
    chemin_json = reports / "kpi_reference.json"
    chemin_json.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = all(c[1] for c in comparaison)
    md = [f"# KPI d'EduSmart — lot {batch_id}", "", f"*Date de référence : {DATE_REFERENCE:%d/%m/%Y} · généré le {datetime.now():%d/%m/%Y %H:%M}*", "",
          f"**Porte G5a : {'VALIDÉE' if ok else 'NON VALIDÉE'}** — {sum(c[1] for c in comparaison)}/{len(comparaison)} KPI "
          "identiques entre le SQL (DW) et le recalcul Python (couche clean).", "",
          "| KPI | Valeur | SQL sur le DW | Python sur la couche clean | Identiques |", "|---|---|---:|---:|:-:|",
          *[f"| {par_code[c].libelle} | **{formater(par_code[c], a)}** | {a} | {b} | {'✅' if ok_ else '❌'} |"
            for c, ok_, a, b in comparaison], "",
          "## Par année académique de la formation", "",
          "| Année | CA (XOF) | Montant dû (XOF) | Recouvrement | Inscriptions | Abandons | Taux d'abandon |",
          "|---|---:|---:|---:|---:|---:|---:|",
          *[f"| {r[0]} | {r[1]:,.0f} | {r[2]:,.0f} | {100 * r[3]:.2f} % | {r[4]} | {r[5]} | {100 * r[6]:.2f} % |".replace(",", " ")
            for r in annees], "",
          f"**Satisfaction : non calculable.** {KPI_NON_CALCULABLE['raison']}", "",
          "Valeurs de référence pour Power BI (porte G5b, L8) : `data/reports/kpi_reference.json`.", ""]
    chemin_md = reports / f"kpi_{batch_id}.md"
    chemin_md.write_text("\n".join(md), encoding="utf-8")
    return str(chemin_md), str(chemin_json)


class CoucheCleanVide(RuntimeError):
    """La couche clean est vide : le recalcul indépendant est impossible."""


def dernier_lot_dw(conn) -> str:
    """Dernier lot chargé avec succès dans le DW (journal Phase 6) : le DW, lui, est journalisé."""
    with conn.cursor() as cur:
        cur.execute("""SELECT batch_id FROM meta.etl_execution_log WHERE etape = 'DW' AND statut = 'SUCCES'
                       ORDER BY date_fin DESC LIMIT 1""")
        r = cur.fetchone()
    if r is None:
        raise RuntimeError("Aucun chargement du DW réussi : lancez python -m pipeline.run_pipeline")
    return r[0]


def verifier_clean(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT (SELECT COUNT(*) FROM clean.paiements), (SELECT COUNT(*) FROM clean.notes)")
        paiements, notes = cur.fetchone()
    if not paiements or not notes:
        raise CoucheCleanVide("Couche clean vide (après un arrêt brutal de PostgreSQL, les tables UNLOGGED sont "
                              "vidées) : relancez python -m pipeline.run_pipeline, puis python -m pipeline.kpi")


def executer(conn, batch_id: str):
    verifier_clean(conn)
    sql = valeurs_sql(conn)
    py = recalculer(conn)
    comparaison = comparer(sql, py)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM dw.v_kpi_annee")
        annees = cur.fetchall()
    return comparaison, ecrire(batch_id, comparaison, annees)


def main() -> int:
    import psycopg2
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        comparaison, (md, js) = executer(conn, dernier_lot_dw(conn))
    except (CoucheCleanVide, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1
    finally:
        conn.close()
    par_code = {k.code: k for k in KPIS}
    for code, ok, a, b in comparaison:
        (logger.info if ok else logger.error)("[%s] %-30s SQL=%s  Python=%s", "OK" if ok else "KO",
                                              par_code[code].libelle, formater(par_code[code], a), b)
    logger.info("Porte G5a : %d/%d - %s ; référence : %s", sum(c[1] for c in comparaison), len(comparaison), md, js)
    return 0 if all(c[1] for c in comparaison) else 1


if __name__ == "__main__":
    sys.exit(main())
