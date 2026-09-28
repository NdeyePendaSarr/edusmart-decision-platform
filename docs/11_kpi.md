# Phase 11 — KPI et indicateurs de performance

*EduSmart Decision Platform · Lot L7 · Étape 5 du module BI*

> **Recherche du PDF :** 1. Qu'est-ce qu'un KPI ? 2. Quelle différence entre KPI et métrique ? 3. Comment choisir un bon KPI ?
>
> **TP :** définir les KPI d'EduSmart (chiffre d'affaires, taux de réussite, taux d'abandon, progression moyenne, satisfaction, nombre d'étudiants actifs) et **justifier chaque KPI**.
>
> Calcul : `dw.v_kpi` et `dw.v_kpi_annee` (`pipeline/sql/olap/10_kpi.sql`) · recalcul indépendant et porte G5a : `pipeline/kpi.py` · mesures DAX : `powerbi/mesures_kpi.dax`. Date de référence : 15/09/2026 (C20).

---

## 1. Qu'est-ce qu'un KPI ?

Un **KPI** (*Key Performance Indicator*, indicateur clé de performance) est une mesure **rattachée à un objectif**, suivie dans le temps, qui déclenche une **décision** quand elle s'écarte de sa cible.

Il répond à la question « sommes-nous en train d'atteindre notre objectif ? ». Il est **peu nombreux** par nature : un tableau de direction en compte 5 à 10.

## 2. KPI ou métrique ?

| | **Métrique** | **KPI** |
|---|---|---|
| Nature | Toute mesure quantifiable | Une métrique **choisie** parce qu'elle traduit un objectif |
| Nombre | Des centaines | Quelques-uns |
| Cible | Non | **Oui**, et un seuil d'alerte |
| Décideur | Aucun en particulier | Un responsable identifié |
| Exemple EduSmart | Nombre de tentatives de quiz ; taux de validation **par tentative** (74 %) | Taux de réussite **par couple étudiant-quiz** (93,13 %) |

L'exemple de la dernière ligne est tiré du cube pédagogique (Phase 10). Les deux chiffres mesurent la « réussite », mais avec des sens opposés. Le taux par tentative **pénalise** l'étudiant qui échoue deux fois puis réussit, alors que l'objectif pédagogique est justement qu'il finisse par réussir. Seul le second traduit l'objectif : c'est le KPI.

**Tout KPI est une métrique ; peu de métriques sont des KPI.**

## 3. Comment choisir un bon KPI ?

Six critères, appliqués à chaque fiche du § 4 :

| Critère | Question |
|---|---|
| **Aligné** | Traduit-il un objectif du DG (Phase 1) ou un besoin métier (Phase 2) ? |
| **Actionnable** | Si la valeur se dégrade, sait-on **qui** agit et **comment** ? |
| **Défini sans ambiguïté** | Deux personnes calculeraient-elles la même valeur ? (définitions validées en L3) |
| **Mesurable** | Les données existent-elles, avec une qualité connue (Phase 5) ? |
| **Pourvu d'une cible** | Sait-on dire si 90 % est bon ou mauvais ? |
| **Honnête sur ses limites** | Ce qu'il ne dit pas est-il écrit ? |

Le critère « mesurable » **élimine la satisfaction** (§ 5).

## 4. Les 8 KPI d'EduSmart

| # | KPI | Valeur au 15/09/2026 | Cible proposée | Décideur |
|---|---|---:|---|---|
| 1 | Chiffre d'affaires encaissé | **13,554 Mds XOF** | ≥ CA de l'année précédente à date | DG, Finance |
| 2 | Taux de recouvrement | **90,10 %** | ≥ 90 % en fin d'année | Finance |
| 3 | Taux de réussite aux quiz | **93,13 %** | ≥ 85 % | Pédagogie |
| 4 | Taux d'abandon | **6,24 %** | ≤ 5 % ⚠️ | DG, Pédagogie |
| 5 | Progression moyenne | **65,59 %** | ≥ 70 % ⚠️ | Pédagogie |
| 6 | Étudiants actifs (30 jours) | **3 003** (28,6 % des étudiants) | ≥ 30 % des étudiants ⚠️ | DG |
| 7 | Temps médian de connexion | **1 740 s (29 min)** | ≥ 20 min | Pédagogie |
| 8 | Nombre réel d'étudiants | **10 500** | suivi | DG |

**Les cibles sont des propositions**, à valider avec la direction : aucune source ne contient d'objectif. Trois KPI sont sous leur cible (⚠️) ; ce seront les points d'attention du Data Storytelling (Phase 14).

