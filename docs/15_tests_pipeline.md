# Phase 15 — Validation et tests du pipeline

*EduSmart Decision Platform · Lot L9 · Étape 7 du module BI*

> **PDF, recherche :** pourquoi tester un pipeline ETL ?
>
> **PDF, TP :** créer des tests permettant de vérifier : toutes les lignes ont-elles été extraites ? toutes les lignes ont-elles été chargées ? des données ont-elles été perdues ? des erreurs sont-elles apparues ? les clés sont-elles toujours valides ?
>
> Code : [`pipeline/verify_g6.py`](../pipeline/verify_g6.py) · tests : [`tests/test_verify_g6.py`](../tests/test_verify_g6.py), [`tests/test_pipeline_integration.py`](../tests/test_pipeline_integration.py) · rapport généré : `data/reports/G6_<lot>.md`.

---

## 1. Pourquoi tester un pipeline ETL ?

Un pipeline qui « tourne sans erreur » peut quand même produire de faux chiffres. Ses défauts sont **silencieux** : une jointure qui écarte des lignes, un filtre trop large ou un doublon ne lèvent aucune exception, et le tableau de bord affiche alors un chiffre faux avec une parfaite assurance.

| Raison | Ce qui arrive sans test | Exemple réel dans EduSmart |
|---|---|---|
| **Les pertes sont silencieuses** | Une ligne disparaît entre deux couches, sans message | Un `INNER JOIN` à la place d'un `LEFT JOIN` aurait écarté les paiements orphelins **sans trace**. En L5, ils sont rejetés **et tracés** dans `quality.rejets` |
| **Les doublons gonflent les totaux** | Une même ligne est comptée deux fois | 7 438 notes en double (B12) : sans dédoublonnage (règle `MY_NOTE_DOUBLON`), le nombre de tentatives et le taux de réussite seraient faussés |
| **Les sources changent** | Une colonne renommée casse l'extraction, ou pire, la vide | `version_schema` (empreinte des colonnes) dans `meta.metadata_sources` |
| **Le pipeline évolue** | Une optimisation change un résultat sans que personne ne le voie | L6 : `TRANSFORM s2_mysql` est passé de 486 s à 23 s (51 `ANALYZE`). Il fallait prouver que les **chiffres** n'avaient pas bougé, seulement la durée |
| **La confiance du décideur** | Un seul chiffre faux décrédibilise tout le tableau de bord | Le DG ne vérifiera pas 300 000 notes : il doit pouvoir faire confiance à la chaîne |
| **Les sources volatiles** | Une donnée Redis expire avant l'extraction | `statistics:today` expire au bout d'1 h (C24) : correctif L5, tolérance de G3 limitée à Redis |

Tester un pipeline, c'est donc vérifier des **invariants** : des égalités qui doivent rester vraies quelles que soient les données. Exemple : « lignes en staging = lignes en clean + lignes rejetées ». Un test d'invariant ne dépend pas d'une valeur attendue écrite à la main ; il reste valable quand les données changent.

## 2. La stratégie de test d'EduSmart

Trois niveaux, du plus rapide au plus complet :

| Niveau | Quoi | Où | Quand | Volume |
|---|---|---|---|---|
| **Tests unitaires** | Fonctions pures : règles de nettoyage, équation de conservation, comparaison des KPI, format des rapports | `tests/test_*.py` (sans base) | À chaque modification, en 2 min | 299 tests (249 avant L9, + 41 en L9, + 9 en L10) |
| **Portes de contrôle** | Invariants sur les vraies données, couche par couche | `pipeline/verify_g2.py` … `verify_g6.py` | À chaque exécution du pipeline | G2 85, G3 69, G4 57, G5a 8, G5b 8, **G6 101** |
| **Tests d'intégration** | Le pipeline complet sur les 5 vraies sources, les portes, **les mutations** | `tests/test_*_integration.py` (`EDUSMART_INTEGRATION=1`) | Avant chaque livraison de lot | 69 tests (57 avant L9, + 11 en L9, + 1 en L10) |

**Pourquoi G6 alors que G2, G3 et G4 existent ?** Chaque porte précédente regarde **une** frontière. G6 regarde la chaîne **entière**, et ajoute deux choses qui manquaient :

