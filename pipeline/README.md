# Pipeline ELT — Lot L4 : extraction, chargement en staging, porte G2

Mise en œuvre de la Phase 4 (TP) et d'une partie de la Phase 6 (métadonnées).
La conception est détaillée dans [`docs/04_etl_vs_elt.md`](../docs/04_etl_vs_elt.md).

## 1. Fichiers

| Fichier | Rôle |
|---|---|
| `registry.py` | **Registre des 17 objets** (5 PG + 6 MySQL + 4 CSV + MongoDB + Redis) : colonnes reprises du volet A, table de staging, clé d'ordre. Génère le DDL du staging |
| `extract_postgres.py` | 5 tables, **une transaction en lecture seule** (REPEATABLE READ), valeurs converties en texte par PostgreSQL, curseur serveur |
| `extract_mysql.py` | 6 tables, `START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY`, `CAST(… AS CHAR)`, lecture en flux |
| `extract_csv.py` | 4 fichiers RH, encodage et séparateur **déclarés** ; en-tête et nombre de champs contrôlés ; aucune valeur modifiée |
| `extract_mongodb.py` | Collection `events`, chaque document **entier** en JSON étendu (types conservés : date, texte, nombre) |
| `extract_redis.py` | Toutes les clés : type, valeur (JSON), TTL ; snapshot figé à l'instant du lot |
| `extract_common.py` | Écriture en zone d'atterrissage, manifeste, journal (commun aux 5 extracteurs) |
| `landing.py` | Lot (`batch_id`), fichiers `data/landing/<lot>/…`, manifeste, empreinte MD5 |
| `load.py` | `TRUNCATE` + `COPY` par table (une transaction par table), contrôle du nombre de lignes |
| `meta.py` | `meta.metadata_sources` (catalogue des 17 objets) et `meta.etl_execution_log` (une ligne par étape et par objet) |
| `verify_g2.py` | **Porte G2** : 5 contrôles par objet + rapport Markdown |
| `run_pipeline.py` | Orchestration : initialisation → EXTRACT → LOAD → VERIFY |
| `sql/meta/01_meta_tables.sql` | DDL des métadonnées (Phase 6) |
| `sql/staging/01_staging_tables.sql` | DDL des 17 tables de staging (**généré** par `python -m pipeline.registry`) |

## 2. Exécution

```powershell
python -m sources.s5_redis.insert_data        # régénère le snapshot Redis (TTL 24 h) juste avant
python -m pipeline.run_pipeline               # 5 sources : EXTRACT, LOAD, VERIFY (~1 min)
```

Options :

```powershell
python -m pipeline.run_pipeline --sources s3_csv s5_redis      # certaines sources seulement
python -m pipeline.run_pipeline --steps load verify            # recharge le DERNIER lot, sans réextraire
```

Chaque étape reste utilisable seule, par exemple `python -m pipeline.extract_csv`, `python -m pipeline.load` ou `python -m pipeline.verify_g2`.

## 3. Principes

| Principe | Mise en œuvre |
|---|---|
| **Lecture seule des sources** | Transactions `READ ONLY` (PostgreSQL, MySQL) ; les sources ne sont jamais modifiées |
| **Instantané cohérent** | Toutes les tables d'une source sont lues au même instant logique |
| **Aucune correction avant le staging** | Valeurs source en `TEXT` / `JSONB` ; un montant négatif ou une date `12/09/2026` se chargent tels quels |
| **Un format d'atterrissage unique** | CSV UTF-8, `NULL` écrit `\N`, chaîne vide écrite `""` (les deux restent distincts) ; colonnes source + techniques |
| **Colonnes techniques** | `_batch_id`, `_source`, `_extracted_at`, `_row_number` sur chaque ligne de staging |
| **Idempotence** | `TRUNCATE` + `COPY` dans une transaction par table ; recharger un lot redonne le même état |
| **Traçabilité (Phase 6)** | Une ligne `etl_execution_log` par étape et par objet (source, date, durée, lignes, erreurs, statut, version), y compris en cas d'**échec de connexion** |
| **Tolérance aux pannes** | Une source en échec est tracée (`ECHEC`) ; les autres sont extraites, chargées et vérifiées ; code de sortie 1 |

Le staging ne contient que le **dernier lot**. L'historique reste dans `data/landing/` et dans le journal.

## 4. Porte G2 : 5 contrôles par objet (85 pour les 17 objets)

| Contrôle | Question (Phase 15) | Méthode |
|---|---|---|
| G2.1 | Toutes les lignes ont-elles été **extraites** ? | Recomptage **dans la source** = lignes extraites |
| G2.2 | Toutes les lignes ont-elles été **chargées** ? | Lignes en staging (pour ce lot) = lignes extraites |
| G2.3 | Des valeurs ont-elles été **altérées** ? | Empreinte MD5 calculée en Python sur le fichier **=** empreinte recalculée **en SQL** sur le staging (même ordre, même représentation des NULL). Pour MongoDB et Redis, dont le JSONB normalise le texte : mêmes `event_id` et mêmes clés, dans le même ordre |
| G2.4 | Des erreurs sont-elles apparues ? | `EXTRACT` et `LOAD` au statut `SUCCES` dans `meta.etl_execution_log` |
| G2.5 | Métadonnées à jour ? | `meta.metadata_sources` : dernier lot, nombre de lignes, statut |