Par **année académique de la formation** (`dw.v_kpi_annee`) :

| Année | CA | Montant dû | Recouvrement | Inscriptions | Abandon |
|---|---:|---:|---:|---:|---:|
| 2023-2024 | 2 868 M | 3 179 M | 90,19 % | 3 617 | 6,25 % |
| 2024-2025 | 5 101 M | 5 624 M | 90,70 % | 6 191 | 6,33 % |
| 2025-2026 | 5 585 M | 6 240 M | 89,51 % | 7 383 | 6,16 % |

Le CA est rattaché à l'année **de la formation payée**, et non à la date du paiement. Sinon, les acomptes de juin-septembre 2023 créeraient une année « 2022-2023 » fictive (3 458 paiements). C'est la dimension conforme `dim_formation`, partagée par les paiements et les inscriptions, qui rend ce calcul possible.

### Fiches

Chaque fiche donne : définition, formule, sources, fréquence, cible, justification, limites. Le catalogue complet est `pipeline/kpi.py` (`KPIS`).

**1. Chiffre d'affaires encaissé — 13,554 Mds XOF**
- *Définition* : somme des paiements au statut VALIDE, rattachés à une inscription existante, montants négatifs exclus (définition L3).
- *Formule* : SQL `SUM(montant_ca)` ; DAX `SUM(fact_paiements[montant_ca])`.
- *Sources* : PostgreSQL. *Fréquence* : mensuelle.
- *Justification* : premier indicateur demandé par le DG (Phase 1).
- *Limites* : 1 700 paiements négatifs (A14) exclus ; s'il s'agit d'erreurs de signe, le CA réel est plus élevé, et c'est à trancher avec la finance. Les paiements EN_ATTENTE, ECHOUE et REMBOURSE sont exclus.

**2. Taux de recouvrement — 90,10 %**
- *Définition* : CA encaissé ÷ montant dû, soit les frais annuels de la classe après réduction.
- *Formule* : SQL `SUM(montant_ca) / SUM(montant_du)` ; DAX `DIVIDE([CA encaissé], [Montant dû])`.
- *Sources* : PostgreSQL. *Fréquence* : mensuelle.
- *Justification* : le CA seul ne dit pas si les étudiants paient ce qu'ils doivent ; le recouvrement mesure les **impayés** (environ 1,5 Md XOF au total).
- *Limites* : frais annuels = coût total ÷ nombre d'années (convention L6). Les 541 réductions neutralisées (A11) sont comptées sans réduction. L'année en cours n'est pas close.

**3. Taux de réussite aux quiz — 93,13 %**
- *Définition* : couples (étudiant, quiz) validés au moins une fois ÷ couples tentés (définition L3).
- *Formule* : SQL, `AVG` du maximum de `est_valide` par couple ; DAX, `SUMMARIZE` puis `FILTER` (voir le fichier `.dax`).
- *Sources* : MySQL. *Fréquence* : hebdomadaire.
- *Justification* : demandé par le DG ; compter par couple ne pénalise pas celui qui retente.
- *Limites* : c'est la réussite aux quiz en ligne, **pas au diplôme**, qu'aucune source ne contient (gap L3). Sur les données brutes, on mesurait 91,54 % en L3 : le nettoyage a réuni les tentatives d'un même étudiant écrites avec des `student_code` différents (B13) et retiré les doublons (B12).

**4. Taux d'abandon — 6,24 %**
- *Définition* : inscriptions au statut ABANDON ÷ inscriptions.
- *Formule* : SQL `SUM(est_abandon) / COUNT(*)` ; DAX `DIVIDE(SUM(…[est_abandon]), COUNTROWS(…))`.
- *Sources* : PostgreSQL. *Fréquence* : trimestrielle.
- *Justification* : exemple du PDF ; un abandon est un CA futur perdu et un signal pédagogique.
- *Limites* : la source ne **date** pas l'abandon. Les 360 inscriptions SUSPENDU ne sont pas comptées. Le slice de la Phase 10 montre que les Licences et les Certificats abandonnent davantage.

**5. Progression moyenne — 65,59 %**
- *Définition* : moyenne des pourcentages de progression par couple (étudiant, module).
- *Formule* : SQL `AVG(pourcentage)` ; DAX `AVERAGE(fact_progression[pourcentage])`.
- *Sources* : MySQL. *Fréquence* : hebdomadaire.
- *Justification* : exemple du PDF ; mesure l'avancement réel dans les contenus.
- *Limites* : mesure **semi-additive** (on la moyenne, on ne la somme jamais). Les 3 180 valeurs hors [0, 100] neutralisées en L5 sont ignorées. C'est un instantané, sans historique.