| Porte | Frontière contrôlée | Ce qu'elle ne voit pas |
|---|---|---|
| G2 | source → staging | ce que devient la ligne ensuite |
| G3 | anomalies du volet A → traitement | les lignes **sans** anomalie qui se perdraient |
| G4 | clean → DW | ce qui s'est perdu **avant** la couche clean |
| **G6** | **source → staging → clean + rejets → DW**, journal, clés, KPI | — |

Les deux ajouts : l'**équation de conservation staging → clean + rejets**, que personne ne vérifiait, et la **non-régression des KPI**, qui fige les 8 valeurs validées en L7.

## 3. Les 5 questions du PDF : la porte G6

| Code | Question du PDF | Contrôle | Nb |
|---|---|---|---:|
| **G6.1** | Toutes les lignes ont-elles été **extraites** ? | Source recomptée maintenant = manifeste du lot = journal `EXTRACT` (statut SUCCES) | 17 |
| **G6.2** | Toutes les lignes ont-elles été **chargées** ? | Staging (lignes du lot) = manifeste = journal `LOAD`, et **aucune ligne d'un autre lot** | 17 |
| **G6.3** | Des données ont-elles été **perdues** ? | Équation de conservation (§ 4) : 16 tables + 9 contrôles Redis + 8 faits + 2 contrôles du rapport qualité | 35 |
| **G6.4** | Des **erreurs** sont-elles apparues ? | Journal du lot : 41 étapes attendues présentes, dernière exécution SUCCES, aucune `EN_COURS`, 0 erreur ; `metadata_sources` à jour | 9 |
| **G6.5** | Les **clés** sont-elles toujours valides ? | 26 clés étrangères des 8 faits (regroupées par fait), membres « Inconnu », version courante unique (SCD 2), clés primaires des 24 tables clean, 4 intégrités garanties par les rejets | 15 |
| **G6.6** | *(ajout)* Les KPI ont-ils changé ? | Les 8 KPI de `dw.v_kpi` = valeurs validées en L7, tolérance explicite | 8 |
| | | **Total** | **101** |

**Détails de conception :**
- **Redis n'est jamais recompté après coup.** Le PDF Source 5 le dit : « Redis ne conserve pas les données de manière permanente ». Une heure après l'extraction, `statistics:today` a expiré : recompter donnerait un écart **normal**. La référence de Redis est donc l'instant d'extraction (manifeste = journal).
- **Une étape relancée n'est jugée que sur sa dernière exécution.** Le test d'idempotence recharge le staging : le journal contient alors deux lignes `LOAD` par objet. Un échec suivi d'un succès est compté à part, pour information (« échecs rattrapés »).
- **Lecture seule.** G6 n'écrit rien et ne valide aucune transaction : c'est ce qui permet les tests de mutation (§ 5).
- **G6 ne s'inscrit pas dans `meta.etl_execution_log`** (décision D-L9-03) : son propre résultat fausserait G6.4 à l'exécution suivante.
- **Réutilisation, pas recopie.** Les listes des clés étrangères et des faits viennent de `verify_g4.py`, celle des 16 tables du rapport qualité de `rapport_qualite.py`. Un test unitaire vérifie que G6 n'en possède pas de copie.

## 4. L'équation de conservation (« des données ont-elles été perdues ? »)

### 4.1 Le principe

Chaque ligne du staging a **exactement un destin** : elle arrive en clean (corrigée ou non, éventuellement signalée), ou elle est rejetée **avec trace** dans `quality.rejets`. D'où, pour chaque table :

```
lignes du lot en staging  =  lignes en clean  +  lignes rejetées DISTINCTES
lignes en clean           =  lignes du fait correspondant dans le DW
```

**Piège évité : compter les rejets avec `COUNT(*)`.** Une ligne rejetée par deux règles serait comptée deux fois, et l'équation pourrait tomber juste par hasard (une perte compensée par un double rejet). G6 compte les rejets par `COUNT(DISTINCT rang)`, où `rang` est le `_row_number` du staging, et vérifie à part qu'**aucune ligne n'est rejetée deux fois**. J'ai relu les 14 appels de `quality.rejeter` : les règles d'une même table sont disjointes (`rn > 1` pour les doublons, `rn = 1` pour les autres), donc ce contrôle doit être vert.

