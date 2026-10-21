# Phase 18 — Présentation

*EduSmart Decision Platform · Lot L10 · Support : [`presentation/EduSmart_presentation.pptx`](../presentation/EduSmart_presentation.pptx) (21 diapositives, 16:9)*

> **PDF, Phase 18 :** présenter 1. le contexte métier, 2. les sources de données, 3. les difficultés d'intégration, 4. le pipeline ETL/ELT, 5. les contrôles qualité réalisés, 6. les métadonnées produites, 7. le Data Warehouse, 8. le modèle multidimensionnel, 9. les KPI retenus, 10. le tableau de bord Power BI, 11. les recommandations stratégiques.
>
> Il n'y a pas de soutenance orale : le support doit se comprendre **seul**. Chaque diapositive porte un titre qui énonce sa conclusion, et des notes de l'orateur qui la complètent.

---

## 1. Principes de construction

| Principe | Application |
|---|---|
| **Commencer par la conclusion** | La diapositive 2 donne l'idée maîtresse et quatre chiffres avant tout détail technique |
| **Un message par diapositive** | Le titre est une phrase (« Le taux de recouvrement est stable, les impayés doublent »), pas un sujet (« Finance ») |
| **Suivre les 11 points du PDF** | Un cercle safran numéroté (1 à 11) signale chaque point ; les diapositives sans numéro sont des résultats ou des limites |
| **Des chiffres vérifiables** | Tous viennent des documents validés (11, 14, 15, 17) ; un test automatique compare ceux du support à la référence des KPI |
| **Le rouge brique pour ce qui s'écarte de la cible** | Abandon, progression, étudiants actifs, impayés, heures non remplacées |
| **Des graphiques natifs** | Les 3 graphiques (qualité, impayés, RH) sont des graphiques PowerPoint modifiables, pas des images |
| **Honnêteté** | Une diapositive dédiée à ce que les données ne permettent pas de dire |

**Palette** : bleu nuit (fonds de titre, textes), sarcelle (résultats conformes), safran (motif, accent), rouge brique (alertes). **Polices** : Cambria pour les titres, Calibri pour le texte (installées avec Office).

## 2. Les 21 diapositives

| # | Section | Point PDF | Titre (le message) | Contenu |
|---:|---|:-:|---|---|
| 1 | Introduction | — | EduSmart Decision Platform | De cinq sources dispersées à une plateforme décisionnelle |
| 2 | Introduction | — | L'essentiel en une page | Idée maîtresse ; 10 500 étudiants réels, 13,554 Mds XOF encaissés, 90,10 % de recouvrement, 3 003 actifs (28,6 %) |
| 3 | Le projet | 1 | Le Directeur Général pose 7 questions | 5 répondues, 2 sans données (satisfaction, évaluation des enseignants) |
| 4 | Le projet | 2 | Cinq sources hétérogènes, volontairement imparfaites | Volumes et types d'anomalies par source (≈ 800 000 enregistrements, 69 types) |
| 5 | Le projet | 3 | Intégrer, c'est d'abord savoir qui est qui | 26 476 → 10 500 personnes ; identifiants, formats, source volatile |
| 6 | Le projet | 4 | ELT : transformer dans l'entrepôt | Schéma sources → bronze → argent → or → Power BI ; pourquoi ELT |
| 7 | Le projet | 5 | 159 946 anomalies traitées, aucune devinée | Graphique corrigées / rejetées / signalées ; 69/69, 89 règles |
| 8 | Le projet | 5 | Sept portes de contrôle, toutes vertes | G0 à G6 ; équation de conservation ; 368 tests ; 9 mutations détectées |
| 9 | Le projet | 6 | Chaque chiffre est traçable jusqu'à sa source | `metadata_sources`, `etl_execution_log`, lignage de bout en bout |
| 10 | Le projet | 7 | Un entrepôt PostgreSQL en trois couches | Bronze, argent, or ; SCD 2 « un étudiant change de ville » |
| 11 | Le projet | 8 | Une constellation de 8 faits et 7 dimensions | Matrice de bus : grain de chaque fait, dimensions partagées |
| 12 | Les résultats | 9 | 8 KPI, et un indicateur que l'on ne sait pas mesurer | 8 cartes valeur / cible / statut ; satisfaction « non mesurée » |
| 13 | Les résultats | 10 | Power BI · Vue Direction : où en sommes-nous ? | CA et dû par année, satisfaction « non mesurée », CA par région ; avant / après le correctif |
| 14 | Les résultats | 10 | Power BI · page Finance : où en est le recouvrement ? | Matrice filière × année, impayés par filière ; principes du tableau de bord |
| 15 | Les résultats | 10 | Power BI · Pédagogie et Engagement | Histogramme des scores, carte de chaleur jour × heure |
| 16 | Les résultats | — | Le taux de recouvrement est stable, les impayés doublent | 311 → 523 → 655 M XOF non encaissés ; régions de 88,57 % à 93,29 % |
| 17 | Les résultats | — | On réussit les quiz, on ne finit pas les parcours | 93,13 % ; 65,59 % ; 6,24 % ; 28,6 % ; associations, pas causes |
| 18 | Les résultats | — | 6 409 heures de cours non remplacées en trois ans | Graphique heures remplacées / non remplacées ; masse salariale ; salaire moyen |
| 19 | Décider | 11 | Sept recommandations, deux priorités | R1 à R7, KPI de suivi, priorité ; pourquoi R1 d'abord |
| 20 | Décider | — | Ce que ces données ne permettent pas de dire | Simulation, angles morts, Kaffrine, absence d'historique SCD 2 |
| 21 | Décider | — | Engager et écouter | Conclusion : première décision, mesurer la satisfaction |

