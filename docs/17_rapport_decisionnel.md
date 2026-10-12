# Phase 17 — Rapport décisionnel

*EduSmart Decision Platform · Lot L10 · Données au 15/09/2026 · À l'attention du Directeur Général*

> **PDF, Phase 17 :** fusionner les cinq sources pour produire un pipeline ETL unique, un Data Warehouse commun, une base multidimensionnelle, un cube OLAP, un tableau de bord Power BI et **un rapport décisionnel complet**.
>
> Ce rapport s'adresse au **décideur**. Les choix techniques sont expliqués dans le [rapport individuel](16_rapport_individuel.md) ; le récit détaillé des résultats est dans le [Data Storytelling](14_data_storytelling.md).

---

## 1. Résumé exécutif

> **EduSmart encaisse 90 % de ce qu'elle attend et ses apprenants réussissent leurs quiz (93 %), mais seulement 3 sur 10 sont actifs sur 30 jours. La priorité n'est plus de recruter, c'est d'engager et d'écouter.**

**Ce qui va bien**
- **10 500** étudiants réels, enfin comptés une seule fois (la somme des systèmes en annonçait 26 476).
- **13,554 Mds XOF** encaissés ; activité multipliée par deux en deux ans (3 617 → 7 383 inscriptions).
- **93,13 %** de réussite aux quiz ; sessions médianes de **29 min**.

**Trois alertes**
1. **L'argent non encaissé a doublé en deux ans** : 311 M → 655 M XOF par année académique, à taux de recouvrement constant (≈ 90 %).
2. **71 % des étudiants sans activité mesurée sur 30 jours** : 3 003 actifs sur 10 500 (28,6 %, cible proposée 30 %).
3. **L'abandon dépasse la cible depuis trois ans** : 6,24 % (cible proposée 5 %).

**Deux angles morts** : ni la satisfaction des étudiants, ni la qualité des enseignants ne sont mesurées.

**Un constat RH** : **62 %** des heures d'absence des enseignants ne sont pas remplacées, soit **6 409 heures** de cours perdues en trois ans.

**Sept recommandations** (§ 6), dont deux à lancer en priorité : **mesurer la satisfaction** (R1) et **relancer les impayés** (R3).

## 2. Contexte et périmètre

| Élément | Valeur |
|---|---|
| Sources intégrées | 5 : gestion académique (PostgreSQL), plateforme pédagogique (MySQL), ressources humaines (CSV), application mobile (MongoDB), temps réel (Redis) |
| Volume traité | ≈ 800 000 enregistrements |
| Période | Années académiques 2023-2024 à 2025-2026 (rentrée au 1er octobre) |
| Date de référence | 15/09/2026 : aucune activité au-delà |
| Restitution | Tableau de bord Power BI, 4 pages : Vue Direction, Finance, Pédagogie, Engagement |
| Devise | XOF (franc CFA) |

⚠️ **Les données sont simulées** (générées pour le projet). Les mécanismes de mesure sont réels et vérifiés ; certains constats reflètent les paramètres de la simulation (§ 7.1). Chaque recommandation indique son niveau de confiance.

## 3. Peut-on faire confiance à ces chiffres ?

Oui, et voici pourquoi :