**Piège évité : les 159 946 anomalies ne sont pas des lignes.** Une ligne peut porter plusieurs anomalies. Elles n'entrent jamais dans une équation de lignes.

### 4.2 Redis : l'unité change selon la famille

Une ligne du staging Redis est une **clé**. La couche clean, elle, compte des clés, des messages ou des membres selon la famille. G6 écrit donc une équation par famille :

| Famille (PDF Source 5) | Unité en clean | Équation contrôlée |
|---|---|---|
| `session:*` | une session | clés = `clean.redis_sessions` |
| `last_course:*`, `last_quiz:*`, `progress:*` | un étudiant | clés = clean + clés rejetées (étudiant inconnu, E06) |
| `notifications:*` (clé) | un étudiant | clés = étudiants distincts en clean + clés rejetées |
| `notifications:*` (message) | un message | messages = clean + doublons (E04) + messages des clés rejetées |
| `online_users`, `statistics:today` | un compteur | 1 + 4 lignes de `clean.redis_compteurs` |
| `leaderboard:*` | un membre | membres = clean, **bloquant** depuis L10 (constat L9-A1, décision A1-bis) |
| toute autre clé | — | aucune clé non routée (sinon elle disparaîtrait sans trace) |

## 5. Les tests de mutation : prouver que les tests savent échouer

Un test qui ne peut pas échouer ne prouve rien. Pour chaque question du PDF, un test d'intégration **casse volontairement** une donnée, dans une transaction, vérifie que G6 passe au rouge sur le bon contrôle, puis **annule** la transaction (`ROLLBACK`). Les données réelles ne sont jamais modifiées durablement.

| Mutation | Question | Défaut introduit | Contrôle G6 qui doit échouer |
|---|---|---|---|
| `Q1` | Extraites ? | La source contient une ligne de plus que le lot (`s2_mysql.notes`) | `Extraction de s2_mysql.notes` |
| `Q2_ligne_staging_perdue` | Chargées ? | Une ligne supprimée de `staging.stg_pg_filieres` | `Chargement de s1_postgresql.filieres` |
| `Q3_ligne_dw_perdue` | Perdues ? | Une note supprimée de `dw.fact_notes` | `clean -> DW : fact_notes` |
| `Q3_ligne_clean_perdue` | Perdues ? | Un paiement supprimé de `clean.paiements`, sans rejet | `staging -> clean + rejets : s1_postgresql.paiements` |
| `Q3_rejet_en_double` | Perdues ? | Une ligne rejetée deux fois | `Aucune ligne rejetée deux fois` |
| `Q4_etape_en_echec` | Erreurs ? | Dernière exécution de `TRANSFORM s2_mysql` en `ECHEC` | `Journal : étape TRANSFORM` |
| `Q5_cle_orpheline` | Clés ? | Une inscription supprimée : ses paiements deviennent orphelins | `Intégrité clean : paiements -> inscriptions` |
| `NR_kpi_ca_fausse` | Non-régression | **1 000 XOF** ajoutés à un seul paiement (sur 13,55 Mds) | `KPI CA` |
| `Q3_membre_classement_perdu` *(L10)* | Perdues ? | Un membre du classement Redis supprimé de la couche clean | `Redis : membres du classement -> clean.redis_leaderboard` |

Une **contre-épreuve** termine la série : après les 9 mutations, G6 est de nouveau verte, ce qui prouve qu'aucune n'a été validée par erreur.

**Preuve que les tests de mutation mordent (faite pendant le développement).** En sabotant volontairement l'équation de conservation de G6 (« toujours vrai »), les deux tests `Q3_ligne_*_perdue` échouent ; G6 restaurée, ils repassent. Un test de mutation qui resterait vert avec une porte sabotée serait inutile.

## 6. Rapport de tests final

### 6.1 Chaîne des portes

