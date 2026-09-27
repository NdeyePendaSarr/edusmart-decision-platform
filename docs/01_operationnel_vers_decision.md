# Phase 1 — De la donnée opérationnelle à la décision

*EduSmart Decision Platform · Lot L3 · Étape 1 du module BI*

> **Objectif du PDF :** comprendre pourquoi les entreprises mettent en place des systèmes décisionnels.
>
> **Méthode :** chaque question de recherche est traitée en deux temps. D'abord la notion générale, puis son **illustration sur les 5 sources réellement construites** (volet A).
> Tous les chiffres cités sont recalculés par `python -m scripts.constats_sources`. Ce sont des calculs **exploratoires** avec des règles simples ; les valeurs officielles viendront du Data Warehouse.

---

## Partie A — Comprendre les données opérationnelles

### 1. Qu'appelle-t-on une donnée opérationnelle ?

Une **donnée opérationnelle** est produite et utilisée par l'activité quotidienne de l'organisation : elle enregistre une **transaction** ou un **état courant**, au moment où il se produit, pour faire fonctionner un service.

Ses caractéristiques :
- **granulaire** : une ligne représente un fait élémentaire (un paiement, une connexion) ;
- **actuelle** : elle reflète l'état présent, et l'historique n'est pas toujours conservé ;
- **volatile** : elle est modifiée ou supprimée au fil des opérations ;
- **structurée pour le traitement**, et non pour l'analyse.

**Chez EduSmart**, chaque source en produit :

| Source | Exemple de donnée opérationnelle | Ce qu'elle permet de faire |
|---|---|---|
| PostgreSQL | un paiement `PAY-2025-013460` de 700 000 XOF par Wave | encaisser une tranche de scolarité |
| MySQL | une note de 14,5/20 à la tentative 2 d'un quiz | valider un quiz, débloquer la suite du cours |
| CSV RH | le salaire d'octobre 2025 d'un enseignant | payer les enseignants |
| MongoDB | un événement `VIDEO_STARTED` en 720p sur un Tecno Spark 10 | journaliser l'usage de l'application |
| Redis | `session:{id}` avec `status = ONLINE` | savoir qui est connecté *maintenant* |

La donnée Redis est l'exemple extrême de la volatilité : elle n'existe que le temps d'une session (TTL de 24 h), et **la ville d'un étudiant n'est conservée nulle part avec son historique**. PostgreSQL ne garde que la ville actuelle. C'est précisément le problème traité en Phase 9 (SCD).

### 2. Qu'est-ce qu'une base OLTP ?

