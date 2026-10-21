# Phase 16 — Rapport individuel

*EduSmart Decision Platform · Lot L10 · Ndeye Penda SARR · Master 2 Business Intelligence, UCAD*

> **PDF, Phase 16 (projet individuel) :** développer son pipeline ETL ou ELT ; intégrer sa source de données ; participer à la construction du Data Warehouse ; proposer un schéma multidimensionnel ; définir les KPI ; construire un tableau de bord ; rédiger un rapport d'analyse.
>
> **Lecteur visé :** l'enseignant et tout lecteur technique. Ce rapport explique **ce qui a été construit, comment, pourquoi ainsi, et ce que j'en ai appris**. Le rapport destiné au Directeur Général est le [rapport décisionnel](17_rapport_decisionnel.md) (Phase 17).

---

## 1. Contexte et périmètre

EduSmart est une plateforme de formation en ligne dont les données sont dispersées dans **cinq systèmes** qui ne se parlent pas (PDF « Données EduSmart ») : la gestion académique (PostgreSQL), la plateforme pédagogique (MySQL), les ressources humaines (fichiers CSV), les journaux de l'application mobile (MongoDB) et la plateforme temps réel (Redis). Le Directeur Général veut une plateforme décisionnelle unique.

**Une particularité de ce projet : il a été réalisé seule.** Le PDF prévoit un groupe de cinq, chaque membre étant responsable d'une source. J'ai donc construit **les cinq sources**, puis la totalité de la chaîne décisionnelle. Ce rapport couvre l'ensemble ; le découpage entre « projet individuel » (Phase 16) et « projet collaboratif » (Phase 17) devient un découpage **par public** : ce rapport pour le lecteur technique, le rapport 17 pour le décideur.

## 2. Les 7 livrables de la Phase 16, et leur preuve

| # | Livrable demandé (PDF) | Ce qui a été produit | Preuve vérifiable |
|---|---|---|---|
| 1 | Développer son pipeline ETL ou ELT | Pipeline **ELT** : 5 extracteurs, chargement, transformation SQL dans l'entrepôt, orchestrateur | `pipeline/`, porte **G2 85/85** |
| 2 | Intégrer sa source de données | Les **5 sources** construites, générées (Python, Faker) et volontairement dégradées : 69 types d'anomalies | `sources/s1_postgresql/` à `s5_redis/`, portes **G1 195/195** |
| 3 | Participer à la construction du DW | Entrepôt PostgreSQL en 3 couches (bronze, argent, or), 89 règles qualité, métadonnées | `pipeline/sql/`, portes **G3 69/69** et **G4 57/57** |
| 4 | Proposer un schéma multidimensionnel | Constellation de **8 faits** et **7 dimensions**, SCD 2 sur l'étudiant, 2 cubes OLAP | [07_conception_dw.md](07_conception_dw.md), [10_olap.md](10_olap.md) |
| 5 | Définir les KPI | **8 KPI** calculés par deux chemins indépendants ; la satisfaction déclarée non mesurable | [11_kpi.md](11_kpi.md), porte **G5a 8/8** |
| 6 | Construire un tableau de bord | Power BI, 4 pages, 31 mesures DAX, 26 relations, 5 hiérarchies | `powerbi/EduSmart.pbix`, porte **G5b 8/8** |
| 7 | Rédiger un rapport d'analyse | Data Storytelling, rapport décisionnel | [14_data_storytelling.md](14_data_storytelling.md), [17_rapport_decisionnel.md](17_rapport_decisionnel.md) |

Et, au-delà du PDF : une porte de **tests de bout en bout** (**G6 101/101**) et **372 tests automatisés** (§ 7).

## 3. La démarche : des lots et des portes de contrôle

Le projet a été découpé en **11 lots** (L0 à L10). Chaque lot suit le même cycle : plan détaillé, validation, production, exécution des tests, correction, validation. Un lot n'est validé que si sa **porte de contrôle** est entièrement verte.

