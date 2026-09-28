"""
pipeline/verify_g3.py — Porte G3 : toutes les anomalies sont-elles traitées ? (Lot L5)
=====================================================================================

Pour CHACUNE des anomalies du journal du volet A (data/anomalies/*.csv, vérité
terrain lue UNIQUEMENT ici, jamais par le pipeline), on cherche une preuve de
traitement dans quality.constats : un constat d'une règle qui couvre ce code
d'anomalie, sur la même ligne.
    - preuve trouvée : l'anomalie est CORRIGÉE, REJETÉE ou SIGNALÉE (décision validée en L5) ;
    - doublons dont la copie porte un NOUVEL identifiant (A10, B12, B15) : il suffit
      que le groupe soit dédoublonné (la copie OU l'original est rejeté).

Porte G3 validée si 100 % des anomalies REÇUES de chacun des 69 types sont traitées.

Cas particulier de Redis, volatile par nature (PDF : « Redis ne conserve pas les données de
manière permanente ») : une anomalie dont la clé a EXPIRÉ avant l'extraction n'est jamais
parvenue au pipeline. Elle est comptée à part, « non extraite », et n'est pas un échec de
traitement. G2 garantit déjà que tout ce qui existait à l'extraction a été extrait. Cette
tolérance ne s'applique qu'à la Source 5 ; le rapport affiche ces anomalies.
Le rapport indique aussi les constats « hors journal » d'une règle, par exemple
les deux lignes d'une référence partagée : c'est une information de précision,
pas un échec.

Rapport : data/reports/G3_<batch_id>.md
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from common.anomaly_journal import read_journal
from common.config import get_settings
from common.logger import get_logger
from pipeline.qualite_regles import DOUBLONS_NOUVEL_ID, REGLES
from pipeline.registry import SOURCES

logger = get_logger("verify_g3")


@dataclass
class ResultatAnomalie:
    code: str
    total: int
    traitees: int
    par_action: dict
    hors_journal: int
    non_extraites: int = 0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.traitees == self.total - self.non_extraites


def regles_par_anomalie() -> dict[str, list]:
    res = defaultdict(list)
    for r in REGLES:
        for a in r.anomalies:
            res[a].append(r)
    return res


def cles_redis(code: str, id_ligne: str) -> list[str]:
    """Clé(s) Redis porteuse(s) d'une anomalie E.. du journal."""
    if code == "E06":                                   # id = student_code, présent dans plusieurs clés
        return [f"{famille}:{id_ligne}" for famille in ("last_course", "last_quiz", "progress", "notifications")]
    if code == "E03" and id_ligne.startswith("statistics:today."):
        return ["statistics:today"]
    return [id_ligne]                                   # session:…, notifications:…, progress:…, online_users


def evaluer(journal: list, preuves: dict[str, dict[str, str]], cles_extraites: set[str] | None = None) -> list[ResultatAnomalie]:
    """
    journal : enregistrements (code, id_ligne, valeur_originale) ;
    preuves : {code_regle: {id_ligne: action}} issu de quality.constats ;
    cles_extraites : clés Redis présentes en staging (None = ne pas tenir compte de l'expiration).
    Fonction PURE (testable sans base).
    """
    par_code = defaultdict(list)
    for rec in journal:
        par_code[rec.code].append(rec)
    couvertures = regles_par_anomalie()
    resultats = []
    for code in sorted(set(couvertures) | set(par_code)):
        recs, regles = par_code.get(code, []), couvertures.get(code, [])
        ids_journal = {r.id_ligne for r in recs} | ({r.valeur_originale for r in recs} if code in DOUBLONS_NOUVEL_ID else set())
        actions, traitees, non_extraites = Counter(), 0, 0
        for rec in recs:
            if cles_extraites is not None and code.startswith("E") and \
                    not any(k in cles_extraites for k in cles_redis(code, rec.id_ligne)):
                non_extraites += 1
                continue
            candidats = [rec.id_ligne] + ([rec.valeur_originale] if code in DOUBLONS_NOUVEL_ID else [])
            action = next((preuves.get(r.code, {}).get(c) for r in regles for c in candidats
                           if preuves.get(r.code, {}).get(c)), None)
            if action:
                traitees += 1
                actions[action] += 1
        hors = sum(1 for r in regles for i in preuves.get(r.code, {}) if i not in ids_journal)
        resultats.append(ResultatAnomalie(code, len(recs), traitees, dict(actions), hors, non_extraites))
    return resultats


