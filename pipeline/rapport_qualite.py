"""
pipeline/rapport_qualite.py — Rapport qualité automatisé (Phase 5, Lot L5)
=========================================================================

Calcule, pour le lot traité, les indicateurs EXIGÉS par le PDF (Phase 5, TP) :
    nombre de lignes extraites · lignes rejetées · doublons · valeurs manquantes
    · incohérences détectées · corrections effectuées
et un taux de conformité pour chacune des 5 dimensions étudiées :
    complétude · unicité · cohérence · exactitude · fraîcheur.

Résultats stockés dans quality.synthese et quality.dimensions, et rapport
Markdown : data/reports/qualite_<batch_id>.md
"""

from __future__ import annotations

from datetime import datetime

from common.config import get_settings
from pipeline.qualite_regles import DIMENSIONS, REGLES

# (source, table des constats, table de staging, filtre staging, table clean)
TABLES = (
    ("s1_postgresql", "etudiants", "stg_pg_etudiants", None, "etudiants"),
    ("s1_postgresql", "filieres", "stg_pg_filieres", None, "filieres"),
    ("s1_postgresql", "classes", "stg_pg_classes", None, "classes"),
    ("s1_postgresql", "inscriptions", "stg_pg_inscriptions", None, "inscriptions"),
    ("s1_postgresql", "paiements", "stg_pg_paiements", None, "paiements"),
    ("s2_mysql", "modules", "stg_mysql_modules", None, "modules"),
    ("s2_mysql", "cours", "stg_mysql_cours", None, "cours"),
    ("s2_mysql", "quiz", "stg_mysql_quiz", None, "quiz"),
    ("s2_mysql", "notes", "stg_mysql_notes", None, "notes"),
    ("s2_mysql", "progression", "stg_mysql_progression", None, "progression"),
    ("s2_mysql", "temps_connexion", "stg_mysql_temps_connexion", None, "temps_connexion"),
    ("s3_csv", "enseignants", "stg_csv_enseignants", None, "enseignants"),
    ("s3_csv", "departements", "stg_csv_departements", None, "departements"),
    ("s3_csv", "salaires", "stg_csv_salaires", None, "salaires"),
    ("s3_csv", "absences", "stg_csv_absences", None, "absences"),
    ("s4_mongodb", "events", "stg_mongo_events", None, "evenements"),
    ("s5_redis", "sessions", "stg_redis_keys", "cle LIKE 'session:%'", "redis_sessions"),
    ("s5_redis", "progress", "stg_redis_keys", "cle LIKE 'progress:%'", "redis_progress"),
    ("s5_redis", "notifications", "stg_redis_keys", "cle LIKE 'notifications:%'", "redis_notifications"),
    ("s5_redis", "cles_etudiant", "stg_redis_keys",
     "split_part(cle, ':', 1) IN ('last_course', 'last_quiz', 'progress', 'notifications')", None),
    ("s5_redis", "compteurs", "stg_redis_keys", "cle IN ('online_users', 'statistics:today')", "redis_compteurs"),
)
# Dernière donnée métier de chaque source (fraîcheur)
FRAICHEUR = {
    "s1_postgresql": "SELECT max(date_paiement)::TIMESTAMP FROM clean.paiements",
    "s2_mysql": "SELECT max(date_passage) FROM clean.notes",
    "s3_csv": "SELECT max(date_absence)::TIMESTAMP FROM clean.absences",
    "s4_mongodb": "SELECT max(horodatage) FROM clean.evenements",
    "s5_redis": "SELECT max(last_activity) FROM clean.redis_sessions",
}
DIM_REGLES = {d: [r.code for r in REGLES if r.dimension == d] for d in DIMENSIONS}
_ACTIONS = {r.code: r.action for r in REGLES}


def _scalar(cur, sql, params=None):
    cur.execute(sql, params or None)          # None : sinon psycopg2 interprète le '%' de LIKE 'x:%'
    return cur.fetchone()[0]