| Lot | Contenu | Phases du PDF | Porte | Résultat |
|---|---|---|---|---|
| L0 | Infrastructure Docker (6 services), configuration, journalisation | — | G0 | 5/5 |
| L1 | Référentiel maître : 10 500 personnes | — | — | Livré |
| L2 (a à e) | Les 5 sources | Projet précédent | G1 | 195/195 |
| L3 | Recherches : opérationnel vers décisionnel, besoin métier, architectures, ETL ou ELT | 1 à 4 | — | Validé |
| L4 | Pipeline : extraction, staging, métadonnées | 4, 6 | G2 | 85/85 |
| L5 | Couche clean, contrôle qualité | 5 | G3 | 69/69 |
| L6 | Data Warehouse, SCD 2 | 7, 8, 9 | G4 | 57/57 |
| L7 | OLAP, KPI | 10, 11 | G5a | 8/8 |
| L8 | Visualisations, Power BI | 12, 13 | G5b | 8/8 |
| L9 | Data Storytelling, tests du pipeline | 14, 15 | G6 | 101/101 |
| L10 | Rapports, présentation | 16, 17, 18 | — | Ce document |

**Outils et assistance.** Ce projet a été réalisé avec l'assistance d'un outil d'IA générative (Claude, Anthropic) pour la génération de code, la documentation et la revue de qualité. Les choix de conception ont été arbitrés et validés par l'auteure à chaque lot ; l'exécution des tests, la vérification des résultats et la validation finale ont été effectuées par l'auteure, sur son poste (Windows, Python 3.14, Docker, Power BI Desktop).

**Pourquoi cette méthode ?** Une erreur découverte en L8 dans un chiffre du tableau de bord peut venir de n'importe quelle couche. Avec une porte par couche, chaque couche est prouvée juste **avant** de construire la suivante : quand un écart apparaît, on sait où chercher.

## 4. Les cinq sources

| Source | Technologie | Contenu | Volume | Anomalies injectées |
|---|---|---|---:|---:|
| S1 Gestion académique | PostgreSQL 15 | Étudiants, filières, classes, inscriptions, paiements | 67 882 lignes (5 tables) | 16 types (A01 à A16) |
| S2 Plateforme pédagogique | MySQL 8.0 | Modules, cours, quiz, notes, progression, connexions | 422 218 lignes (6 tables) | 16 types (B01 à B16) |
| S3 Ressources humaines | Fichiers CSV | Enseignants, départements, salaires, absences | 6 728 lignes (4 fichiers) | 19 types (C01 à C19) |
| S4 Application mobile | MongoDB 6 | Événements (14 types) | 297 601 documents | 11 types (D01 à D11) |
| S5 Temps réel | Redis 7 | Sessions, progression, classement, notifications, compteurs | 4 608 clés | 7 types (E01 à E07) |
| **Total** | | | **≈ 800 000 enregistrements** | **69 types** |

Les anomalies suivent les recommandations des PDF sources : doublons, formats de dates multiples, encodages mélangés (UTF-8 et ISO-8859-1), séparateurs différents, catégories mal orthographiées, identifiants incompatibles, enregistrements orphelins. Chaque anomalie est **journalisée** au moment de son injection (`data/anomalies/`). Ce journal sert de vérité terrain pour prouver qu'elle a bien été traitée (porte G3), et il n'est **jamais lu par le pipeline**.

## 5. Les choix structurants, et leurs alternatives

