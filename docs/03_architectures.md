# Phase 3 — Les architectures décisionnelles

*EduSmart Decision Platform · Lot L3 · Étapes 1 et 2 du module BI*

> **Demande du PDF :** étudier le Data Warehouse, le Data Mart, le Data Lake et le Data Lakehouse, selon cinq axes : définition, architecture, avantages, limites, cas d'utilisation. Puis proposer et justifier une architecture pour EduSmart.

---

## 1. Data Warehouse (entrepôt de données)

### Définition

Un **Data Warehouse** est une base de données centrale qui **intègre** les données de plusieurs sources opérationnelles, les **nettoie**, les **historise** et les **organise pour l'analyse**.

La définition de W. H. Inmon reste la référence : une collection de données
- **orientées sujet** (étudiant, paiement, et non « application MySQL ») ;
- **intégrées** (identifiants, formats et référentiels unifiés) ;
- **historisées** (le temps est une dimension) ;
- **non volatiles** (on ajoute, on ne modifie pas l'historique) ;

destinée à l'aide à la décision.

### Architecture

```
 Sources (OLTP, fichiers)      Intégration (ETL/ELT)          Entrepôt                     Restitution
 ┌───────────┐                ┌────────────────────┐   ┌──────────────────────────┐   ┌──────────────┐
 │PostgreSQL │──┐             │ extraction         │   │ zone de préparation      │   │ tableaux de  │
 │MySQL      │──┼──────────▶  │ contrôle qualité   │──▶│ (staging)                │──▶│ bord, OLAP,  │
 │CSV        │──┤             │ transformation     │   │ modèle dimensionnel      │   │ rapports     │
 │MongoDB... │──┘             │ chargement         │   │ (faits + dimensions)     │   └──────────────┘
 └───────────┘                └────────────────────┘   └──────────────────────────┘
                                          ▲ métadonnées, journal d'exécution ▲
```

Il existe deux grandes approches de construction :
- **Inmon (descendante)** : un entrepôt d'entreprise normalisé, à partir duquel on dérive des data marts.
- **Kimball (ascendante)** : des modèles dimensionnels en étoile, construits sujet par sujet et reliés par des **dimensions conformes**. C'est l'approche des Phases 7 et 8.

### Avantages
- **Une seule version de la vérité** : une définition du CA, un comptage des étudiants.
- **Données fiables et nettoyées** ; qualité mesurée.
- **Historique** : suivi dans le temps, dimensions à évolution lente (Phase 9).
- **Performance d'analyse** : modèle dénormalisé, agrégations rapides, sans charger les bases de production.
- **Traçabilité** : métadonnées, lignage, journal d'exécution.
- Parfaitement adapté aux **outils BI** (Power BI) et au **SQL**.

### Limites
- **Conception exigeante** : il faut modéliser *avant* de charger (*schema-on-write*).
- **Rigidité** : une nouvelle question non prévue peut exiger de modifier le modèle.
- **Coût et délai** de mise en place, en particulier l'intégration.
- **Peu adapté aux données non structurées** (images, vidéos, textes libres) et au temps réel strict.
- La **latence** : des données souvent rafraîchies une fois par jour.

### Cas d'utilisation
Pilotage de la performance, reporting financier, tableaux de bord de direction, analyses historiques. **C'est le cas typique d'une direction qui veut ses indicateurs de pilotage consolidés.**

---

## 2. Data Mart (magasin de données)

### Définition

Un **Data Mart** est un **sous-ensemble** de données décisionnelles consacré à **un domaine métier** ou à un service (finance, pédagogie, RH). Il contient uniquement les faits et les dimensions utiles à ce domaine.

### Architecture

On en distingue deux formes :
- **Dépendant** : il est alimenté *à partir du Data Warehouse*. C'est la forme recommandée, car les définitions restent cohérentes.
- **Indépendant** : il est alimenté *directement depuis les sources*. C'est rapide à construire, mais on recrée des silos.

```
                     ┌─▶ Data Mart Finance    (fait paiements, dim temps, dim étudiant)
 Data Warehouse ─────┼─▶ Data Mart Pédagogie  (faits notes, progression, connexions)
                     └─▶ Data Mart RH         (faits salaires, absences, dim enseignant)
```

### Avantages
- **Simple et rapide** pour les utilisateurs d'un service.
- **Performances** : un volume réduit, un modèle ciblé.
- **Sécurité** : chaque service ne voit que son domaine (les salaires RH restent confidentiels).
- Permet une **mise en œuvre progressive**, domaine par domaine.

### Limites
- Des marts **indépendants** recréent des silos, avec des définitions divergentes : le problème même que la BI veut résoudre.
- **Redondance** des données et des traitements.
- **Pas de vue transverse** à lui seul : le DG a besoin de croiser finance et pédagogie.

### Cas d'utilisation
Besoin d'un service précis, périmètre limité, sécurité par domaine, projet pilote avant un entrepôt complet.

---

## 3. Data Lake (lac de données)

### Définition

Un **Data Lake** est un espace de stockage **massif et peu coûteux** qui conserve les données **brutes, dans leur format natif** (structurées, semi-structurées, non structurées). La structure n'est imposée **qu'à la lecture** (*schema-on-read*). Le terme a été popularisé par J. Dixon en 2010.

### Architecture

```
 Sources (tout format) ──▶ stockage objet (S3, ADLS, HDFS) organisé en zones :
                           brut (raw) ─▶ nettoyé ─▶ préparé
                           + catalogue de métadonnées
                           + moteurs de traitement (Spark, SQL distribué, ML)
```

### Avantages
- **Tout conserver**, sans devoir modéliser à l'avance.
- **Souplesse** : de nouvelles analyses sont possibles sur des données brutes.
- **Faible coût** de stockage, **passage à l'échelle** (téraoctets, pétaoctets).
- Adapté au **Big Data**, à la **science des données** et au **machine learning** (fichiers, images, logs).

### Limites
- Risque de **« marécage de données »** (*data swamp*) : sans gouvernance ni catalogue, personne ne sait ce que contient le lac, ni si c'est fiable.
- **Qualité non garantie** : la donnée est brute.
- **Pas de transactions ACID** natives ; mises à jour difficiles.
- **Performances médiocres** pour le reporting interactif ; il faut souvent recopier dans un entrepôt pour la BI.
- Exige des **compétences** spécialisées (Spark, formats Parquet) et une infrastructure distribuée.

### Cas d'utilisation
Très gros volumes et grande variété (logs, IoT, images), exploration par des data scientists, entraînement de modèles, archivage à bas coût.

---

## 4. Data Lakehouse

### Définition

Un **Data Lakehouse** combine le **stockage bon marché et ouvert d'un lac** (fichiers Parquet sur stockage objet) avec les **fonctions d'un entrepôt** : transactions ACID, schémas, gouvernance, performances SQL. Cela passe par une **couche de tables transactionnelles** (Delta Lake, Apache Iceberg, Apache Hudi). Le concept a été formalisé par M. Armbrust et al. (CIDR 2021).

### Architecture

Elle est souvent organisée en **médaillon** :

```
 Sources ─▶ Stockage objet + format de table ouvert (Delta / Iceberg)
            ├── Bronze : données brutes, telles qu'extraites
            ├── Argent : données nettoyées, conformes, dédoublonnées
            └── Or     : données agrégées / modèles dimensionnels pour la BI
            + moteur SQL, ML et streaming sur les MÊMES données
```

### Avantages
- **Une seule plateforme** pour la BI **et** la science des données, **sans copie** entre lac et entrepôt.
- **ACID, versions** (*time travel*), évolution de schéma.
- **Coût du stockage objet**, formats ouverts (pas d'enfermement propriétaire).
- Adapté aux **gros volumes** et au **temps réel** (streaming).

### Limites
- **Technologie récente** et en évolution ; écosystème complexe (Spark, Databricks, catalogues).
- Exige une **infrastructure** (cloud ou cluster) et des **compétences** avancées.
- **Surdimensionné** pour de petits volumes structurés.
- Les performances BI interactives peuvent rester inférieures à celles d'un entrepôt bien optimisé.

### Cas d'utilisation
Organisations qui ont **à la fois** de gros volumes variés, des besoins BI **et** des besoins de machine learning ou de temps réel : grandes plateformes numériques, télécoms, banques.

---

## 5. Comparaison

| Critère | Data Warehouse | Data Mart | Data Lake | Data Lakehouse |
|---|---|---|---|---|
| Données | Structurées, intégrées | Structurées, un domaine | Tout format, brut | Tout format, brut → raffiné |
| Schéma | À l'écriture | À l'écriture | À la lecture | Les deux (couches) |
| Qualité | Élevée, contrôlée | Élevée (si dépendant) | Non garantie | Croissante par couche |
| Historique | Oui (SCD) | Oui | Oui (brut) | Oui (+ *time travel*) |
| ACID | Oui | Oui | Non | Oui |
| Volume visé | Go → To | Mo → Go | To → Po | To → Po |
| Utilisateurs | Décideurs, analystes | Un service | Data scientists | Tous |
| Outils BI (Power BI) | Excellent | Excellent | Médiocre | Bon |
| Coût et complexité | Moyens | Faibles | Stockage faible, compétences élevées | Élevés |
| Maturité | Très forte | Très forte | Forte | En cours |

---

## 6. Cas pratique : quelle architecture pour EduSmart ?

### 6.1 Critères de choix, mesurés sur le volet A

| Critère | Constat EduSmart | Conséquence |
|---|---|---|
| **Volume** | ~800 000 enregistrements (799 037), quelques centaines de Mo | Pas de Big Data : un SGBD relationnel suffit largement |
| **Nature des données** | 4 sources structurées (PostgreSQL, MySQL, CSV) + 1 semi-structurée (JSON MongoDB) + 1 clé-valeur temporaire (Redis). **Aucune donnée non structurée** (ni image, ni vidéo, ni texte libre) | Le stockage JSONB de PostgreSQL suffit pour MongoDB |
| **Besoin principal** | Pilotage de direction : KPI, historique, Power BI (Phases 10 à 14) | Besoin typique d'un **entrepôt** |
| **Qualité** | 159 946 anomalies réparties sur 69 types | Il faut des **couches** (brut → nettoyé) et un contrôle qualité traçable (Phases 5 et 6) |
| **Historique** | Déménagements des étudiants (Phase 9) ; Redis ne garde rien | Il faut un **SCD 2** dans des dimensions : fonction d'entrepôt |
| **Temps réel** | Redis n'est qu'un **snapshot** ; aucun besoin de décision à la seconde | Chargement par lots (quotidien) suffisant |
| **Machine learning** | Aucun besoin exprimé | Aucun argument pour un lac ou un lakehouse |
| **Équipe et moyens** | Une personne, un poste Windows, Docker, sans cloud | Pas de cluster Spark ni de stockage objet |
| **Confidentialité** | Salaires, téléphones, adresses IP | Vues ou marts par domaine, droits différenciés |

### 6.2 Proposition : un Data Warehouse PostgreSQL en couches, avec des data marts dépendants

*(Décision prise à l'Étape 2 et en L0 : PostgreSQL pour le DW, conteneur `pg_dw` distinct des sources.)*

```
 SOURCES (conteneurs Docker)                    DATA WAREHOUSE — PostgreSQL « edusmart_dw »            RESTITUTION
 ┌─────────────────────────┐                   ┌───────────────────────────────────────────────┐
 │ PostgreSQL  academic    │─┐                 │ staging  (BRONZE) : copie brute des 5 sources   │
 │ MySQL       learning    │─┤  extract_*.py   │          TEXT / JSONB + _source, _batch_id       │
 │ CSV RH (fichiers)       │─┼──▶ load.py ───▶ │ clean    (ARGENT) : typé, standardisé, dédoublonné│
 │ MongoDB     events      │─┤                 │ dw       (OR)     : constellation de 8 faits     │──▶ Power BI
 │ Redis       snapshot    │─┘                 │                     + dimensions conformes, SCD2 │    (modèle tabulaire,
 └─────────────────────────┘                   │ quality  : rejets, rapport qualité (Phase 5)    │     KPI, OLAP)
                                               │ meta     : metadata_sources, etl_execution_log  │
       mappings/ (correspondances) ───────────▶│ (Phase 6)                                        │
                                               └───────────────────────────────────────────────┘
                                                transform.py : SQL exécuté DANS l'entrepôt (ELT, Phase 4)
```

Les **data marts** sont des **vues** ou des sous-ensembles de la constellation, *dépendants* de l'entrepôt :

| Data mart | Faits | Utilisateurs | Contenu confidentiel |
|---|---|---|---|
| Finance | paiements, inscriptions | Direction financière, DG | — |
| Pédagogie | notes, quiz, connexions, progression | Direction des études | — |
| RH | salaires, absences | RH, DG uniquement | **Salaires** |

### 6.3 Justification

1. **Le besoin est un pilotage de direction sur des données structurées.** C'est le domaine d'excellence du Data Warehouse (point 1).
2. **Le volume est modeste.** Un lac ou un lakehouse apporterait complexité et coût sans bénéfice.
3. **Le seul format non relationnel (JSON MongoDB) est géré nativement par PostgreSQL** (`JSONB`). Le schéma flexible est conservé en couche brute, puis normalisé.
4. **On reprend la meilleure idée du Lakehouse**, l'organisation en couches bronze / argent / or, **sans sa technologie**. Les données brutes restent disponibles, ce qui permet de rejouer les transformations et de prouver la qualité (Phases 5, 6 et 15).
5. **Les data marts dépendants** évitent les silos et répondent au besoin de confidentialité (salaires).
6. **La cohérence technique** : même SGBD que la Source 1, SQL standard, connecteur Power BI natif, Docker déjà opérationnel.
7. **Une trajectoire d'évolution est possible.** Si EduSmart ajoutait un jour des vidéos de cours, des traces d'apprentissage massives ou du machine learning (prédiction des abandons), les couches bronze et argent pourraient migrer vers un **lakehouse** (Parquet + Iceberg) sans remettre en cause le modèle « or ».

### 6.4 Ce que cette architecture n'est pas

Par honnêteté, et c'est un point de soutenance : il ne s'agit **pas** d'un vrai Data Lakehouse. Il n'y a ni stockage objet, ni format de table ouvert, ni moteur distribué. Il s'agit d'un **Data Warehouse** qui emprunte au Lakehouse son **organisation en médaillon**. Ce choix est cohérent avec le volume et les moyens d'EduSmart.

| Architecture | Retenue ? | Motif |
|---|:-:|---|
| Data Warehouse | ✅ Cœur de la solution | Pilotage, historique, qualité, Power BI |
| Data Marts dépendants | ✅ Sous forme de vues par domaine | Simplicité, confidentialité RH |
| Data Lake | ❌ | Volume faible, aucune donnée non structurée, risque de marécage |
| Data Lakehouse | ⚠️ Organisation seulement | Couches bronze / argent / or reprises ; technologie non justifiée |

## Références

- PDF « BI Recherche P8 », Phase 3 ; décisions validées à l'Étape 2 (architecture cible, schémas du DW).
- W. H. Inmon, *Building the Data Warehouse* (1992).
- R. Kimball et M. Ross, *The Data Warehouse Toolkit* (3ᵉ édition, 2013).
- J. Dixon, billet « Pentaho, Hadoop, and Data Lakes » (2010) : origine du terme *data lake*.
- M. Armbrust, A. Ghodsi, R. Xin, M. Zaharia, *Lakehouse: A New Generation of Open Platforms that Unify Data Warehousing and Advanced Analytics*, CIDR 2021.
