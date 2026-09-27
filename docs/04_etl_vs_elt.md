# Phase 4 — ETL ou ELT ?

*EduSmart Decision Platform · Lot L3 · Étape 2 du module BI*

> **Demande du PDF :** répondre à 4 questions de recherche, puis préparer le TP (7 scripts : `extract_postgres.py`, `extract_mysql.py`, `extract_mongodb.py`, `extract_redis.py`, `extract_csv.py`, `transform.py`, `load.py`). Le PDF précise : *« Nous déciderons ensemble lequel faire »*.
>
> **Décision prise :** **ELT** (Étape 1, travail en solo). Ce document la justifie et **conçoit** le pipeline. Le code viendra au lot L4.

---

## 1. Qu'est-ce qu'un ETL ?

**ETL** (*Extract – Transform – Load*) désigne un processus d'intégration en trois étapes **dans cet ordre** :
1. **Extract** : lire les données dans les sources ;
2. **Transform** : les nettoyer, les convertir, les rapprocher et les agréger **dans un moteur intermédiaire** (serveur ETL, script Python, outil comme Talend ou SSIS) ;
3. **Load** : charger dans l'entrepôt des données **déjà propres et au format cible**.

```
Sources ──Extract──▶ [ Moteur ETL : nettoyage, conversion, rapprochement ] ──Load──▶ Data Warehouse (données finales)
```

La transformation a lieu **avant** l'entrepôt : l'entrepôt ne voit jamais la donnée brute.

## 2. Qu'est-ce qu'un ELT ?

**ELT** (*Extract – Load – Transform*) inverse les deux dernières étapes :
1. **Extract** : lire les données dans les sources ;
2. **Load** : les charger **telles quelles** dans une zone brute (*staging*) de l'entrepôt ;
3. **Transform** : les transformer **à l'intérieur de l'entrepôt**, avec son propre moteur (SQL), de couche en couche.

```
Sources ──Extract──▶ ──Load──▶ Data Warehouse [ brut ──SQL──▶ nettoyé ──SQL──▶ modèle final ]
```

L'ELT s'est généralisé avec les entrepôts puissants et bon marché (entrepôts cloud, PostgreSQL moderne) et des outils comme dbt.

## 3. Quelles différences ?

| Critère | ETL | ELT |
|---|---|---|
| Lieu de la transformation | Moteur intermédiaire, hors entrepôt | **Dans** l'entrepôt (SQL) |
| Données brutes dans l'entrepôt | Non | **Oui** (zone *staging*) |
| Rejouer une transformation | Il faut réextraire les sources | On **relance le SQL** sur le brut déjà chargé |
| Traçabilité, audit | Le brut est perdu, sauf archivage séparé | Brut conservé : on peut **prouver** chaque correction |
| Puissance nécessaire | Dans le moteur ETL | Dans l'entrepôt |
| Délai de disponibilité | Données finales seulement | Brut disponible tout de suite, raffiné ensuite |
| Données personnelles | Peuvent être **masquées avant** chargement | Arrivent **en clair** dans le *staging* : à protéger |
| Espace de stockage | Faible (données finales) | Plus élevé (brut + nettoyé + final) |
| Langage des transformations | Python, Java, outil graphique | Principalement **SQL** |
| Schéma cible | Doit être fixé avant | Le brut peut être chargé sans schéma final |

## 4. Dans quels cas choisir l'un ou l'autre ?

**Choisir l'ETL quand :**
- des données sensibles doivent être **masquées ou filtrées avant** d'entrer dans l'entrepôt (conformité) ;
- l'entrepôt cible a une **puissance de calcul limitée** ou coûteuse ;
- les transformations sont **très complexes** et mieux exprimées en code procédural qu'en SQL ;
- l'organisation dispose déjà d'un **outil ETL** et des compétences associées ;
- on veut limiter le stockage (pas de copie brute).

