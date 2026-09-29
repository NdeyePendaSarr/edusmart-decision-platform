"""
scripts/visualisations.py — Les 5 graphiques de la Phase 12, produits depuis le DW (Lot L8)
==========================================================================================

Chaque graphique répond à UNE question du décideur ; son choix est justifié dans
docs/12_visualisations.md (pourquoi ce choix, pourquoi pas un autre).

    histogramme  : comment se répartissent les scores sur 20 ?
    boxplot      : la durée de connexion dépend-elle de l'appareil ?
    scatterplot  : le nombre de tentatives est-il lié au score ? le temps connecté à la progression ?
    heatmap      : quand les étudiants se connectent-ils (jour x heure) ?
    barplot      : quelles régions portent le chiffre d'affaires ?

Sortie : docs/figures/*.png (également utilisables dans le rapport et la soutenance).
Prérequis : pip install matplotlib

    python -m scripts.visualisations
"""

from __future__ import annotations

import sys
from pathlib import Path

from common.config import get_settings

SORTIE = Path(__file__).resolve().parent.parent / "docs" / "figures"
BLEU, ORANGE, GRIS = "#1f4e79", "#e07b00", "#8c8c8c"


def _lignes(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def _sauver(fig, nom: str) -> str:
    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = SORTIE / nom
    fig.savefig(chemin, dpi=130, bbox_inches="tight")
    return str(chemin)


def histogramme(conn, plt) -> str:
    scores = [float(s) for (s,) in _lignes(conn, "SELECT score_sur_20 FROM dw.fact_notes WHERE score_sur_20 IS NOT NULL")]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.hist(scores, bins=[i for i in range(21)], color=BLEU, edgecolor="white")
    med = sorted(scores)[len(scores) // 2]
    ax.axvline(med, color=ORANGE, linewidth=2, label=f"médiane : {med:.1f}/20")
    ax.axvline(10, color=GRIS, linestyle="--", linewidth=1, label="10/20")
    ax.set(title=f"Répartition des scores aux quiz ({len(scores):,} tentatives)".replace(",", " "),
           xlabel="Score sur 20 (tranches de 1 point)", ylabel="Nombre de tentatives")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _sauver(fig, "01_histogramme_scores.png")


def boxplot(conn, plt) -> str:
    donnees = {}
    for appareil, d in _lignes(conn, "SELECT appareil, duree_secondes / 60.0 FROM dw.fact_connexions WHERE duree_secondes IS NOT NULL"):
        donnees.setdefault(appareil, []).append(float(d))
    appareils = sorted(donnees, key=lambda a: -len(donnees[a]))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.boxplot([donnees[a] for a in appareils], tick_labels=[f"{a}\n({len(donnees[a]):,} connexions)".replace(",", " ") for a in appareils],
               showfliers=True, flierprops={"marker": ".", "markersize": 2, "alpha": 0.3, "markeredgecolor": GRIS},
               medianprops={"color": ORANGE, "linewidth": 2}, patch_artist=True, boxprops={"facecolor": "#dbe7f3"})
    # Longue traîne (jusqu'à 480 min) : l'axe est limité à 150 min pour lire les boîtes,
    # et les valeurs au-delà sont COMPTÉES à l'écran (rien n'est masqué en silence).
    limite = 150
    for i, a in enumerate(appareils, start=1):
        au_dela = sum(1 for d in donnees[a] if d > limite)
        ax.text(i + 0.2, limite * 0.97, f"{au_dela} au-delà de {limite} min\n({100 * au_dela / len(donnees[a]):.1f} %)",
                ha="left", va="top", fontsize=7, color=GRIS)
    ax.set_ylim(0, limite)
    ax.set(title="Durée de connexion selon l'appareil : distributions identiques", ylabel="Durée (minutes)")
    ax.spines[["top", "right"]].set_visible(False)
    return _sauver(fig, "02_boxplot_connexion_appareil.png")


def scatterplot(conn, plt) -> str:
    import statistics
    etu = _lignes(conn, """SELECT COUNT(*), AVG(score_sur_20) FROM dw.fact_notes f JOIN dw.dim_etudiant d USING (etudiant_key)
                           WHERE score_sur_20 IS NOT NULL GROUP BY d.etudiant_id""")
    eng = _lignes(conn, """WITH e AS (SELECT d.etudiant_id, SUM(c.duree_secondes) / 3600.0 AS h FROM dw.fact_connexions c
                                      JOIN dw.dim_etudiant d USING (etudiant_key) GROUP BY 1),
                                p AS (SELECT etudiant_id, AVG(pourcentage) AS pr FROM dw.fact_progression GROUP BY 1)
                           SELECT e.h, p.pr FROM e JOIN p USING (etudiant_id) WHERE e.h IS NOT NULL AND p.pr IS NOT NULL""")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    for ax, pts, titre, xl, yl in ((a1, etu, "Tentatives et score moyen", "Tentatives par étudiant", "Score moyen sur 20"),
                                   (a2, eng, "Temps connecté et progression", "Heures connectées par étudiant", "Progression moyenne (%)")):
        x, y = [float(p[0]) for p in pts], [float(p[1]) for p in pts]
        r = statistics.correlation(x, y)
        ax.scatter(x, y, s=4, alpha=0.25, color=BLEU)
        ax.set(title=f"{titre} : r = {r:.2f}", xlabel=xl, ylabel=yl)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"Une étudiante ou un étudiant = un point ({len(etu):,} étudiants)".replace(",", " "), fontsize=10, color=GRIS)
    return _sauver(fig, "03_scatter_relations.png")


def heatmap(conn, plt) -> str:
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    grille = [[0] * 24 for _ in jours]
    for js, h, n in _lignes(conn, """SELECT t.jour_semaine, c.heure, COUNT(*) FROM dw.fact_connexions c
                                     JOIN dw.dim_temps t USING (date_key) GROUP BY 1, 2"""):
        grille[js - 1][int(h)] = n
    fig, ax = plt.subplots(figsize=(11, 3.6))
    im = ax.imshow(grille, aspect="auto", cmap="YlOrRd")
    ax.set_yticks(range(7), jours)
    ax.set_xticks(range(0, 24, 2), [f"{h}h" for h in range(0, 24, 2)])
    ax.set(title="Connexions par jour et par heure : l'activité se concentre le soir, tous les jours", xlabel="Heure de connexion")
    fig.colorbar(im, ax=ax, label="Connexions")
    return _sauver(fig, "04_heatmap_activite.png")


def barplot(conn, plt) -> str:
    lignes = _lignes(conn, """SELECT r.region, SUM(p.montant_ca) / 1e6 FROM dw.fact_paiements p JOIN dw.dim_region r USING (region_key)
                              GROUP BY 1 ORDER BY 2""")
    total = sum(float(v) for _, v in lignes)
    fig, ax = plt.subplots(figsize=(8, 5.2))
    couleurs = [ORANGE if i == len(lignes) - 1 else BLEU for i in range(len(lignes))]
    barres = ax.barh([r for r, _ in lignes], [float(v) for _, v in lignes], color=couleurs)
    for b, (_, v) in zip(barres, lignes):
        ax.text(b.get_width() + total * 0.004, b.get_y() + b.get_height() / 2, f"{float(v):,.0f} M ({100 * float(v) / total:.0f} %)".replace(",", " "),
                va="center", fontsize=8)
    ax.set(title="Chiffre d'affaires encaissé par région (millions XOF)", xlabel="CA (millions XOF)")
    ax.spines[["top", "right"]].set_visible(False)
    return _sauver(fig, "05_barplot_ca_region.png")


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")                      # pas de fenêtre : génération de fichiers
    import matplotlib.pyplot as plt
    import psycopg2
    conn = psycopg2.connect(**get_settings().pg_dw.connect_kwargs())
    try:
        for f in (histogramme, boxplot, scatterplot, heatmap, barplot):
            print(f(conn, plt))
            plt.close("all")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