| Porte | Lot | Question | Résultat |
|---|---|---|---|
| G0 | L0 | L'infrastructure répond-elle ? | 5/5 ✅ |
| G1 | L2 | Les 5 sources sont-elles conformes aux PDF ? | 195/195 ✅ (39 + 45 + 50 + 30 + 31) |
| G2 | L4 | Extraction et chargement fidèles ? | 85/85 ✅ |
| G3 | L5 | Toutes les anomalies traitées ? | 69/69 ✅ (159 946 anomalies) |
| G4 | L6 | Le Data Warehouse est-il juste ? | 57/57 ✅ |
| G5a | L7 | KPI : SQL (DW) = Python (clean) ? | 8/8 ✅ |
| G5b | L8 | KPI : DAX (Power BI) = SQL ? | 8/8 ✅ |
| **G6** | **L9** | **Le pipeline est-il fiable de bout en bout ?** | **101/101** ✅ (17 + 17 + 35 + 9 + 15 + 8) |

### 6.2 Suite pytest

| Mode | Commande | Avant L9 | Attendu après L9 | Obtenu |
|---|---|---|---|---|
| Unitaire | `python -m pytest` | 249 passed, 57 skipped | 290 passed, 68 skipped | **290 passed, 68 skipped** ✅ (166 s) |
| Intégration | `$env:EDUSMART_INTEGRATION = "1"; python -m pytest` | — | 358 passed, 0 skipped | **358 passed, 0 skipped** ✅ (1 464 s, soit 24 min) |

Critère de la porte G6 (validé le 12/10/2026) : la suite **complète** en mode intégration, **0 test ignoré**. Un test ignoré ne prouve rien. Durée constatée : 24 min pour la suite d'intégration complète (dont environ 16 min pour `test_qualite_integration`).

**Après L10** (contrôle du classement rendu bloquant, test de cohérence des rapports), attendu : **299 passed, 69 skipped** en mode unitaire, **368 passed, 0 skipped** en mode intégration.

*Résultats obtenus sur le poste de développement (Windows, Python 3.14, Docker), le 12/10/2026 ; porte G6 validée sur le lot `B20261012T134851`.*

### 6.3 Ce qui a été testé, et où

| Élément | Où | Résultat |
|---|---|---|
| 41 tests unitaires de G6 | Atelier de développement, Python 3.13 | 41/41 ✅ ; suite unitaire complète : 288 passed, 70 skipped (2 tests ignorés de plus que chez toi : `data/` absent) |
| G6 sur un **entrepôt miniature** | PostgreSQL 16 local, **vrais DDL du dépôt** (meta, staging, quality, dw), couche clean minimale, 99 lignes de staging aux équations connues, dont un échec rattrapé, un doublon de notification, un étudiant Redis inconnu et un membre de classement écarté | 101/101 ✅ |
| 8 mutations + contre-épreuve + ligne de commande | Même entrepôt miniature | 10/10 ✅ ; G6 sabotée : 2 échecs attendus ✅ |
| **G6 sur les 5 vraies sources** | Poste de développement (Docker) | **101/101** ✅ ; suite d'intégration complète 358/358 |

## 7. Journal des décisions et constats du lot L9

### Décisions