| Garantie | Preuve |
|---|---|
| **Aucune donnée perdue sans trace** | Chaque ligne extraite arrive dans l'entrepôt ou est écartée **avec son motif** : l'équation est vérifiée à chaque exécution, table par table (101 contrôles automatiques) |
| **Les erreurs de saisie sont traitées, pas ignorées** | 159 946 anomalies traitées : 55 853 corrigées, 25 932 traitées par rejet, 78 161 signalées sans être devinées |
| **Chaque KPI est calculé trois fois** | Trois langages, trois couches (SQL sur l'entrepôt, Python sur les données nettoyées, DAX dans Power BI) : même résultat |
| **Les contrôles savent détecter une erreur** | 9 tests introduisent volontairement une erreur (ligne perdue, clé orpheline, montant faussé de 1 000 XOF) : tous détectés |
| **Le tableau de bord est réconcilié avec l'entrepôt** | Un taux aberrant observé dans Power BI (Kaffrine) a été recalculé dans l'entrepôt : 89,68 %, valeur normale (§ 7.2) |

## 4. Les indicateurs clés

| KPI | Valeur au 15/09/2026 | Cible proposée | Statut | Responsable |
|---|---:|---|:-:|---|
| Chiffre d'affaires encaissé | **13,554 Mds XOF** | ≥ CA de l'année précédente à date | ✅ | DG, Finance |
| Taux de recouvrement | **90,10 %** | ≥ 90 % | ✅ (de justesse) | Finance |
| Taux de réussite aux quiz | **93,13 %** | ≥ 85 % | ✅ | Pédagogie |
| Taux d'abandon | **6,24 %** | ≤ 5 % | ⚠️ | DG, Pédagogie |
| Progression moyenne | **65,59 %** | ≥ 70 % | ⚠️ | Pédagogie |
| Étudiants actifs (30 jours) | **3 003** (28,6 %) | ≥ 30 % | ⚠️ | DG |
| Temps médian de connexion | **1 740 s (29 min)** | ≥ 20 min | ✅ | Pédagogie |
| Nombre réel d'étudiants | **10 500** | Suivi | — | DG |
| Satisfaction des étudiants | **Non mesurée** | — | ❌ | DG |

**Les cibles sont des propositions** (lot L7) : aucune source ne contient d'objectif. Elles sont à valider par la direction. Définitions complètes : [11_kpi.md](11_kpi.md).

## 5. Analyse par axe

### 5.1 Finance : l'argent rentre, mais les impayés grossissent

| Année académique | Inscriptions | Montant dû | Encaissé | Non encaissé | Recouvrement |
|---|---:|---:|---:|---:|---:|
| 2023-2024 | 3 617 | 3 179 M | 2 868 M | 311 M | 90,19 % |
| 2024-2025 | 6 191 | 5 624 M | 5 101 M | 523 M | 90,70 % |
| 2025-2026 | 7 383 | 6 240 M | 5 585 M | 655 M | 89,51 % |
| **Total** | | **15 043 M** | **13 554 M** | **≈ 1 489 M** | **90,10 %** |

*Millions de XOF, arrondis. Chaque montant est rattaché à l'année de la formation payée.*

- **Le taux est stable, le montant ne l'est pas.** À 90 % de recouvrement, chaque doublement de l'activité double les impayés.
- **L'année 2025-2026 n'est pas close** : une partie des 655 M peut encore être encaissée.
- **Aucune région n'est en décrochage** : de 88,57 % (Matam) à 93,29 % (Kédougou) ; Dakar à 90,16 %.
- **Saisonnalité** : le pic d'encaissement est en octobre, à la rentrée (1ʳᵉ tranche).

### 5.2 Pédagogie : on réussit les quiz, on ne finit pas les parcours

| Indicateur | Valeur | Lecture |
|---|---|---|
| Réussite aux quiz | 93,13 % | Couples (étudiant, quiz) validés **au moins une fois**, toutes tentatives confondues. Ce n'est **pas** la réussite au diplôme, qu'aucune source ne contient |
| Progression moyenne | 65,59 % | Un tiers des contenus en ligne n'est pas parcouru |
| Abandon | 6,24 % | Stable sur trois ans (6,25 % ; 6,33 % ; 6,16 %) : un phénomène structurel, pas un accident |
| Distribution des scores | Centrée vers 10-12/20, accumulation à 20/20 | Effet plafond : ces quiz ne distinguent plus les meilleurs étudiants |
| Tentatives et score | Relation négative faible (r = −0,20) | Ceux qui retentent ont un score moyen plus bas : un signal pour cibler le tutorat, **pas** une cause |

La source ne date pas l'abandon et n'en donne pas le motif : on sait **combien** abandonnent, pas **quand** ni **pourquoi**.

### 5.3 Engagement : présents le soir, absents sur la durée

| Indicateur | Valeur | Lecture |
|---|---|---|
| Étudiants actifs sur 30 jours | 3 003 (28,6 %) | **Valeur minimale** : les vidéos et téléchargements de l'application mobile ne sont pas encore comptés |
| Temps médian de connexion | 29 min | Identique sur mobile, PC et tablette |
| Créneau d'activité | Pic entre 20 h et 22 h, tous les jours | Aucune connexion entre minuit et 6 h, pas d'effet week-end |
| Heures connectées et progression | Aucune relation (r = −0,01) | Passer plus de temps connecté ne s'accompagne pas d'une meilleure progression |

### 5.4 Ressources humaines

**Masse salariale**

| Année académique | Enseignants | dont permanents | Masse salariale nette | Part des permanents | Salaire net moyen (par bulletin) |
|---|---:|---:|---:|---:|---:|
| 2023-2024 | 114 | 72 | 980,7 M | 89,1 % | 728 038 |
| 2024-2025 | 116 | 74 | 1 033,3 M | 89,8 % | 751 492 (+3,2 %) |
| 2025-2026 | 120 | 78 | 1 020,4 M | 90,3 % | 784 355 (+4,4 %) |
| **Total** | | | **3 034,4 M** | | **+7,7 % en deux ans** |

*Millions de XOF. Année du bulletin de salaire. 2025-2026 ne couvre que 11 mois : les salaires sont versés jusqu'en août 2026.*

- Les **permanents** (65 % des enseignants) représentent **90 %** de la masse salariale ; les vacataires (42 chaque année) en représentent 10 %.
- Sur trois ans, la masse salariale représente **22,4 %** du CA encaissé. C'est un ordre de grandeur : le CA est rattaché à l'année de la formation, les salaires à la date du bulletin.
- **Encadrement** : les inscriptions ont doublé (3 617 → 7 383), les enseignants n'ont augmenté que de 5 % (114 → 120). Soit **31,7 → 61,5 inscriptions par enseignant**. *Prudence : l'effectif enseignant de la simulation est plafonné à 120 par construction (convention C18). Sur données réelles, ce ratio serait un indicateur de charge à suivre.*

**Absences des enseignants**

| Année académique | Absences | Heures | Heures non remplacées | Part non remplacée |
|---|---:|---:|---:|---:|
| 2023-2024 | 798 | 3 581 | 2 144 | 59,9 % |
| 2024-2025 | 774 | 3 400 | 2 211 | 65,0 % |
| 2025-2026 | 771 | 3 384 | 2 054 | 60,7 % |
| **Total** | **2 343** | **10 365** | **6 409** | **61,8 %** |

- **6 409 heures de cours non remplacées en trois ans** : c'est le chiffre RH qui touche directement les étudiants.
- Les motifs sont répartis presque uniformément (de 209 à 239 absences pour 10 motifs). Cette régularité est probablement un effet de la simulation.
- Entre 68 % et 79 % des absences sont justifiées selon le motif.
- **Incohérence de saisie à vérifier** : 89 absences **sans motif**, dont 77,5 % sont pourtant marquées « justifiées ».
- 79 durées aberrantes ont été neutralisées (non comptées dans les heures).

## 6. Recommandations

| # | Recommandation | Constat | KPI de suivi | Responsable | Confiance | Priorité |
|---|---|---|---|---|---|:-:|
| **R1** | Collecter un **score de satisfaction** (1 à 5) à la fin de chaque module | Satisfaction non mesurée | Satisfaction | DG | Haute | **1** |
| **R2** | Créer une **évaluation des enseignements** et une table d'**affectation** enseignant ↔ cours | Qualité des enseignants non mesurée | Note moyenne par enseignant | Pédagogie, RH | Haute | 2 |
| **R3** | **Plan de relance des impayés** dès la 2ᵉ tranche, piloté par le Top 10 des impayés | ≈ 1 489 M XOF non encaissés, en hausse | Recouvrement, impayés | Finance | Moyenne | **1** |
| **R4** | **Programme de réactivation** des inactifs (relance après 15 jours sans activité, tutorat ciblé sur les étudiants qui retentent le plus) | 71 % sans activité mesurée ; abandon 6,24 % ; progression 65,59 % | Actifs (30 j), abandon, progression | Pédagogie | Moyenne | 2 |
| **R5** | Intégrer les **vidéos et téléchargements** au Data Warehouse | KPI d'activité incomplet | Actifs (30 j) | Équipe data | Haute | 3 |
| **R6** | **Normaliser la saisie à la source** (listes fermées : modes de paiement, villes, catégories, motif d'absence obligatoire) | 159 946 anomalies traitées ; absences « justifiées sans motif » | Taux de conformité qualité | DSI, chaque service | Haute | 3 |
| **R7** | Un **dispositif de remplacement** des enseignants absents (vivier de vacataires, cours enregistrés) | 61,8 % des heures d'absence non remplacées | Part des heures remplacées | RH, Pédagogie | Moyenne (à confirmer sur données réelles) | 2 |

**Ce qui n'est pas recommandé** : investir dans une application tablette pour allonger les sessions (durées identiques sur tous les appareils), ni inciter à « se connecter plus longtemps » pour progresser (aucune relation observée).

**Pourquoi R1 en premier ?** Les trois alertes (impayés, inactivité, abandon) ont une cause commune possible que les données actuelles ne permettent pas d'établir. Sans la voix des étudiants, R3 et R4 traitent les symptômes.

## 7. Ce que les données ne permettent pas de dire

### 7.1 Les effets de la simulation

Plusieurs résultats restituent les paramètres du générateur de données : le pic d'activité à 20 h, le poids de Dakar dans le CA (29 %), l'abandon de 6 %, l'uniformité du recouvrement entre filières, l'effectif enseignant plafonné à 120. Ces constats démontrent que la plateforme **sait mesurer** ces phénomènes ; ils ne décrivent pas un comportement réel. Le détail, vérifié dans le code, est au § 8.1 du [Data Storytelling](14_data_storytelling.md).

### 7.2 Le taux de recouvrement par segment : le cas Kaffrine

Un filtre sur la région de Kaffrine affichait **2 821 %** dans Power BI. L'entrepôt a été interrogé directement :

| Vérification | Résultat |
|---|---|
| Recouvrement de Kaffrine, calculé dans l'entrepôt | **89,68 %** : normal (14 régions entre 88,57 % et 93,29 %) |
| Recouvrement par filière à Kaffrine | de 79,84 % à 100 %, **aucun au-dessus de 100 %** |
| Paiements rattachés à une autre région que leur inscription | **0** sur 38 372 |
| Étudiants ayant déménagé (versions SCD 2) | **0** |

**Conclusion** : l'entrepôt est juste ; l'écart vient du **contexte de filtre de Power BI**, dont le mécanisme exact reste à identifier. Les hypothèses « petit effectif » et « déménagements » ont été testées et **réfutées**.

**Règles de lecture pour le décideur :**
- un taux se calcule en agrégeant **séparément** le numérateur (paiements) et le dénominateur (inscriptions) ; additionner après avoir croisé les deux tables gonfle le dénominateur (une vérification intermédiaire, faite ainsi, avait donné 32 à 47 % : un autre faux résultat) ;
- au-delà de 100 %, ou très loin de la moyenne, on vérifie le calcul avant de conclure ;
- sur une petite population (une région × une filière), deux filières à 100 % peuvent ne compter que quelques inscriptions : un taux se lit avec son effectif.

### 7.3 Les autres limites

| Limite | Conséquence |
|---|---|
| Satisfaction et évaluation des enseignants absentes | 2 des 7 questions de la direction sans réponse |
| Abandon non daté, sans motif | On ne peut ni prévenir l'abandon au bon moment, ni en traiter la cause |
| Réussite au diplôme absente | Le taux de réussite ne porte que sur les quiz en ligne |
| Snapshot temps réel unique (15/09/2026, 23 h) | Pas de tendance sur les données temps réel |
| Aucun historique de déménagement dans l'entrepôt actuel | Le mécanisme d'historisation (SCD 2) est en place et testé, mais aucun étudiant n'a changé de ville dans les données chargées |
| Pas de rafraîchissement automatique | Le tableau de bord se met à jour à la demande, après exécution du pipeline |

## 8. Annexes

### 8.1 Glossaire

| Terme | Définition |
|---|---|
| **KPI** | Indicateur clé de performance : une mesure rattachée à un objectif, avec une cible |
| **Recouvrement** | Encaissé ÷ montant dû (frais annuels de la classe, après réduction) |
| **Étudiant actif** | Au moins une connexion, une note ou une activité de quiz dans les 30 jours précédant le 15/09/2026 |
| **Médiane** | Valeur qui partage les observations en deux moitiés égales ; insensible aux valeurs extrêmes |
| **Data Warehouse** | Base de données unique, construite pour l'analyse, qui réunit les 5 sources après nettoyage |
| **SCD 2** | Historisation d'un attribut (ici la ville de l'étudiant) : l'ancienne valeur est conservée avec ses dates de validité |

### 8.2 Pour aller plus loin

| Besoin | Document |
|---|---|
| Le récit détaillé et les objections probables | [14_data_storytelling.md](14_data_storytelling.md) |
| Les fiches des 8 KPI | [11_kpi.md](11_kpi.md) |
| Le tableau de bord, page par page | [13_powerbi.md](13_powerbi.md), `powerbi/EduSmart.pdf` |
| La fiabilité du pipeline | [15_tests_pipeline.md](15_tests_pipeline.md) |
| La démarche technique | [16_rapport_individuel.md](16_rapport_individuel.md) |

*Sources des chiffres : vues `dw.v_kpi` et `dw.v_kpi_annee` (KPI, finance) ; requêtes K1 à K4 et RH1 à RH4 du lot L10, exécutées sur l'entrepôt le 12/10/2026, après validation de la porte G6 (101/101).*