| Décision | Alternative écartée | Pourquoi ce choix | Document |
|---|---|---|---|
| **ELT** (plus précisément EtLT) | ETL | Garder le brut dans l'entrepôt pour **prouver** chaque correction ; changer une règle sans réextraire ; MongoDB et Redis chargés tels quels en JSONB. **Pas** pour une raison de volume : ≈ 800 000 enregistrements, ce n'est pas du Big Data | [04_etl_vs_elt.md](04_etl_vs_elt.md) |
| **Data Warehouse PostgreSQL en couches** (bronze, argent, or) | Data Lake, Lakehouse | Données structurées, volume modeste, besoin de requêtes SQL fiables et traçables | [03_architectures.md](03_architectures.md) |
| **3 actions qualité** : corriger, rejeter, signaler | Tout corriger | **Corriger n'est pas inventer** : 45 règles signalent la valeur au lieu de la deviner | [05_qualite.md](05_qualite.md) |
| **Constellation** de 8 faits | Une étoile unique, un flocon | 8 processus métier avec des grains différents (un paiement, une note, une connexion…), et des dimensions **conformes** partagées | [07_conception_dw.md](07_conception_dw.md) |
| **7 dimensions** au lieu des 5 du PDF | Formation unique | Le PDF mélange l'offre diplômante (filière, classe) et l'offre en ligne (module, quiz) : deux hiérarchies différentes, donc trois dimensions | [07_conception_dw.md](07_conception_dw.md) |
| **SCD 2** sur la ville et la région de l'étudiant | SCD 1 (écraser) | Un paiement de 2024 doit rester attribué à la région de 2024 (cas pratique de la Phase 9) | [07_conception_dw.md](07_conception_dw.md) |
| **Nombre réel d'étudiants** = personnes distinctes | Somme des sources | La somme naïve donne **26 476**, le rapprochement **10 500** | [11_kpi.md](11_kpi.md) |
| **Médiane** du temps de connexion | Moyenne | Résiste aux sessions anormales (jusqu'à 480 min) | [11_kpi.md](11_kpi.md) |
| **Satisfaction déclarée non mesurable** | Indicateur de substitution | Aucune source ne la contient ; un substitut tromperait le décideur | [11_kpi.md](11_kpi.md) |
| **Étoiles pures** dans Power BI | Reproduire le flocon du DW | Deux chemins vers une même dimension rendent le filtrage ambigu | [13_powerbi.md](13_powerbi.md) |

## 6. Difficultés rencontrées et solutions

Chaque difficulté ci-dessous a réellement eu lieu ; elle est tracée dans le lot indiqué.

| # | Lot | Difficulté | Cause | Solution | Ce que j'en retiens |
|---|---|---|---|---|---|
| 1 | L1 | Un même étudiant porte deux identifiants (UUID dans PostgreSQL, `LMS-XXXXXX` dans MySQL) | Systèmes conçus séparément (PDF MySQL : « ne pas utiliser `id_etudiant` ») | Table de correspondance `mapping_etudiants` (9 000 paires), 1 000 inscrits sans compte LMS et 500 comptes LMS sans inscription rendus visibles | L'intégration commence par la question « qui est qui ? » |
| 2 | L2-c, L4 | Données différentes sur deux postes, à graine identique | Faker produit des dates qui dépendent du fuseau de la machine, et Windows refuse les dates antérieures à 1970 | `common.seed.random_date` : on tire un nombre de jours, jamais une date Faker (convention C25) | La reproductibilité se teste, elle ne se suppose pas |
| 3 | L5 | Une anomalie Redis introuvable par la porte G3 | `statistics:today` expire au bout d'une heure : la donnée a disparu avant l'extraction | Garde-fou à l'extraction (alerte), tolérance de G3 **limitée à Redis**, régénération du snapshot juste avant le pipeline | Une source volatile se juge à l'instant de son extraction |
| 4 | L6 | L'étape DW refusée par le journal | `CREATE TABLE IF NOT EXISTS` ne modifie pas une table existante : la contrainte `ck_log_etape` de L4 ignorait l'étape `DW` | La contrainte est redéfinie (`DROP` puis `ADD`) à chaque initialisation | Un script « idempotent » doit aussi savoir faire **évoluer** un schéma |
| 5 | L6 | `TRANSFORM s2_mysql` : **486 s** | Les tables temporaires n'ont pas de statistiques : PostgreSQL estimait 1 ligne là où il y en avait des dizaines de milliers, et choisissait des boucles imbriquées | 51 `ANALYZE` explicites : **23 s** (21 fois plus rapide), chiffres inchangés | Mesurer avant d'optimiser (`EXPLAIN`, `scripts/diagnostic_perf.py`) |
| 6 | L8 | Filtrage ambigu dans Power BI | Relations créées automatiquement, branche en flocon `dim_quiz` → `dim_module` | 2 relations supprimées, modèle en étoiles pures, aucun filtrage bidirectionnel | Ne jamais accepter les relations automatiques sans les relire |
| 7 | L8 | Pas de boxplot natif dans Power BI | Limite de l'outil | Visuel certifié AppSource, avec le graphique Python en alternative | Connaître les limites de l'outil avant de promettre un visuel |
| 8 | L9 | Une perte de lignes peut passer inaperçue | Une ligne écartée par un filtre ne lève aucune erreur | Équation de conservation (staging = clean + rejets) et **tests de mutation** : on casse volontairement une donnée pour vérifier que le test la détecte | Un test qui ne peut pas échouer ne prouve rien |
| 9 | L10 | Un taux de recouvrement de **2 821 %** dans Power BI, puis de **32 à 47 %** dans ma requête de vérification | Ma requête joignait les paiements et les inscriptions **ligne à ligne** : le montant dû de chaque inscription était compté une fois **par paiement** (2,29 paiements par inscription ; 90,10 % ÷ 2,29 ≈ 39,4 %). C'est le « chasm trap » de la modélisation dimensionnelle | Agréger chaque fait **séparément**, puis joindre les résultats : Kaffrine est à **89,68 %**. Hypothèse « déménagements SCD 2 » réfutée par deux requêtes (0 paiement rattaché à une autre région que son inscription ; 0 version SCD 2). **Cause du 2 821 %** : dans Power BI, la relation `fact_paiements → dim_region` était **inactive** ; le filtre de région ne touchait pas le CA. Relation rendue active | Dans une constellation, on n'additionne jamais les mesures de deux faits joints ligne à ligne. Une hypothèse se **teste** avant d'être écrite. Et un total juste ne prouve pas qu'un modèle filtre juste : la porte G5b, qui ne contrôle que des totaux, était verte |

## 7. Tests et qualité

| Niveau | Volume | Rôle |
|---|---:|---|
| Tests unitaires (sans base) | 303 | Règles de nettoyage, calculs des KPI, équation de conservation, cohérence des chiffres des rapports |
| Tests d'intégration (5 vraies sources) | 69 | Pipeline complet, portes, idempotence, cas limites du SCD 2, **9 tests de mutation** |
| Portes de contrôle | G0 à G6 | 7 portes, toutes vertes |

Les KPI sont calculés par **trois chemins** qui doivent donner le même résultat : SQL sur le DW, Python sur la couche clean (porte G5a), DAX dans Power BI (porte G5b). La porte G6 fige ces valeurs : toute modification du pipeline qui changerait un KPI la fait échouer.

Le détail est dans [15_tests_pipeline.md](15_tests_pipeline.md).

## 8. Limites du projet

| Limite | Conséquence | Où c'est documenté |
|---|---|---|
| **Données simulées** | Plusieurs « constats » restituent des paramètres du générateur (pic d'activité à 20 h, poids de Dakar, abandon de 6 %) : ils valident le pipeline, pas un comportement réel | [14_data_storytelling.md](14_data_storytelling.md), § 8.1 |
| **Satisfaction et évaluation des enseignants absentes** | 2 des 7 questions du DG restent sans réponse | [02_besoin_metier.md](02_besoin_metier.md) |
| **KPI d'activité incomplet** | Les vidéos et téléchargements MongoDB ne sont pas dans le DW | [11_kpi.md](11_kpi.md) |
| **Snapshot Redis unique** | Pas d'historique temps réel (une seule photographie, le 15/09/2026 à 23 h) | Convention C24 |
| **Pas de déploiement** | Le pipeline tourne à la demande, sans planificateur (Airflow, cron) ni rafraîchissement automatique du tableau de bord | — |

## 9. Bilan personnel

*Texte de l'auteure.*

**Durée et méthode.** J'ai consacré environ trois semaines à ce projet, en travaillant par lots successifs (L0 à L10), avec une méthode rigoureuse de tests et de portes de contrôle.

**Ce qui a été le plus difficile.** La gestion des 159 946 anomalies dans la couche clean : il fallait à la fois les corriger, les tracer et ne pas casser les KPI validés. Puis la compréhension du fan-out dans ma requête Kaffrine, qui m'a fait réaliser qu'une jointure ligne à ligne entre deux faits fausse tout.

**Ce que j'ai préféré.** La construction du tableau de bord Power BI, parce qu'elle transforme dix lots de travail technique en quelque chose de visuel et de compréhensible pour un décideur.

**Ce que j'ai appris.** Les fondamentaux de la BI de bout en bout (ETL/ELT, Data Warehouse en constellation, OLAP, KPI, Power BI), mais aussi la rigueur nécessaire pour intégrer cinq sources hétérogènes sans perdre une seule ligne, et l'importance des tests automatisés (372 tests : 303 unitaires et 69 d'intégration) pour garantir la fiabilité.

**Ce que je referais autrement.** Je prendrais plus de temps sur la modélisation initiale pour anticiper les pièges comme le fan-out, et je documenterais mes décisions au fur et à mesure plutôt qu'à la fin.

## 10. Compétences mobilisées

Chaque compétence renvoie à un élément vérifiable du dépôt.

| Domaine | Compétence | Preuve |
|---|---|---|
| Ingénierie des données | Pipeline ELT multi-sources (SQL et NoSQL), idempotent, journalisé | `pipeline/run_pipeline.py`, `meta.etl_execution_log` |
| SQL (PostgreSQL) | CTE, fonctions de fenêtrage, `JSONB`, fonctions PL/pgSQL, `GROUP BY CUBE`, optimisation (`ANALYZE`, `EXPLAIN`) | `pipeline/sql/` |
| Python | psycopg2, PyMySQL, pymongo, redis-py, pandas, Faker | `sources/`, `pipeline/` |
| Qualité des données | 89 règles sur 5 dimensions (complétude, unicité, cohérence, exactitude, fraîcheur), rejets tracés | [05_qualite.md](05_qualite.md) |
| Modélisation | Constellation, dimensions conformes, grain, SCD 2, membres « Inconnu » | [07_conception_dw.md](07_conception_dw.md) |
| BI et visualisation | Power BI (DAX, modèle en étoile, hiérarchies, segments), matplotlib | `powerbi/`, `scripts/visualisations.py` |
| Tests | pytest, tests d'intégration, tests de mutation, portes de contrôle | `tests/`, `pipeline/verify_g*.py` |
| Infrastructure | Docker Compose (6 services), configuration par variables d'environnement | `docker/` |
| Communication | Data Storytelling, recommandations à un décideur, honnêteté sur les limites | [14_data_storytelling.md](14_data_storytelling.md), [17_rapport_decisionnel.md](17_rapport_decisionnel.md) |

## Références

- PDF « BI Recherche P8 », Phases 1 à 18 ; PDF « Données EduSmart » ; PDF des 5 sources.
- R. Kimball et M. Ross, *The Data Warehouse Toolkit*, 3ᵉ éd. (2013).
- R. Kimball et J. Caserta, *The Data Warehouse ETL Toolkit* (2004).
- Documentation du projet : [docs/README.md](README.md).
