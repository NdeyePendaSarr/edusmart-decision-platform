# Phases 7, 8 et 9 — Conception du Data Warehouse

*EduSmart Decision Platform · Lot L6 · Étape 4 du module BI*

> **Phase 7** : faits, dimensions, mesures, hiérarchies, granularité ; identifier ces éléments pour EduSmart.
>
> **Phase 8** : schéma en étoile, en flocon, constellation ; choisir et justifier.
>
> **Phase 9** : SCD de type 1, 2 et 3 ; traiter le cas « un étudiant change de ville ».
>
> Implémentation : `pipeline/sql/dw/`, `pipeline/load_dw.py`, porte G4 (`pipeline/verify_g4.py`).

---

## Phase 7 — Les concepts et leur application

### 7.1 Définitions

| Concept | Définition | Exemple EduSmart |
|---|---|---|
| **Fait** | Un **événement mesurable** du métier, enregistré au moment où il se produit | Un paiement, une tentative de quiz, une connexion |
| **Dimension** | Le **contexte** d'un fait, par lequel on filtre et on regroupe : qui, quoi, quand, où | L'étudiant qui paie, la formation, la date, la région |
| **Mesure** | La **valeur numérique** d'un fait, que l'on agrège | Montant, score, durée, pourcentage |
| **Hiérarchie** | Des niveaux emboîtés d'une dimension, pour descendre dans le détail ou remonter vers la synthèse | Jour > mois > trimestre > année ; ville > région > pays |
| **Granularité (grain)** | Ce que représente **une ligne** de la table de faits : la décision de conception la plus importante | « Une ligne = un paiement » ; « une ligne = un enseignant pour un mois » |

**Trois natures de mesures**, qui ne s'agrègent pas de la même façon :

| Nature | Règle | Exemple |
|---|---|---|
| **Additive** | Se somme sur toutes les dimensions | Montant, durée de connexion, salaire net |
| **Semi-additive** | Se somme sur certaines dimensions seulement ; ailleurs, on la moyenne | Pourcentage de progression : on le **moyenne**, on ne le somme jamais |
| **Non additive** | Ne se somme pas ; on la recalcule | Taux de réussite = somme des validations / somme des tentatives |

### 7.2 Les dimensions d'EduSmart