def charger_preuves(conn, batch_id: str) -> dict[str, dict[str, str]]:
    preuves = defaultdict(dict)
    with conn.cursor(name="preuves_g3") as cur:
        cur.itersize = 50_000
        cur.execute("SELECT code_regle, id_ligne, action FROM quality.constats WHERE batch_id = %s", (batch_id,))
        for regle, id_ligne, action in cur:
            preuves[regle][id_ligne] = action
    return preuves


def verify(conn, batch_id: str) -> list[ResultatAnomalie]:
    anomalies_dir = get_settings().paths.anomalies_dir
    journal = []
    for source in SOURCES:
        journal += read_journal(anomalies_dir / f"{source}_anomalies.csv")
    with conn.cursor() as cur:
        cur.execute("SELECT cle FROM staging.stg_redis_keys")
        cles = {r[0] for r in cur.fetchall()}
    return evaluer(journal, charger_preuves(conn, batch_id), cles)


def write_report(batch_id: str, resultats: list[ResultatAnomalie]) -> str:
    ok = all(r.ok for r in resultats)
    total = sum(r.total for r in resultats)
    traitees = sum(r.traitees for r in resultats)
    non_extraites = sum(r.non_extraites for r in resultats)
    actions = Counter()
    for r in resultats:
        actions.update(r.par_action)
    fmt = lambda n: f"{n:,}".replace(",", " ")
    lignes = [f"# Porte G3 — lot {batch_id}", "",
              f"*Rapport du {datetime.now():%d/%m/%Y %H:%M}*", "",
              f"**Résultat : {'VALIDÉE' if ok else 'NON VALIDÉE'}** — {fmt(traitees)} / {fmt(total)} anomalies traitées "
              f"({sum(r.ok for r in resultats)}/{len(resultats)} types à 100 %)", "",
              *([f"⚠️ **{non_extraites} anomalie(s) Redis non extraite(s)** : leur clé a expiré avant l'extraction "
                 "(snapshot trop ancien). Pour un contrôle complet, relancer `python -m sources.s5_redis.insert_data` "
                 "juste avant le pipeline.", ""] if non_extraites else []),
              f"Répartition : {fmt(actions['CORRIGE'])} corrigées · {fmt(actions['REJETE'])} rejetées · "
              f"{fmt(actions['SIGNALE'])} signalées", "",
              "| Anomalie | Journal | Non extraites | Traitées | Corrigées | Rejetées | Signalées | Constats hors journal | OK |",
              "|---|---:|---:|---:|---:|---:|---:|---:|:-:|",
              *[f"| {r.code} | {fmt(r.total)} | {fmt(r.non_extraites)} | {fmt(r.traitees)} | {fmt(r.par_action.get('CORRIGE', 0))} | "
                f"{fmt(r.par_action.get('REJETE', 0))} | {fmt(r.par_action.get('SIGNALE', 0))} | {fmt(r.hors_journal)} | "
                f"{'✅' if r.ok else '❌'} |" for r in resultats], "",
              "*« Constats hors journal » : lignes touchées par la même règle sans être dans le journal, par exemple "
              "la seconde ligne d'une référence de paiement partagée (A13) ou d'un titre dupliqué (B03). "
              "Ce n'est pas une erreur : la règle signale toutes les lignes concernées.*", ""]
    path = get_settings().paths.reports_dir / f"G3_{batch_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lignes), encoding="utf-8")
    return str(path)


def main() -> int:
    import psycopg2
    from pipeline.transform import batch_en_staging
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        batch_id = batch_en_staging(conn)
        resultats = verify(conn, batch_id)
    finally:
        conn.close()
    for r in resultats:
        (logger.info if r.ok else logger.error)("[%s] %s %6d/%6d traitées %s", "OK" if r.ok else "KO", r.code,
                                                r.traitees, r.total, r.par_action)
    logger.info("Porte G3 : %d/%d types à 100 %% - %s", sum(r.ok for r in resultats), len(resultats),
                write_report(batch_id, resultats))
    return 0 if all(r.ok for r in resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