**Choisir l'ELT quand :**
- l'entrepôt est **puissant** et sait transformer en SQL ;
- on veut **garder le brut** pour l'audit, la reprise et l'amélioration des règles ;
- les sources sont **hétérogènes** ou ont des **schémas variables** : on charge d'abord, on interprète ensuite ;
- les règles de transformation vont **évoluer** (les définitions métier de la Phase 2 ne sont pas encore validées) ;
- l'équipe maîtrise bien le **SQL**.

En pratique, beaucoup de pipelines sont **hybrides**, ce qu'on appelle **EtLT** : une petite transformation *technique* au chargement (décoder un encodage, aplatir un document), puis les transformations *métier* dans l'entrepôt.

---

## 5. La décision pour EduSmart : ELT

### 5.1 Arguments retenus

| Argument | Constat EduSmart |
|---|---|
| **Traçabilité et contrôle qualité** (Phases 5, 6, 15) | Le PDF demande de compter les lignes extraites, **rejetées**, les doublons et les **corrections**. Il faut donc garder le brut dans l'entrepôt pour prouver chaque correction : les 160 080 anomalies doivent pouvoir être retrouvées **avant** et **après** traitement |
| **Des règles métier encore ouvertes** (Phase 2) | Faut-il exclure ou corriger les 1 650 paiements négatifs ? Quelle définition de la réussite ? En ELT, changer de règle revient à **relancer le SQL**, sans réextraire |
| **Sources hétérogènes, schéma flexible** | MongoDB : documents aux champs variables et horodatages de 3 types. Ils se chargent tels quels en `JSONB` et s'interprètent ensuite en SQL |
| **Sources volatiles** | Redis change à chaque instant : il faut **figer le snapshot** en *staging* dès l'extraction |
| **Moteur disponible** | PostgreSQL 15 : SQL analytique, `JSONB`, expressions régulières, fonctions |
| **Architecture en couches** (Phase 3) | Les couches bronze / argent / or sont la mise en œuvre naturelle de l'ELT |

### 5.2 Une nuance à la justification initiale

La justification initiale invoquait aussi *« les volumes MongoDB/Redis importants »* et *« un contexte Big Data / Data Lakehouse »*. Les mesures du volet A **nuancent ce point** :
- MongoDB compte 297 601 documents (16 Mo compressés) ;
- Redis compte 4 608 clés ;
- l'ensemble représente environ 800 000 enregistrements.

Ce n'est pas du Big Data, et l'architecture n'est pas un vrai Lakehouse (Phase 3, § 6.4). **La décision ELT reste la bonne**, mais pour les raisons du § 5.1 (traçabilité, hétérogénéité, règles évolutives), **pas pour une raison de volume**. C'est plus solide à défendre en soutenance.

### 5.3 Contrepartie à gérer : les données personnelles en *staging*

En ELT, les téléphones, adresses, adresses IP et **salaires** arrivent **en clair** dans le schéma `staging`.