## 3. Les chiffres du support et leur source

| Chiffre | Valeur | Source |
|---|---|---|
| Chiffre d'affaires encaissé | 13,554 Mds XOF | `dw.v_kpi`, [11_kpi.md](11_kpi.md) |
| Taux de recouvrement | 90,10 % | idem |
| Taux de réussite aux quiz | 93,13 % | idem |
| Taux d'abandon | 6,24 % | idem |
| Progression moyenne | 65,59 % | idem |
| Étudiants actifs (30 jours) | 3 003 | idem |
| Temps médian de connexion | 1 740 s (29 min) | idem |
| Nombre réel d'étudiants | 10 500 | idem |
| Anomalies traitées | 159 946 (55 853 corrigées, 25 932 rejetées, 78 161 signalées) | Porte G3, [05_qualite.md](05_qualite.md) |
| Non encaissé par année | 311 M, 523 M, 655 M XOF | `dw.v_kpi_annee`, [17_rapport_decisionnel.md](17_rapport_decisionnel.md) |
| Recouvrement par région | 88,57 % à 93,29 % ; Kaffrine 89,68 % | Requête K1 (lot L10) |
| Heures d'absence non remplacées | 6 409 sur 10 365 (61,8 %) | Requêtes RH3 et RH4 (lot L10) |
| Masse salariale nette | 3 034 M XOF sur trois ans | Requêtes RH1 et RH2 (lot L10) |
| Tests automatisés | 368 (299 unitaires, 69 d'intégration) | [15_tests_pipeline.md](15_tests_pipeline.md) |

## 4. La page Vue Direction et le correctif du 21/10/2026

Dans le premier export du tableau de bord, le graphique « CA encaissé par région » de la page **Vue Direction** affichait 14 barres égales, au niveau du CA total. Cause : la relation `fact_paiements → dim_region` était **inactive** dans le modèle Power BI ; c'était aussi l'origine du taux de 2 821 % observé à Kaffrine. La relation a été rendue active le 21/10/2026 et le tableau de bord réexporté : la diapositive 13 montre la page Vue Direction corrigée, avec le constat avant / après ([13_powerbi.md](13_powerbi.md)).

## 5. Régénérer le support

Le fichier `.pptx` a été construit par programme (pptxgenjs), à partir des chiffres ci-dessus, puis vérifié : validation du format PowerPoint, rendu de chaque diapositive, test automatique des chiffres (`tests/test_rapports.py`). Les captures Power BI sont des recadrages de `powerbi/EduSmart.pdf`. Toute modification d'un KPI doit être répercutée dans le support **et** dans la référence `REFERENCE_KPI` : le test signale tout écart.