Rapport : `data/reports/G2_<batch_id>.md`

## 5. Consulter les métadonnées (Adminer, serveur `pg_dw`)

```sql
-- Dernier lot : chaque étape, sa durée, ses lignes, son statut
SELECT etape, code_source, objet, nb_lignes, duree_secondes, statut, erreurs
FROM meta.etl_execution_log
WHERE batch_id = (SELECT MAX(batch_id) FROM meta.etl_execution_log)
ORDER BY id_execution;

-- Catalogue des sources
SELECT code_source, objet, technologie, encodage, separateur, version_schema,
       dernier_batch_id, derniere_nb_lignes, dernier_statut
FROM meta.metadata_sources ORDER BY 1, 2;

-- Le staging conserve les types MongoDB (anomalie D08)
SELECT jsonb_typeof(document->'timestamp') AS type_timestamp, COUNT(*)
FROM staging.stg_mongo_events GROUP BY 1;
```

## 6. Tests

| Fichier | Portée |
|---|---|
| `tests/test_pipeline.py` | 11 tests sans serveur : registre = définitions du volet A, DDL à jour, NULL distinct de la chaîne vide, empreinte, extraction CSV fidèle sur les vrais fichiers, en-tête non conforme refusé, MongoDB (mongomock, types conservés), Redis (fakeredis, classement trié, TTL) |
| `tests/test_pipeline_integration.py` | 3 tests sur les vraies bases : pipeline complet avec G2 validée, rechargement idempotent, journal complet (17 extractions) |

**Testé pendant le développement :**
- PostgreSQL, MySQL, CSV et Redis réels : **80/80**, environ 10 s pour environ 500 000 lignes ;
- MongoDB via mongomock (20 000 documents réels) : 5/5 ;
- idempotence ;
- source en échec tracée.

Le lot complet sur les 5 sources réelles (85 contrôles) est à valider **sur ta machine**, puisque MongoDB n'était pas disponible dans mon environnement.

---

# Lot L5 : couche clean, contrôle qualité, porte G3

## 7. Fichiers ajoutés

| Fichier | Rôle |
|---|---|
| `transform.py` | Staging → clean, **en SQL dans l'entrepôt** (ELT) ; une transaction par source ; ordre S1, S2, S3, S4, S5 (Redis dépend de MongoDB et MySQL) |
| `qualite_regles.py` | Catalogue des **89 règles** : dimension, action (CORRIGE, REJETE, SIGNALE), anomalies couvertes |
| `referentiels.py` | Villes, synonymes (profilés sur le staging), correspondances étudiants et contenus |
| `rapport_qualite.py` | Indicateurs du PDF par table, 5 dimensions, fraîcheur → `data/reports/qualite_<lot>.md` |
| `verify_g3.py` | **Porte G3** : chaque anomalie du journal a une trace de traitement → `data/reports/G3_<lot>.md` |
| `sql/quality/01_quality_tables.sql` | `quality.regles`, `constats`, `rejets`, `synthese`, `dimensions` + fonctions `constater` et `rejeter` |
| `sql/clean/00_fonctions.sql` | 14 fonctions de standardisation (dates dans 3 formats, téléphone, `student_code`, version, mois, IP…) |
| `sql/clean/10_…` à `50_…` | Un script par source : chaque règle = un appel à `quality.constater` ou `quality.rejeter` |

## 8. Exécution

```powershell
python -m pipeline.run_pipeline                              # les 5 étapes : extract, load, verify, transform, qualite
python -m pipeline.run_pipeline --steps transform qualite    # retraiter le lot présent en staging (~40 s)
```

## 9. Couche clean

26 tables typées : les tables source nettoyées, plus `comptes_lms` (population LMS rapprochée de PostgreSQL) et 7 tables Redis dépliées.

Chaque table conserve `_batch_id` et `_anomalies`, la liste des règles qui ont touché la ligne. Une valeur neutralisée vaut NULL ; la valeur d'origine reste dans `quality.constats`.

## 10. Résultats (lot local, 5 sources)

- **Porte G3 : 159 946 / 159 946 anomalies traitées, 69/69 types à 100 %** : 55 853 corrigées, 25 932 rejetées, 78 161 signalées.
- 797 378 lignes extraites → 772 432 lignes en couche clean.
- Transformation : environ 36 s ; MongoDB et MySQL représentent 90 % du temps.

## 11. Tests

| Fichier | Portée |
|---|---|
| `tests/test_qualite.py` | 10 tests sans base : 69 anomalies couvertes, règles du catalogue = règles utilisées dans le SQL, référentiels cohérents avec les catalogues du volet A, logique de la porte G3 |
| `tests/test_qualite_integration.py` | 26 tests sur l'entrepôt : G3 validée, 16 fonctions SQL sur des cas limites, 9 invariants de la couche clean, retraitement idempotent |