Une base **OLTP** (*Online Transaction Processing*) est conçue pour exécuter un **grand nombre de petites transactions** (insertion, mise à jour, lecture d'une ligne), avec des garanties d'intégrité fortes.

Ses caractéristiques techniques :
- **transactions ACID** : atomicité, cohérence, isolation, durabilité ;
- **modèle normalisé** (3ᵉ forme normale) : chaque information à un seul endroit, pour éviter les anomalies de mise à jour ;
- **index sur les clés primaires**, pour accéder vite à *une* ligne ;
- **nombreux utilisateurs simultanés**, avec un temps de réponse de l'ordre de la milliseconde.

**Chez EduSmart**, `edusmart_academic` (PostgreSQL) est une base OLTP typique : 5 tables normalisées reliées par des clés étrangères (`filieres → classes → inscriptions ← etudiants`, puis `inscriptions → paiements`).

Pour savoir *« combien a payé la filière IA en 2024-2025 ? »*, il faut joindre 4 tables et agréger 40 150 paiements. Une base OLTP le permet, mais **ce n'est pas pour cela qu'elle est optimisée**.

MongoDB et Redis ne sont pas des SGBD relationnels, mais ils jouent aussi un **rôle opérationnel** : journaliser (MongoDB) et servir le temps réel (Redis).

### 3. Pourquoi une entreprise possède-t-elle plusieurs bases de données ?

Il y a trois raisons principales.
1. **Chaque besoin a sa technologie.** Chez EduSmart :
   - des transactions financières fiables → **PostgreSQL** ;
   - une plateforme web classique → **MySQL** ;
   - des journaux volumineux au schéma variable → **MongoDB** ;
   - un accès en quelques microsecondes → **Redis** ;
   - aucun outil au service RH → **des fichiers CSV**.
2. **L'histoire de l'organisation.** Le document de cadrage le dit : *« Au fil des années, plusieurs applications ont été développées. Chaque application possède sa propre base de données. »* On ajoute des applications ; on refond rarement l'existant.
3. **L'isolement des risques et des charges.** Une panne ou un pic de charge sur la plateforme de cours ne doit pas bloquer les encaissements.

### 4. Pourquoi chaque service possède-t-il souvent son propre système d'information ?

Parce que chaque service a ses **propres processus, son vocabulaire, ses priorités, son budget et ses prestataires**.
- La **scolarité** pense en *matricules*, *inscriptions* et *tranches*.
- La **pédagogie** pense en *comptes LMS*, *modules* et *quiz*.
- Les **RH** pensent en *codes enseignants*, *mois de paie* et *absences*.

Chez EduSmart, les RH n'ont même pas de base : ils exportent des fichiers. Chaque service choisit l'outil adapté à **son** métier, sans penser à la consolidation.

### 5. Quels sont les avantages de cette organisation ?

| Avantage | Illustration EduSmart |
|---|---|
| Outil adapté à chaque métier | Le schéma flexible de MongoDB accepte des événements aux champs différents (un LOGIN n'a pas de `quiz_code`) |
| Performance locale | Redis répond instantanément au nombre de connectés |
| Autonomie des services | Les RH exportent leurs fichiers sans dépendre de l'informatique |
| Isolement des pannes | Une panne de MySQL n'empêche pas d'encaisser dans PostgreSQL |
| Évolution indépendante | L'application mobile passe de la version 2.0.0 à la 2.4.1 sans toucher aux autres systèmes |

Ces avantages ont un coût : **l'information de l'entreprise est éclatée**. C'est l'objet de la partie B.

---

## Partie B — Les limites des systèmes opérationnels

### 6. Quels problèmes rencontre-t-on lorsque les données sont réparties dans plusieurs systèmes ?

| Problème | Constat mesuré sur les sources EduSmart |
|---|---|
| **Identifiants incompatibles** | PostgreSQL identifie par `id_etudiant` (UUID) et `matricule` ; MySQL, MongoDB et Redis par `student_code` (`LMS-XXXXXX`). **Aucune colonne commune.** |
| **Hétérogénéité technique** | 4 technologies (SQL relationnel, documents JSON, clés-valeurs) + des fichiers ; 2 encodages (UTF-8, ISO-8859-1) ; 2 séparateurs CSV |
| **Formats différents** | Dates en 3 formats dans les CSV RH ; horodatages MongoDB stockés en date (291 289), en texte (4 739) **et** en nombre (1 573) |
| **Référentiels incohérents** | **171 écritures de villes différentes** dans PostgreSQL pour 49 villes réelles ; 8 valeurs pour le sexe (`M`, `F`, `Homme`, `Garçon`, `1`, `0`…) ; 19 écritures de modes de paiement |
| **Même mot, sens différent** | `device` vaut `Android` dans Redis mais `Samsung Galaxy A54` dans MongoDB |
| **Unités différentes** | Durée de connexion en **minutes** (MySQL), en **secondes** (MongoDB), sous forme d'horodatages (Redis) |
| **Temporalités différentes** | Redis ne connaît que l'instant présent ; PostgreSQL remonte à juin 2023 |
| **Pièges techniques** | La collation MySQL `utf8mb4_unicode_ci` fusionne `Data`, `DATA` et `data` dans un `GROUP BY` et **cache** l'anomalie |

### 7. Pourquoi les identifiants peuvent-ils être différents d'une base à l'autre ?

- **Chaque système génère ses propres clés** au moment où il crée l'objet. La scolarité crée le matricule à l'inscription ; la plateforme crée le compte LMS à la première connexion.
- **Les systèmes ont été conçus à des époques différentes, par des équipes différentes**, sans référentiel commun.
- **La consigne de conception l'impose parfois.** Le PDF MySQL écrit : *« Ne pas utiliser id_etudiant de PostgreSQL. Utiliser student_code ».*
- **Tout le monde n'existe pas partout** :
  - 1 000 étudiants inscrits n'ont **jamais** activé leur compte LMS ;
  - 500 comptes LMS n'ont **aucune** inscription (auditeurs libres, comptes de test, anciens étudiants).

Conséquence : le lien entre les systèmes n'existe que dans une **table de correspondance** (`mapping_etudiants.csv`, 9 000 paires). Les 1 500 cas restants ne peuvent pas être rapprochés automatiquement.

S'y ajoutent les **erreurs de saisie des identifiants eux-mêmes** : `lms-000154`, `LMS000154` ou `LMS-154` au lieu de `LMS-000154` (7 721 notes MySQL). Résultat : MySQL contient **16 476 codes étudiants distincts pour 9 500 comptes réels**.

### 8. Pourquoi une même information peut-elle être présente plusieurs fois ?

- **Redondance voulue entre systèmes.** Un paiement Wave fait depuis le téléphone existe dans PostgreSQL (la transaction) **et** dans MongoDB (l'événement `PAYMENT_SUCCESS`, même référence `PAY-…`). La progression existe dans MySQL **et** dans Redis (le PDF prévoit qu'elle transite par Redis).
- **Doublons techniques :**
  - un export RH lancé deux fois (189 lignes de salaires strictement identiques) ;
  - un événement journalisé deux fois (12 164 dans MongoDB) ;
  - une inscription saisie deux fois (366).
- **Doublons de saisie :** le même département écrit « Data », « Développement Data » et « Data Engineering ».

### 9. Quels risques cela représente-t-il pour les décideurs ?

Un décideur qui interrogerait directement les sources obtiendrait des **chiffres faux, contradictoires ou impossibles à justifier** :

| Question du DG | Calcul naïf | Calcul avec des règles simples | Écart |
|---|---|---|---|
| Combien d'étudiants ? | 10 000 (PostgreSQL) + 16 476 (MySQL) = **26 476** | **10 500 personnes** (10 000 inscrits + 500 comptes LMS sans inscription) | ×2,5 |
| Chiffre d'affaires ? | somme de toutes les lignes : **14,19 Mds XOF** | paiements VALIDE rattachés à une inscription : **12,91 Mds XOF** | +9,9 % |
| CA vu par l'application ? | somme des `PAYMENT_SUCCESS` de MongoDB : **5,14 Mds XOF** | ce n'est qu'une partie des paiements (mobile money via l'application) | −60 % |
| Temps moyen de connexion ? | **34,6 min** (MySQL, durées négatives comprises) | **37,7 min** sans les 2 453 durées négatives ; 29,3 min selon les sessions MongoDB | selon la source et la règle |
| Formation la plus suivie ? | « Génie Logiciel » (1 983 inscriptions) | **Intelligence Artificielle (2 561)**, une fois réunis les libellés « IA », « Ingénierie IA » et « Intelligence Artificielle » | **le classement s'inverse** |

Les risques qui en découlent :
- **décisions erronées** : investir dans la mauvaise filière ;
- **perte de confiance** : deux directeurs arrivent en réunion avec deux chiffres différents ;
- **temps perdu** à réconcilier à la main ;
- **absence de traçabilité** : impossible de dire d'où vient un chiffre ;
- **risque réglementaire** sur les données financières.

Le cas du CA illustre bien le danger : 1 650 paiements VALIDE rattachés sont **négatifs** (une erreur de signe). Faut-il les exclure, les corriger en valeur absolue (14,20 Mds) ou les signaler ? **C'est une décision métier**, pas technique (Phase 2).

---

## Partie C — Les besoins métier

### 10. Quelles informations un Directeur Général souhaite-t-il consulter quotidiennement ?

Un DG pilote la **santé globale** de l'organisation. Il suit :
- des **indicateurs de résultat** : chiffre d'affaires, encaissements du jour, nombre d'étudiants actifs, taux de réussite ;
- des **indicateurs de risque** : abandons, impayés, baisse d'activité sur la plateforme ;
- des **tendances** : évolution par rapport à la veille, au mois ou à l'année précédente ;
- des **alertes** : écart à un objectif, anomalie.

Le cas pratique du PDF liste 7 informations. Elles sont analysées au point 11 et dans le cas pratique.

### 11. Ces informations existent-elles dans une seule base ?

**Non.** Aucune des 7 informations demandées ne peut être produite de façon fiable à partir d'une seule source, et **deux n'existent nulle part** :

| Information demandée | Sources | Une seule suffit ? |
|---|---|---|
| Nombre réel d'étudiants | PostgreSQL + MySQL (+ MongoDB, Redis) + correspondance | ❌ Il faut réunir les inscrits et les comptes LMS |
| Chiffre d'affaires | PostgreSQL (référence), MongoDB (rapprochement) | ⚠️ PostgreSQL suffit, mais il doit être nettoyé |
| Taux de réussite | MySQL (quiz) | ⚠️ Au niveau du **quiz** seulement : aucun diplôme ni examen final n'est enregistré |
| Satisfaction des étudiants | — | ❌ **Aucune source** |
| Formations les plus suivies | PostgreSQL (filières), MySQL (modules), MongoDB (consultations) | ⚠️ Trois définitions possibles |
| Temps moyen de connexion | MySQL, MongoDB, Redis | ⚠️ Trois mesures, deux unités |
| Enseignants les mieux évalués | — | ❌ **Aucune source** : ni évaluation, ni lien enseignant ↔ cours |

### 12. Pourquoi un directeur ne consulte-t-il jamais directement les bases opérationnelles ?

1. **Performance.** Une requête d'agrégation sur 300 000 notes ou 300 000 événements ralentit la base qui sert les étudiants.
2. **Complexité.** Il faut connaître 4 langages ou API (SQL PostgreSQL, SQL MySQL, requêtes MongoDB, commandes Redis), 24 tables, fichiers ou structures et leurs pièges (collation, encodage, formats de date).
3. **Données non fiables en l'état.** Voir le tableau du point 9.
4. **Absence d'historique.** Redis ne sait rien d'hier ; PostgreSQL ne garde pas l'ancienne ville d'un étudiant.
5. **Sécurité et confidentialité.** Les bases contiennent des téléphones, des adresses, des salaires et des adresses IP. On ne donne pas un accès direct à la production.
6. **Absence de langage commun.** « Étudiant actif » ne signifie rien pour une base : il faut une **définition métier partagée**.

---

## Partie D — Introduction à la BI

### 13. Qu'est-ce que la Business Intelligence ?

La **Business Intelligence** (informatique décisionnelle) est l'ensemble des **méthodes, processus, architectures et outils** qui transforment des données brutes, dispersées et hétérogènes en **informations fiables, partagées et exploitables pour la décision**.

Elle couvre toute la chaîne que suit ce projet :

```
Sources opérationnelles → Intégration (ETL/ELT) → Qualité & métadonnées → Entrepôt (DW)
   → Modèle multidimensionnel → Analyse (OLAP, KPI) → Restitution (Power BI) → Décision
```

### 14. Quels sont ses objectifs ?

| Objectif | Traduction EduSmart |
|---|---|
| **Consolider** les données dispersées | Réunir 5 sources sous une vue « étudiant » unique |
| **Fiabiliser** : une seule version de la vérité | Un seul chiffre d'affaires, défini et documenté |
| **Historiser** | Suivre les déménagements, l'évolution des effectifs par année académique |
| **Analyser** selon plusieurs axes | CA par région, filière, mode de paiement et mois |
| **Mesurer** la performance avec des KPI | Taux de réussite, taux d'abandon, étudiants actifs |
| **Diffuser** l'information au bon niveau | Tableau de bord du DG, vues détaillées pour la pédagogie et la finance |
| **Tracer** l'origine de chaque chiffre | Métadonnées et journal d'exécution (Phase 6) |
| **Révéler** ce que les données ne disent pas | Gaps : satisfaction, évaluation et activité des enseignants |

### 15. Quelle différence entre une base opérationnelle et un système décisionnel ?

| Critère | Base opérationnelle (OLTP) | Système décisionnel (OLAP / DW) |
|---|---|---|
| Finalité | Faire fonctionner l'activité | Comprendre et piloter l'activité |
| Utilisateurs | Nombreux (étudiants, agents) | Peu nombreux (décideurs, analystes) |
| Opérations | Insertions, mises à jour, lecture d'une ligne | Lectures massives, agrégations |
| Modèle | Normalisé (3FN) | Dénormalisé (étoile, constellation) |
| Données | Courantes, détaillées, modifiables | Historisées, intégrées, non volatiles |
| Périmètre | Une application | Toute l'organisation |
| Qualité | Celle de la saisie | Contrôlée, nettoyée, documentée |
| Temps de réponse | Millisecondes par transaction | Secondes pour une analyse complexe |
| Exemple EduSmart | `edusmart_academic.paiements` | `dw.fact_paiements` × `dim_temps` × `dim_region` |

La définition de référence d'un entrepôt de données (W. H. Inmon) résume la différence : une collection de données **orientées sujet, intégrées, historisées et non volatiles**, destinée à l'aide à la décision.

### 16. Pourquoi la BI est-elle indispensable aujourd'hui ?

- **Le volume et la variété des données explosent.** Même une structure de taille moyenne comme EduSmart produit près de **800 000 enregistrements** (799 130) dans 4 technologies et des fichiers, en 3 ans.
- **La concurrence impose des décisions rapides et fondées** : quelle filière ouvrir, quel module refondre, quand relancer un impayé.
- **La décision « à l'intuition » coûte cher.** L'inversion du classement des formations (point 9) le montre.
- **Les exigences de traçabilité** (financière, pédagogique) imposent de justifier chaque chiffre.
- **Les outils sont devenus accessibles** (Power BI, bases open source), mais ils n'ont de valeur que sur des **données intégrées et fiables**.

---

## Cas pratique EduSmart

### Où se trouvent ces données ?

| Information du DG | PostgreSQL | MySQL | CSV RH | MongoDB | Redis |
|---|:-:|:-:|:-:|:-:|:-:|
| Nombre réel d'étudiants | ● inscrits | ● comptes LMS | | ○ | ○ |
| Chiffre d'affaires | ● paiements | | | ○ `PAYMENT_*` | ○ notifications |
| Taux de réussite | ○ statut DIPLOME | ● `notes.valide` | | ○ `QUIZ_SUBMITTED` | |
| Satisfaction | | | | | |
| Formations les plus suivies | ● inscriptions | ● progression | | ○ `COURSE_OPENED` | |
| Temps moyen de connexion | | ● `temps_connexion` | | ● sessions | ○ `session:*` |
| Enseignants les mieux évalués | ○ `classes.responsable` (nom) | | ○ `enseignants.csv` | | |

● source principale · ○ source partielle ou de rapprochement

### Une seule source suffit-elle ?

**Non**, pour les raisons développées aux points 9 et 11. Même le chiffre d'affaires, présent dans une seule base, n'est pas utilisable tel quel.

### Peut-on construire directement un tableau de bord sur les cinq sources ?

**Techniquement, en partie** : Power BI sait se connecter à PostgreSQL, MySQL et à des fichiers CSV (MongoDB et Redis demandent des connecteurs particuliers). **Mais ce serait une erreur** :
- Power BI devrait **refaire le rapprochement** étudiant ↔ compte LMS à chaque actualisation ;
- les **règles de nettoyage** (171 villes, 19 modes de paiement, 8 écritures du sexe) seraient enfouies dans des requêtes Power Query, impossibles à tester et à tracer ;
- les **bases de production** seraient interrogées en direct ;
- **Redis serait vide ou différent** à chaque actualisation, car ses données sont temporaires ;
- **aucun historique** ne serait constitué ;
- chaque rapport risquerait de **calculer différemment** le même indicateur.

### Quels problèmes rencontrera-t-on ?

Ce sont les constats de la partie B, résumés en quatre familles :
1. **Intégration** : identifiants sans clé commune, codes de contenus non résolubles (89 codes MongoDB absents de `mapping_courses.csv`), même nom de champ au sens différent.
2. **Qualité** : de 7 à 19 types d'anomalies selon la source, soit **160 080 anomalies journalisées au total**.
3. **Technique** : encodages, séparateurs, formats de dates, types mixtes MongoDB, collation MySQL, données Redis temporaires.
4. **Sémantique** : pas de définition partagée de l'« étudiant actif », de la « réussite » ou de l'« abandon », et des indicateurs sans aucune donnée (satisfaction, évaluation et activité des enseignants).

### Quelle solution proposeriez-vous ?

**Un système décisionnel en quatre briques**, détaillé en Phases 3 et 4 :
1. un **pipeline d'intégration** qui extrait les 5 sources, les charge **brutes** puis les transforme (**ELT**, Phase 4) ;
2. un **contrôle qualité** et des **métadonnées** à chaque exécution (Phases 5 et 6) ;
3. un **entrepôt de données PostgreSQL** organisé en couches (brut → nettoyé → modèle en constellation), historisé (Phases 3, 7, 8 et 9) ;
4. une **restitution Power BI** fondée sur des **KPI définis avec le métier** (Phases 11 à 14).

Et, **avant toute technique, un travail de définition avec le métier** (Phase 2) : quel « chiffre d'affaires », quel « étudiant actif », quelle « réussite ».

---

## Synthèse

| Idée clé | Preuve EduSmart |
|---|---|
| Les données opérationnelles servent à *faire*, pas à *décider* | 5 sources, 4 technologies, chacune optimisée pour son métier |
| La dispersion fausse les chiffres | 26 476 « étudiants » pour 10 500 personnes réelles |
| La qualité change les décisions | Le classement des formations s'inverse après standardisation |
| Certains besoins n'ont aucune donnée | Satisfaction, évaluation des enseignants : des gaps à remonter au DG |
| La BI apporte une version unique, historisée et traçable de la vérité | Objet des phases 3 à 18 |

## Références

- PDF « BI Recherche P8 », Phase 1 (questions 1 à 16 et cas pratique) ; « Données EduSmart » (cadrage).
- W. H. Inmon, *Building the Data Warehouse* (1992) : définition de l'entrepôt de données.
- R. Kimball et M. Ross, *The Data Warehouse Toolkit* : modélisation dimensionnelle.
- Chiffres : `python -m scripts.constats_sources`, à partir des sources du volet A (graine 2026).