| # | Décision | Raison |
|---|---|---|
| D-L9-01 | G6 dans `pipeline/verify_g6.py` | Même famille que G2, G3, G4 (contrôles du pipeline et du DW) |
| D-L9-02 | Rapport de porte dans `data/reports/G6_<lot>.md` (non versionné) **et** synthèse versionnée dans ce document | `data/` est exclu par `.gitignore` : sans synthèse, le correcteur ne verrait aucun résultat sur GitHub |
| D-L9-03 | G6 ne s'inscrit pas dans `meta.etl_execution_log` | Un G6 en échec, journalisé, ferait échouer G6.4 à l'exécution suivante (contrôle circulaire) |
| D-L9-04 | Redis jugé à l'instant d'extraction, jamais recompté | Source volatile (PDF Source 5) |
| D-L9-05 | Rejets comptés par `COUNT(DISTINCT rang)` + contrôle séparé des doubles rejets | Une perte ne doit pas pouvoir être compensée par un double comptage |
| D-L9-06 | Référence KPI figée dans le code (`REFERENCE_KPI`) ; égalité exacte pour montants et effectifs, 10⁻⁹ pour les ratios, 10⁻⁶ pour la progression | Valeurs L7 transmises avec 10 et 8 décimales : la tolérance est d'un ordre de grandeur au-dessus de la troncature |
| D-L9-07 | Tests de mutation en transaction annulée | Prouver que G6 détecte chaque type de défaut, sans jamais modifier les données |
| D-L9-08 | Critère G6 : 0 test ignoré en mode intégration | Un test ignoré ne prouve rien |
| D-L10-01 | Contrôle du classement Redis **bloquant** (A1-bis), plutôt qu'une nouvelle règle de rejet (A1) | 0 cas attendu : une règle ne rejetterait rien, alors qu'un contrôle bloquant détecte toute perte future, sans modifier la couche clean validée en L5 |
| D-L10-02 | Test de cohérence des rapports (`tests/test_rapports.py`) | Les chiffres des rapports sont écrits à la main : ils sont comparés à `REFERENCE_KPI`, et toute variante arrondie contradictoire (« 93,1 % ») est refusée |

### Constats (à arbitrer, aucun ne bloque G6)

| # | Constat | Source | Impact | Proposition |
|---|---|---|---|---|
| **L9-A1** ✅ | Les membres du classement Redis (`leaderboard:python`) inconnus de MySQL seraient écartés par un **filtre** dans `50_s5_redis.sql`, **sans trace** dans `quality.rejets` | `clean/50_s5_redis.sql`, bloc « classement » | Risque de perte silencieuse. **0 cas attendu** : sur les données régénérées à la graine 2026, les 1 325 membres sont tous présents dans MySQL. Les « 137 » d'abord évoqués sont les 137 faux comptes E06 (`last_course`, `progress`), **rejetés avec trace** | **Résolu en L10 (A1-bis)** : le contrôle G6 devient **bloquant** (membres = clean) au lieu d'ajouter une règle qui ne rejetterait rien ; mutation `Q3_membre_classement_perdu` |
| L9-A2 | G2.1 recompte Redis en direct (`dbsize()`) : G2 relancée **seule** plus d'une heure après l'extraction échoue | `pipeline/verify_g2.py` | Faux rouge possible ; sans effet dans `run_pipeline` (G2 juste après l'extraction) | Aligner G2.1 sur D-L9-04. Non fait en L9 pour ne pas toucher une porte validée |
| L9-A3 | Le dernier commit sur GitHub est `e544056` (mise à jour du `.pbix`), pas `2c2dd26` | `git log` | Références de version dans les rapports | Utiliser `e544056` comme base de L9 |
| L9-A4 | Le README racine indiquait encore « L8 : en attente de G5b » | `README.md` | Documentation | Corrigé en L9 |

## 8. Exécution

```powershell
# 1. Tests unitaires (2 min)
python -m pytest -q

# 2. Porte G6 seule, sur le dernier lot (sources démarrées)
python -m pipeline.verify_g6
python -m pipeline.verify_g6 --sans-recomptage     # si une source est arrêtée : G6.1 compare manifeste et journal

# 3. Suite complète en mode intégration (≈ 24 min) : critère de la porte G6
$env:EDUSMART_INTEGRATION = "1"; python -m pytest -q
Remove-Item Env:EDUSMART_INTEGRATION
```

En cas d'échec, le rapport `data/reports/G6_<lot>.md` indique la question concernée, le contrôle et les comptages exacts (ex. `40 150 ≠ 40 149 clean + 0 rejetées (écart +1)`).

## Références

- PDF « BI Recherche P8 », Phase 15 (Étape 7).
- R. Kimball et J. Caserta, *The Data Warehouse ETL Toolkit* (2004) : sous-système de contrôle qualité, rapprochement des comptages entre couches.
- Documents du projet : [05_qualite.md](05_qualite.md) (rejets, porte G3), [06_metadonnees.md](06_metadonnees.md) (journal), [07_conception_dw.md](07_conception_dw.md) (porte G4), [11_kpi.md](11_kpi.md) (valeurs de référence).