**6. Étudiants actifs (30 jours) — 3 003**
- *Définition* : personnes distinctes ayant au moins une connexion, une note ou une activité de quiz entre le 17/08 et le 15/09/2026 (définition L3).
- *Formule* : SQL `COUNT(DISTINCT etudiant_id)` sur les trois faits ; DAX `UNION` des trois faits filtrés, puis `DISTINCT`.
- *Sources* : MySQL, MongoDB. *Fréquence* : quotidienne.
- *Justification* : exemple du PDF ; l'engagement réel, que le nombre d'inscrits ne dit pas.
- *Limites* : les événements MongoDB hors quiz (vidéos, téléchargements) ne sont pas dans le DW. La fenêtre est fixée à la date de référence de la simulation.

**7. Temps médian de connexion — 1 740 s (29 min)**
- *Définition* : médiane des durées de connexion, en secondes (définition L3).
- *Formule* : SQL `percentile_cont(0.5)` ; DAX `MEDIAN(fact_connexions[duree_secondes])`. Les deux font la moyenne des deux valeurs centrales quand le nombre est pair.
- *Sources* : MySQL. *Fréquence* : hebdomadaire.
- *Justification* : demandé par le DG ; la médiane résiste aux sessions anormalement longues.
- *Limites* : les 1 658 connexions sans déconnexion (B08) sont exclues. Le temps connecté ne mesure pas l'attention.

**8. Nombre réel d'étudiants — 10 500**
- *Définition* : personnes distinctes, soit les inscrits (PostgreSQL) et les comptes LMS sans inscription (MySQL).
- *Formule* : SQL `COUNT(DISTINCT etudiant_id)` sur les versions courantes ; DAX `DISTINCTCOUNT` filtré.
- *Sources* : PostgreSQL, MySQL. *Fréquence* : mensuelle.
- *Justification* : première question du DG ; la somme naïve des sources donnait **26 476** (L3).
- *Limites* : 1 000 inscrits sans compte LMS et 500 comptes sans inscription ne peuvent pas être rapprochés ; chacun compte pour une personne.

## 5. La satisfaction : un KPI demandé mais non calculable

Le PDF la cite, et le DG la demande (Phase 1). Pourtant, **aucune des 5 sources** ne contient d'avis, de note ni d'enquête (gap documenté en L3).

| | |
|---|---|
| **Ce qu'il ne faut pas faire** | Présenter un indicateur de substitution (taux de réussite, temps de connexion) sous le nom de « satisfaction ». Un étudiant peut réussir ses quiz et être mécontent : **ce serait tromper le décideur** |
| **Recommandation** | Collecter une note de 1 à 5 à la fin de chaque module, dans la plateforme pédagogique. Elle deviendrait la mesure d'un nouveau fait `fact_evaluations`, lié aux dimensions étudiant, module et temps, et le KPI serait calculable sans changer le reste du modèle |

Il en va de même pour « les enseignants les mieux évalués » : aucune évaluation, et aucun lien entre un cours et un enseignant (L6).

## 6. Porte G5 : le même KPI par deux chemins

| Porte | Comparaison | Statut |
|---|---|---|
| **G5a** (L7) | **SQL sur le DW** (`dw.v_kpi`) = **Python sur la couche clean** (`pipeline/kpi.py`) | ✅ **8/8** : montants au centime, effectifs exacts, ratios à 10⁻⁹ près |
| **G5b** (L8) | **DAX dans Power BI** = valeurs de référence (`data/reports/kpi_reference.json`) | À exécuter en L8 |

G5a compare deux **langages** et deux **couches**, sans code commun. Le Python ne lit pas le DW : il repart de la couche clean, refait les jointures, le rapprochement des étudiants et le calcul des frais annuels. Un écart aurait révélé une erreur de grain, de jointure ou de rattachement SCD 2. Il n'y en a aucun.

**Procédure G5b (L8).** Importer les tables `dw.*`, créer les relations, coller les mesures de `powerbi/mesures_kpi.dax`, puis comparer chaque carte, **sans aucun filtre**, à `kpi_reference.json`.

## Références

- PDF « BI Recherche P8 », Phase 11 ; Phase 1 (besoins du DG) ; L3 (définitions métier validées).
- D. Parmenter, *Key Performance Indicators*, 4ᵉ éd. (2019) : KPI, indicateurs de résultat et de performance.
- Critères SMART (G. T. Doran, 1981) : spécifique, mesurable, atteignable, réaliste, temporellement défini.