def calculer(conn, batch_id: str) -> tuple[list[dict], list[dict]]:
    """Remplit quality.synthese et quality.dimensions ; renvoie leurs lignes."""
    lignes, dims = [], []
    with conn.cursor() as cur:
        cur.execute("DELETE FROM quality.synthese WHERE batch_id = %s", (batch_id,))
        cur.execute("DELETE FROM quality.dimensions WHERE batch_id = %s", (batch_id,))
        for source, table, stg, filtre, clean_t in TABLES:
            where = f"WHERE {filtre}" if filtre else ""
            extraites = _scalar(cur, f"SELECT COUNT(*) FROM staging.{stg} {where}")
            cur.execute("""SELECT code_regle, COUNT(*) FROM quality.constats
                           WHERE batch_id = %s AND code_source = %s AND table_source = %s GROUP BY 1""", (batch_id, source, table))
            par_regle = dict(cur.fetchall())
            rejetees = _scalar(cur, """SELECT COUNT(*) FROM quality.rejets WHERE batch_id = %s AND code_source = %s
                                       AND table_source = %s""", (batch_id, source, table))
            clean_n = _scalar(cur, f"SELECT COUNT(*) FROM clean.{clean_t}") if clean_t else extraites - rejetees
            somme = lambda codes: sum(n for c, n in par_regle.items() if c in codes)
            ligne = {"source": source, "table": table, "extraites": extraites, "rejetees": rejetees, "clean": clean_n,
                     "doublons": somme(DIM_REGLES["UNICITE"]), "manquants": somme(DIM_REGLES["COMPLETUDE"]),
                     "incoherences": somme(DIM_REGLES["COHERENCE"] + DIM_REGLES["EXACTITUDE"]),
                     "corrections": sum(n for c, n in par_regle.items() if _ACTIONS[c] == "CORRIGE")}
            lignes.append(ligne)
            cur.execute("INSERT INTO quality.synthese VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (batch_id, source, table, extraites, rejetees, clean_n, ligne["doublons"], ligne["manquants"],
                         ligne["incoherences"], ligne["corrections"]))

        sources = sorted({t[0] for t in TABLES})
        for source in sources:
            controlees = sum(l["extraites"] for l in lignes if l["source"] == source and l["table"] != "cles_etudiant")
            for dim in DIMENSIONS[:-1]:
                defaut = _scalar(cur, """SELECT COUNT(DISTINCT (table_source, id_ligne)) FROM quality.constats
                                         WHERE batch_id = %s AND code_source = %s AND code_regle = ANY(%s)""",
                                 (batch_id, source, DIM_REGLES[dim]))
                taux = round(1 - defaut / controlees, 4) if controlees else None
                dims.append({"dimension": dim, "source": source, "controlees": controlees, "defaut": defaut,
                             "taux": taux, "mesure": None})
            derniere = _scalar(cur, FRAICHEUR[source])
            extraction = _scalar(cur, "SELECT min(_extracted_at) FROM staging." +
                                 next(t[2] for t in TABLES if t[0] == source))
            reference = datetime.combine(get_settings().generation.date_reference, datetime.max.time())
            retard = (reference - derniere).days if derniere else None
            mesure = (f"dernière donnée {derniere:%d/%m/%Y %H:%M} ; retard sur la date de référence "
                      f"(15/09/2026) : {retard} j ; extraction le {extraction:%d/%m/%Y %H:%M}") if derniere else "aucune donnée"
            dims.append({"dimension": "FRAICHEUR", "source": source, "controlees": 1, "defaut": 0, "taux": None,
                         "mesure": mesure, "retard": retard})
        for d in dims:
            cur.execute("INSERT INTO quality.dimensions VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (batch_id, d["dimension"], d["source"], d["controlees"], d["defaut"], d["taux"], d["mesure"]))
    conn.commit()
    return lignes, dims


def ecrire_rapport(conn, batch_id: str, lignes: list[dict], dims: list[dict]) -> str:
    with conn.cursor() as cur:
        cur.execute("""SELECT c.code_regle, r.dimension, r.action, r.anomalies, COUNT(*) FROM quality.constats c
                       JOIN quality.regles r USING (code_regle) WHERE c.batch_id = %s
                       GROUP BY 1, 2, 3, 4 ORDER BY 1""", (batch_id,))
        regles = cur.fetchall()
    fmt = lambda n: f"{n:,}".replace(",", " ")
    tot = {k: sum(l[k] for l in lignes if l["table"] != "cles_etudiant")
           for k in ("extraites", "rejetees", "clean", "doublons", "manquants", "incoherences", "corrections")}
    out = [f"# Rapport qualité — lot {batch_id}", "",
           f"*Généré le {datetime.now():%d/%m/%Y %H:%M} par `pipeline/rapport_qualite.py` (Phase 5).*", "",
           "## 1. Synthèse (indicateurs exigés par le PDF)", "",
           "| Indicateur | Total |", "|---|---:|",
           f"| Lignes extraites | {fmt(tot['extraites'])} |", f"| Lignes rejetées | {fmt(tot['rejetees'])} |",
           f"| Lignes en couche clean | {fmt(tot['clean'])} |", f"| Doublons | {fmt(tot['doublons'])} |",
           f"| Valeurs manquantes | {fmt(tot['manquants'])} |", f"| Incohérences détectées | {fmt(tot['incoherences'])} |",
           f"| Corrections effectuées | {fmt(tot['corrections'])} |", "",
           "## 2. Par table", "",
           "| Source | Table | Extraites | Rejetées | Clean | Doublons | Manquants | Incohérences | Corrections |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|",
           *[f"| {l['source']} | {l['table']} | {fmt(l['extraites'])} | {fmt(l['rejetees'])} | {fmt(l['clean'])} | "
             f"{fmt(l['doublons'])} | {fmt(l['manquants'])} | {fmt(l['incoherences'])} | {fmt(l['corrections'])} |"
             for l in lignes], "",
           "*Redis : une ligne de staging = une clé. `cles_etudiant` regroupe les clés rattachées à un étudiant "
           "(les rejets E06 y sont comptés) ; les messages de notification en double sont comptés dans `notifications`.*", "",
           "## 3. Les 5 dimensions de la qualité (taux de conformité = 1 − lignes en défaut / lignes contrôlées)", "",
           "| Source | Complétude | Unicité | Cohérence | Exactitude |", "|---|---:|---:|---:|---:|"]
    for source in sorted({d["source"] for d in dims}):
        vals = {d["dimension"]: d for d in dims if d["source"] == source}
        out.append(f"| {source} | " + " | ".join(
            f"{100 * vals[dim]['taux']:.2f} %" if vals[dim]["taux"] is not None else "—"
            for dim in ("COMPLETUDE", "UNICITE", "COHERENCE", "EXACTITUDE")) + " |")
    out += ["", "### Fraîcheur", "", "| Source | Mesure |", "|---|---|",
            *[f"| {d['source']} | {d['mesure']} |" for d in dims if d["dimension"] == "FRAICHEUR"], "",
            "Les données métier s'arrêtent à la date de référence de la simulation (C20). Pour PostgreSQL, les derniers "
            "paiements datent du printemps (fin des tranches de l'année académique) : c'est un retard **métier**, pas "
            "un défaut d'extraction. Redis reflète l'instant de son snapshot (C24).", "",
            "## 4. Détail par règle", "",
            "| Règle | Dimension | Action | Anomalies couvertes | Constats |", "|---|---|---|---|---:|",
            *[f"| {c} | {d} | {a} | {', '.join(an) or '—'} | {fmt(n)} |" for c, d, a, an, n in regles], ""]
    path = get_settings().paths.reports_dir / f"qualite_{batch_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return str(path)
