# Phase 6 — Métadonnées et traçabilité

*EduSmart Decision Platform · Lots L4 et L5 · Étape 3 du module BI*

> **Recherche du PDF :** pourquoi conserver la source, la date d'extraction, la version, le nombre de lignes, le statut du traitement ?
>
> **TP :** créer `metadata_sources` et `etl_execution_log`. Chaque exécution doit enregistrer la source, la date, la durée, le nombre de lignes, les erreurs et le statut.

---

## 1. Qu'est-ce qu'une métadonnée ?

Une **métadonnée** est une **donnée sur les données**. On en distingue trois familles :

| Famille | Répond à | Exemple EduSmart |
|---|---|---|
| **Descriptive** (technique) | Qu'est-ce que c'est ? Où est-ce ? Sous quelle forme ? | `salaires.csv`, ISO-8859-1, séparateur `;`, 9 colonnes |
| **Opérationnelle** (d'exécution) | Que s'est-il passé, quand, avec quel résultat ? | Lot `B20260927T100618` : 4 125 salaires extraits en 0,02 s, statut SUCCES |
| **De lignage** (traçabilité) | D'où vient ce chiffre ? Quelles transformations a-t-il subies ? | Le paiement `PAY-2025-013460` : source PostgreSQL → fichier du lot → staging → clean (mode `OM` corrigé en `Orange Money`) |

## 2. Pourquoi conserver chaque information ?

| Information | Pourquoi | Cas vécu dans ce projet |
|---|---|---|
| **La source** | Savoir d'où vient un chiffre ; comparer les sources ; attribuer une anomalie à son système d'origine | Le CA existe dans PostgreSQL **et** dans MongoDB : sans la source, impossible de savoir lequel fait foi |
| **La date d'extraction** | Dater l'état des données ; juger leur fraîcheur ; rejouer un lot | Redis change en permanence : seule la date d'extraction dit **quel** instant a été figé |
| **La version** | Détecter un changement de structure ; savoir quel code a produit quel résultat | `version_schema` (empreinte des colonnes) : une colonne ajoutée dans une source change l'empreinte et le signale. `version_pipeline` = 1.0.0 |
| **Le nombre de lignes** | Prouver que rien n'a été perdu entre les étapes (Phase 15) | La porte G2 compare les lignes de la source, du fichier et du staging : 85/85 |
| **Le statut** | Savoir si le chiffre est fiable ; relancer ce qui a échoué | Une source injoignable est tracée `ECHEC` : on sait qu'il manque des données plutôt que de croire qu'il n'y en a pas |

**Un cas réel.** Pendant le développement de L5, le premier calcul du rapport qualité a échoué (une erreur `IndexError`). Le journal l'a enregistré :

```
etape  | statut | nb_lignes | erreurs
VERIFY | ECHEC  |           | IndexError: tuple index out of range
```

Sans cette trace, un rapport vide aurait pu passer pour « aucune anomalie ».

## 3. Les tables (TP)

### 3.1 `meta.metadata_sources` : le catalogue des 17 objets sources

Une ligne par objet, soit 5 tables PostgreSQL, 6 tables MySQL, 4 fichiers CSV, la collection MongoDB et la base Redis.

| Colonne | Contenu |
|---|---|
| `code_source`, `objet` | Clé : `s3_csv` / `salaires` |
| `technologie`, `emplacement` | `Fichier CSV` / `sources/s3_csv/output/` ; `PostgreSQL 15` / `localhost:5435/edusmart_academic` |
| `table_staging`, `nb_colonnes`, `encodage`, `separateur` | `staging.stg_csv_salaires`, 9, `ISO-8859-1`, `;` |
| `description` | Reprise du PDF |
| **`version_schema`** | Empreinte MD5 de la liste des colonnes (`e904f46848c4` pour les salaires) |
| **`derniere_extraction`, `dernier_batch_id`, `derniere_nb_lignes`, `dernier_statut`** | État de la **dernière** extraction |

La partie descriptive est générée depuis `pipeline/registry.py` : il n'y a **pas de double saisie**, donc le catalogue ne peut pas diverger du code.

### 3.2 `meta.etl_execution_log` : le journal de chaque étape

Une ligne **par étape, par objet et par exécution**.

| Exigence du PDF | Colonne |
|---|---|
| source | `code_source`, `objet` |
| date | `date_debut`, `date_fin` |
| durée | `duree_secondes` |
| nombre de lignes | `nb_lignes` |
| erreurs | `nb_erreurs`, `erreurs` (message complet) |
| statut | `statut` : `EN_COURS` → `SUCCES` ou `ECHEC` |
| *(ajouts)* | `batch_id` (le lot), `etape` (EXTRACT, LOAD, TRANSFORM, VERIFY), `version_pipeline` |

Chaque ligne est **validée immédiatement**, en autocommit : même si le pipeline s'arrête brutalement, la trace de l'étape en cours reste, au statut `EN_COURS`.

Exemple réel, pour le lot `B20260927T100618` (4 sources extraites, 5 transformées) :

| Étape | Statut | Lignes | Objets |
|---|---|---:|---:|
| EXTRACT | SUCCES | 501 436 | 16 |
| LOAD | SUCCES | 501 436 | 16 |
| TRANSFORM | SUCCES | — | 5 sources, à chaque exécution |
| VERIFY | SUCCES (G2, G3) / ECHEC (1 tentative) | — | — |

## 4. Le lignage de bout en bout

Chaque ligne peut être suivie de la source jusqu'à la couche clean :

```
Source ──▶ data/landing/<lot>/<source>/<objet>.csv ──▶ staging.stg_* ──▶ clean.*
            manifest.json (lignes, empreinte)           _batch_id         _batch_id
                                                        _source           _anomalies (règles appliquées)
                                                        _extracted_at
                                                        _row_number ──▶ quality.rejets.rang (ligne écartée)
                                                                        quality.constats (avant → après)
```

Pour une ligne de la couche clean, on sait donc :
- de quel **lot** et de quelle **source** elle vient, et **quand** elle a été extraite ;
- quelles **règles** l'ont touchée : colonne `_anomalies`, puis `quality.constats` pour la valeur avant et après ;
- si une ligne source **manque**, pourquoi : `quality.rejets` en conserve le **contenu intégral** et le motif.

Exemple de requête d'audit :

```sql
-- Qu'est-il arrivé au paiement X ?
SELECT code_regle, colonne, valeur_avant, valeur_apres, action
FROM quality.constats WHERE id_ligne = '<id_paiement>';
```

## 5. Ce que les métadonnées permettent

| Usage | Comment |
|---|---|
| **Auditer** un chiffre | Lignage : lot → source → constats |
| **Reprendre** après une panne | Statut par objet ; `--steps load verify` recharge le dernier lot sans réextraire |
| **Détecter une évolution de source** | `version_schema` change si une colonne change |
| **Mesurer la fraîcheur** | `derniere_extraction` et dernière donnée métier (rapport qualité, § 4) |
| **Tester le pipeline** (Phase 15) | Lignes par étape ; les portes G2 et G3 s'appuient sur ces tables |
| **Surveiller la performance** | `duree_secondes` : l'extraction MongoDB (environ 30 s) est l'étape la plus longue |

## Références

- PDF « BI Recherche P8 », Phase 6 (recherche et TP) ; Phase 15 (tests).
- R. Kimball et J. Caserta, *The Data Warehouse ETL Toolkit* (2004) : métadonnées de processus et journal d'audit.
- Code : `pipeline/sql/meta/01_meta_tables.sql`, `pipeline/meta.py`, `pipeline/registry.py`.