Le PDF propose 5 dimensions : Temps, Étudiant, Formation, Enseignant, Région. Le modèle en compte **7**, car la dimension « Formation » recouvre en réalité **deux offres qui ne se rejoignent pas** dans les sources (constat du volet A, validé à l'Étape 2) :

| Dimension | Grain | Hiérarchies | Source | Évolution |
|---|---|---|---|---|
| `dim_temps` | Le jour | jour > mois > trimestre > année ; jour > mois > **année académique** (octobre → septembre) | Générée | Fixe |
| `dim_etudiant` | Une **version** d'un étudiant | — | PostgreSQL + comptes LMS (MySQL) | **SCD 2** (ville, région) + SCD 1 |
| `dim_formation` | La classe | classe > filière > niveau / département | PostgreSQL | SCD 1 |
| `dim_module` | Le module | module > catégorie | MySQL | SCD 1 |
| `dim_quiz` | Le quiz | quiz > cours > module | MySQL (+ codes de `mapping_courses`) | SCD 1 |
| `dim_enseignant` | L'enseignant | — | CSV RH | SCD 1 |
| `dim_region` | La ville | ville > région > pays | Référentiel géographique | Fixe |

`dim_formation` porte l'offre **diplômante** (Licence en IA…), liée aux paiements et aux inscriptions. `dim_module` et `dim_quiz` portent l'offre **pédagogique en ligne** (modules Python, quiz…), liée aux notes et à la progression. Les fondre en une seule dimension inventerait un lien que les données ne contiennent pas.

**Clés de substitution et membre « Inconnu ».** Chaque dimension a une clé entière propre au DW, indépendante des identifiants sources qui sont incompatibles (UUID, `LMS-…`, `ENS-…`). Elle possède aussi une ligne de clé **−1 « Inconnu »**. Un fait dont la référence est introuvable (un quiz absent de `mapping_courses`, par exemple) pointe vers −1 : **jamais de clé NULL**, et les totaux restent justes.

### 7.3 Les faits d'EduSmart

| Fait | Grain (1 ligne =) | Mesures | Dimensions |
|---|---|---|---|
| `fact_paiements` | un paiement | montant, **montant_ca** (VALIDE et non négatif, définition L3), indicateurs 0/1 | temps, étudiant, formation, région |
| `fact_inscriptions` | une inscription (étudiant × classe) | nombre, réduction, **montant dû**, boursier, abandon, diplômé, tardive | temps, étudiant, formation, région |
| `fact_notes` | une tentative à un quiz | score, score sur 20, validé, nombre de tentatives | temps, étudiant, quiz, module |
| `fact_quiz_activite` | un événement de quiz dans l'application mobile | durée, score, succès, nombre d'événements | temps (+ heure), étudiant, quiz, module, région (lieu de l'événement) |
| `fact_connexions` | une connexion à la plateforme | durée en secondes, nombre de connexions, sans déconnexion | temps (+ heure), étudiant |
| `fact_progression` | un couple étudiant × module, à sa dernière mise à jour (**instantané**) | pourcentage (semi-additif), terminé | temps, étudiant, module |
| `fact_salaires` | un enseignant × un mois | base, primes, retenues, **net** | temps (1er du mois), enseignant |
| `fact_absences` | une absence | durée en heures, justifiée, remplacée, nombre | temps, enseignant |

Les mesures demandées par le PDF (montant, note, durée, nombre de connexions, pourcentage, base, primes, retenues, net) sont toutes présentes.

### 7.4 Matrice de bus : qui partage quoi

| Fait | Temps | Étudiant | Formation | Module | Quiz | Enseignant | Région |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Paiements | ✓ | ✓ | ✓ | | | | ✓ |
| Inscriptions | ✓ | ✓ | ✓ | | | | ✓ |
| Notes | ✓ | ✓ | | ✓ | ✓ | | |
| Activité quiz | ✓ | ✓ | | ✓ | ✓ | | ✓ |
| Connexions | ✓ | ✓ | | | | | |
| Progression | ✓ | ✓ | | ✓ | | | |
| Salaires | ✓ | | | | | ✓ | |
| Absences | ✓ | | | | | ✓ | |

`dim_temps` et `dim_etudiant` sont **conformes** : partagées par plusieurs faits, elles permettent de croiser les domaines, par exemple le CA et l'assiduité d'un même étudiant.

**Limite assumée : aucun fait ne relie un enseignant à un étudiant.** Aucune source ne lie un cours à un enseignant, en dehors du responsable de classe rapproché par son nom (C18). L'« évaluation des enseignants » reste donc hors d'atteinte (gap documenté en L3).

---

## Phase 8 — Étoile, flocon ou constellation ?

### 8.1 Comparaison

| | **Étoile** | **Flocon** | **Constellation** |
|---|---|---|---|
| Principe | 1 fait au centre ; dimensions **dénormalisées** (une table chacune) | Dimensions **normalisées** en plusieurs tables (ville → région → pays) | **Plusieurs faits** qui partagent des dimensions conformes |
| Jointures | Peu (1 par dimension) | Nombreuses | Peu, par fait |
| Redondance | Oui (la région répétée pour chaque ville) | Minimale | Comme l'étoile |
| Lisibilité métier | Excellente | Plus faible | Bonne (une étoile par processus) |
| Performance en analyse | Très bonne | Moins bonne | Très bonne |
| Mise à jour d'un attribut | Plusieurs lignes à modifier | Une seule ligne | Comme l'étoile |
| Cas d'usage | Un seul processus métier | Dimensions volumineuses et très hiérarchisées | **Plusieurs processus** à croiser |

### 8.2 Choix : une constellation d'étoiles

EduSmart suit **8 processus métier** (paiements, inscriptions, notes…) qui partagent le temps et l'étudiant. Une étoile unique mélangerait des grains incompatibles : un paiement n'est pas une tentative de quiz. Une étoile par processus **sans dimensions communes** interdirait de les croiser.

La **constellation** donne une étoile par processus, reliées par des dimensions conformes. C'est le choix validé à l'Étape 2.

**Une seule branche en flocon, assumée : `dim_quiz` → `dim_module`.** Le module d'un quiz est aussi une dimension à part entière, dont ont besoin les notes et la progression. La référencer évite de dupliquer la catégorie et le niveau dans `dim_quiz`. Ailleurs, les hiérarchies sont dénormalisées : la région est une colonne de `dim_region`, et la filière une colonne de `dim_formation`. Power BI (Phase 13) préfère les étoiles.

```
                          dim_temps (conforme)
          ┌─────────────┬──────┴──────┬──────────────┬──────────────┐
  fact_paiements  fact_inscriptions  fact_notes  fact_quiz_activite  fact_connexions ...
          │  \          │  \           │   \           │   \   \
  dim_formation  dim_region    dim_quiz ─▶ dim_module    dim_region
          \          │              │         │              │
           └──── dim_etudiant (conforme, SCD 2) ──────────────┘
  fact_salaires ── dim_enseignant ── fact_absences
```

---

## Phase 9 — Dimensions à évolution lente (SCD)

### 9.1 Les trois types

| Type | Principe | Historique | Coût | Quand l'utiliser |
|---|---|---|---|---|
| **SCD 1** | On **écrase** l'ancienne valeur | Aucun | Nul | Correction d'erreur ; attribut sans intérêt historique (téléphone, orthographe du nom) |
| **SCD 2** | On **ferme** la ligne courante et on en **ajoute** une nouvelle, avec des dates de validité | **Complet** | Une ligne par changement ; clé durable + clé de version | Attribut dont l'**analyse historique** compte (localisation, statut) |
| **SCD 3** | On ajoute une **colonne** « valeur précédente » | Une seule valeur antérieure | Une colonne | Comparer avant et après une réorganisation unique |

### 9.2 Le cas « un étudiant change de ville »

Awa, inscrite en 2024 à Thiès, déménage à Ziguinchor en septembre 2026. Question du DG : « Quel CA avons-nous encaissé dans la région de Thiès en 2025 ? »

| Type | Ce que devient la dimension | Réponse | Verdict |
|---|---|---|---|
| **SCD 1** | Ville = Ziguinchor, sans trace de Thiès | Les paiements de 2025 d'Awa **passent à Ziguinchor** : l'histoire est réécrite | ❌ Faux |
| **SCD 3** | Ville = Ziguinchor, ville précédente = Thiès | Juste pour **un** déménagement, faux au deuxième | ⚠️ Fragile |
| **SCD 2** | Version 1 : Thiès (jusqu'au 26/09/2026) ; version 2 : Ziguinchor (depuis le 27/09/2026) | Les paiements de 2025 restent rattachés à la **version 1**, donc à Thiès | ✅ Juste |

**Décision : SCD 2 sur la ville et la région** de `dim_etudiant`, et SCD 1 sur ses autres attributs. Une faute d'orthographe corrigée dans un nom est une **correction**, pas une évolution : elle s'applique à toutes les versions.

### 9.3 Mise en œuvre (`pipeline/sql/dw/10_charger_dimensions.sql`)

| Colonne | Rôle |
|---|---|
| `etudiant_key` | Clé de **version** (clé de substitution), utilisée par les faits |
| `etudiant_id` | Clé **durable** : `id_etudiant`, ou `LMS:<student_code>` pour un compte seul |
| `date_debut`, `date_fin` | Période de validité ; la version courante se termine le `9999-12-31` |
| `est_courant`, `version` | Version en vigueur (index unique partiel : **une seule** par étudiant) ; numéro 1, 2, 3… |

À chaque chargement :
1. **SCD 1** : les corrections (nom, sexe, `student_code`…) sont écrasées dans toutes les versions.
2. **SCD 2** : si la ville ou la région diffère, la version courante est **fermée la veille** de la date d'effet, et une nouvelle version s'ouvre à la date d'effet, qui est la **date d'extraction du lot**. Un second changement le même jour met à jour la version du jour, sans créer de version vide.
3. **Nouvel étudiant** : version 1, valable « depuis toujours » (`1900-01-01`), car l'historique antérieur est inconnu.

Les **faits** sont rattachés à la version valable **à leur date** :

```sql
JOIN dw.dim_etudiant d ON d.etudiant_id = <étudiant> AND <date du fait> BETWEEN d.date_debut AND d.date_fin
```

### 9.4 Démonstration : le second chargement (`python -m pipeline.demo_scd2`)

200 étudiants (2 %, graine fixe) déménagent **dans la source PostgreSQL** vers une autre région, puis le pipeline complet est relancé pour cette source.

| Contrôle | Résultat |
|---|---|
| Chaque étudiant déplacé a une version 2 courante | 200/200 ✅ |
| Version 1 fermée la veille de la date d'effet | 200/200 ✅ |
| Anciennes et nouvelles villes exactes | 200/200 ✅ |
| **Paiements passés rattachés à l'ancienne version** (l'histoire est préservée) | **746/746** ✅ |
| Toujours 10 500 étudiants courants | ✅ |
| Portes G2, G3, G4 du second lot | 25/25 · 69/69 · 57/57 ✅ |

**Leçon du volet A retrouvée en chemin.** La source porte des contraintes `CHECK … NOT VALID` : elles tolèrent les anciennes lignes anomalies, mais **s'appliquent à toute ligne modifiée**. Déplacer un étudiant dont le sexe vaut `Homme` (A01) est refusé par PostgreSQL. La démonstration ne déplace donc que des étudiants sans anomalie bloquante.

---

## Porte G4

| Contrôle | Contenu | Résultat |
|---|---|---|
| G4.1 Clés étrangères | 26 liens fait → dimension, aucune clé orpheline (et de vraies `FOREIGN KEY`) | ✅ |
| G4.2 Grain | Aucun doublon sur le grain déclaré des 8 faits | ✅ |
| G4.3 Complétude | Chaque fait = sa table clean, ligne pour ligne | ✅ |
| G4.4 Mesures | Montant, CA, masse salariale, durées, scores : DW = clean au centime | ✅ |
| G4.5 SCD 2 | 10 500 étudiants courants (9 000 appariés, 1 000 sans LMS, 500 LMS seuls) ; une version courante chacun ; ni chevauchement, ni trou | ✅ |
| G4.6 Inconnus | Aucun fait sans étudiant ni sans date ; 2 268 événements de quiz au code non résoluble (5 % voulus) | ✅ |

**57/57 contrôles**, au premier chargement comme au second.

## Références

- PDF « BI Recherche P8 », Phases 7, 8, 9 (recherche et TP).
- R. Kimball et M. Ross, *The Data Warehouse Toolkit*, 3ᵉ éd. (2013) : modélisation dimensionnelle, matrice de bus, dimensions conformes, SCD.
- Code : `pipeline/sql/dw/`, `pipeline/load_dw.py`, `pipeline/verify_g4.py`, `pipeline/demo_scd2.py`.