Mesures prévues :
- droits d'accès restreints aux schémas `staging` et `clean` : Power BI ne lit **que** le schéma `dw` (et les vues des data marts, Phase 3 § 6.2) ;
- aucune donnée personnelle superflue dans les dimensions (pas d'adresse IP, pas de téléphone) ;
- purge possible des lots anciens de *staging*.

### 5.4 Forme retenue : EtLT

Le « t » minuscule ne désigne que des **conversions techniques, sans règle métier** :

| Au chargement (technique, en Python) | Dans l'entrepôt (métier, en SQL) |
|---|---|
| Décoder l'encodage déclaré (ISO-8859-1 → UTF-8) | Standardiser les villes, modes de paiement, catégories |
| Lire le séparateur `;` ou `,` | Lire les 3 formats de date |
| Sérialiser un document MongoDB en `JSONB` sans perdre le type (date, texte, nombre) | Dédoublonner, rattacher, rejeter |
| Figer un snapshot Redis (clé, type, valeur, TTL) | Rapprocher les identifiants (`mapping_*`) |
| Ajouter les colonnes techniques (`_batch_id`, `_source`…) | Construire les dimensions et les faits, SCD2 |

**Aucune valeur n'est corrigée avant d'entrer dans l'entrepôt.** Toute correction est faite, et donc tracée, en SQL.

---

## 6. Conception du pipeline (préparation du lot L4)

### 6.1 Enchaînement

```
run_pipeline.py  (un lot = un batch_id)
 │
 ├─ 1. extract_postgres.py ─┐
 ├─ 1. extract_mysql.py    ─┤   lisent les sources, n'y écrivent JAMAIS
 ├─ 1. extract_csv.py      ─┼─▶ data/landing/<batch_id>/<source>/…   (fichiers bruts du lot)
 ├─ 1. extract_mongodb.py  ─┤
 ├─ 1. extract_redis.py    ─┘
 │
 ├─ 2. load.py        ─▶ edusmart_dw.staging.*   (COPY, tout en TEXT / JSONB + colonnes techniques)
 │
 ├─ 3. transform.py   ─▶ SQL : staging ─▶ clean ─▶ dw     (+ quality.* : rejets et rapport)
 │
 └─ à chaque étape : meta.etl_execution_log (source, date, durée, lignes, erreurs, statut)
```

**Pourquoi une zone d'atterrissage (*landing*) sur disque entre l'extraction et le chargement ?**
- l'extraction et le chargement se **testent séparément** (Phase 15 : « toutes les lignes ont-elles été extraites ? chargées ? ») ;
- en cas d'échec du chargement, on **recharge sans réinterroger** les sources ;
- le lot est **archivé**, ce qui est utile pour l'audit.

### 6.2 Rôle de chaque script

| Script | Lit | Produit | Particularités |
|---|---|---|---|
| `extract_postgres.py` | 5 tables de `edusmart_academic` | 5 fichiers CSV | `COPY … TO STDOUT` : rapide et fidèle |
| `extract_mysql.py` | 6 tables de `edusmart_learning` | 6 fichiers CSV | Lecture par lots (300 000 notes) ; le NULL reste un NULL |
| `extract_csv.py` | 4 fichiers RH | 4 fichiers UTF-8 | Encodage et séparateur **déclarés** (`SCHEMAS`) ; contrôle de l'en-tête ; **aucune** conversion de valeur |
| `extract_mongodb.py` | Collection `events` | 1 fichier JSON Lines | JSON étendu : un horodatage texte reste texte, un nombre reste nombre |
| `extract_redis.py` | Toutes les clés (SCAN) | 1 fichier JSON Lines | Clé, type, valeur, TTL et **instant d'extraction** : le snapshot est figé |
| `load.py` | Les fichiers du lot | Tables `staging.*` | Idempotent (le lot est remplacé s'il est rechargé) ; compte les lignes |
| `transform.py` | `staging.*` + `mappings/` | `clean.*`, `dw.*`, `quality.*` | Scripts SQL ordonnés ; rejets tracés ; rapport qualité |
| `run_pipeline.py` | — | Un lot complet | Orchestration, `batch_id`, arrêt propre en cas d'erreur |

### 6.3 Couche *staging* (bronze) : principes

- **Une table par table ou collection source**, avec un préfixe par source : `stg_pg_paiements`, `stg_mysql_notes`, `stg_csv_salaires`, `stg_mongo_events`, `stg_redis_keys`.
- **Toutes les colonnes en `TEXT`** : un montant négatif, une date `12/09/2026` ou un sexe `Garçon` sont chargés **sans erreur**, puisque rien n'est encore interprété.
- **MongoDB** : le document entier est stocké en `JSONB`, ainsi que `event_id` pour l'indexation.
- **Redis** : une ligne par clé (`cle`, `type`, `valeur JSONB`, `ttl`).
- **Colonnes techniques** sur chaque ligne :
  - `_batch_id` ;
  - `_source` ;
  - `_extracted_at` ;
  - `_row_number` (position dans l'extraction).

### 6.4 Pièges d'intégration identifiés au volet A

C'est l'apport principal du volet A : ces pièges sont **connus avant d'écrire la première ligne d'ETL**.

| Source | Piège | Traitement prévu |
|---|---|---|
| Toutes | Identifiants incompatibles (`id_etudiant` ≠ `student_code`) | Rapprochement par `mapping_etudiants.csv` (9 000 paires) ; les 1 500 non rapprochés sont **conservés et signalés** |
| MySQL, MongoDB, Redis | `student_code` mal formés (`lms-000154`, `LMS-154`) | Normalisation, puis **contrôle** dans le référentiel des comptes LMS |
| MongoDB, Redis | Codes `COURSE-n` et `QUIZ-n` sans colonne MySQL correspondante | Rapprochement par `mapping_courses.csv` ; les **89 codes** absents sont signalés |
| MySQL | Collation insensible à la casse : `GROUP BY` fusionne `Data` et `DATA` | Extraction de la valeur **exacte** ; standardisation dans l'entrepôt (PostgreSQL est sensible à la casse) |
| MySQL | `NULL` écrit `\N` dans les fichiers | Gestion explicite dans l'extraction |
| CSV RH | ISO-8859-1 et `;` pour salaires et absences | Encodage et séparateur déclarés (`SCHEMAS`), jamais devinés |
| CSV RH | 3 formats de date ; `03-04-2024` ambigu | Convention : `/` signifie JJ/MM/AAAA, `-` avec l'année en fin signifie MM-JJ-AAAA (`parse_date` du volet A, à traduire en SQL) |
| CSV RH | Mois en toutes lettres, parfois mal écrits (`Fevrier`, `03`, `Sept.`) | Table de correspondance des mois |
| MongoDB | Horodatage de 3 types (date, texte, nombre) | Types conservés en `JSONB` ; conversion en SQL selon le type |
| MongoDB | Schéma flexible (un LOGIN sans `quiz_code` est **normal**) | Ne pas confondre champ absent par conception et anomalie D02 |
| MongoDB, Redis | `device` = modèle (MongoDB) ou plateforme (Redis) | Deux attributs distincts : `modele_appareil` et `plateforme` |
| MySQL, MongoDB | Durées en minutes et en secondes | Conversion en **secondes** partout |
| Redis | Données temporaires, TTL | Extraction juste après `insert_data` ; instant d'extraction enregistré |
| PostgreSQL, MongoDB | Paiements présents deux fois | PostgreSQL = référence du CA ; MongoDB = rapprochement seulement |

### 6.5 Critères de validation du lot L4 (porte G2, rappel de l'Étape 2)

- Pour chaque source : **lignes extraites = lignes en *staging*** (compte exact, par table).
- **Une ligne `meta.etl_execution_log` par source et par exécution** (source, date, durée, lignes, erreurs, statut).
- **Idempotence** : relancer le même lot ne duplique rien.
- **Aucune modification** des sources, et aucune valeur corrigée avant le *staging*.

---

## Synthèse

| Question | Réponse courte |
|---|---|
| ETL ? | Transformer **avant** de charger, dans un moteur intermédiaire |
| ELT ? | Charger **brut**, puis transformer **dans** l'entrepôt |
| Différence clé | L'endroit de la transformation, donc la **conservation du brut** |
| Pour EduSmart | **ELT (forme EtLT)**, pour la traçabilité, l'hétérogénéité et des règles métier encore ouvertes, et non pour le volume |
| Point de vigilance | Données personnelles en clair dans le *staging* : accès restreint |

## Références

- PDF « BI Recherche P8 », Phase 4 (questions 1 à 4 et TP) ; Phases 5, 6 et 15 (qualité, métadonnées, tests).
- Décisions validées : Étape 1 (ELT), Étape 2 (architecture, lots L4 et L5, porte G2).
- R. Kimball et J. Caserta, *The Data Warehouse ETL Toolkit* (2004).
- Pièges d'intégration : README des 5 sources du volet A (`sources/s*/README.md`).
