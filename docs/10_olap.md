# Phase 10 — Analyse multidimensionnelle (OLAP)

*EduSmart Decision Platform · Lot L7 · Étape 5 du module BI*

> **Recherche du PDF :** cube OLAP, drill down, roll up, slice, dice, pivot.
>
> **TP :** explorer le cube EduSmart.
>
> Requêtes : `pipeline/sql/olap/01_cube.sql` à `06_pivot.sql`. Résultats complets : `data/reports/olap_<lot>.md` (`python -m pipeline.olap`). Montants en XOF.

---

## 1. Le cube OLAP

Un **cube OLAP** présente une mesure selon plusieurs **axes** (les dimensions). Chaque **cellule** est la valeur de la mesure pour une combinaison de membres : par exemple, le CA de l'année 2024-2025, dans la région de Thiès, en Master.

Le cube contient aussi **tous les totaux** : par année toutes régions confondues, par région toutes années confondues, le total général… L'analyse consiste alors à **naviguer** dans le cube, sans écrire une nouvelle requête pour chaque question.

**OLAP vs OLTP (rappel de la Phase 1).** L'OLTP enregistre des transactions, une ligne à la fois. L'OLAP agrège des millions de lignes pour répondre à des questions de pilotage.

**Mise en œuvre choisie à l'Étape 2 : ROLAP.** Le cube est calculé par SQL sur le schéma en constellation (`GROUP BY CUBE`, `ROLLUP`, `GROUPING SETS`), puis consommé par le modèle tabulaire de Power BI (L8). Pas de serveur MOLAP dédié : le volume (environ 500 000 faits) ne le justifie pas.

### Les deux cubes d'EduSmart (matérialisés dans le DW)

| Cube | Mesures | Axes | Cellules |
|---|---|---|---|
| `dw.cube_finance` | CA, nombre de paiements | année académique × région × niveau | toutes les combinaisons + 7 niveaux de totaux (`GROUP BY CUBE` = 2³ regroupements) |
| `dw.cube_pedagogie` | tentatives, validations, taux de validation, score moyen sur 20 | catégorie × niveau du module × année académique | idem |

La colonne `niveau_agregation` (fonction `GROUPING`) indique quelles dimensions sont agrégées : 0 pour une cellule détaillée, 7 pour le total général.

**Contrôle d'intégrité** (test d'intégration) : le total du cube (13 553 901 000 XOF) est égal au KPI CA. Le cube est **additif** : la somme des régions, des niveaux ou des années redonne le total.

## 2. Les cinq opérations, sur le cube EduSmart

### Roll up (forage vers le haut) : du détail vers la synthèse

On **remonte** une hiérarchie, ici `dim_temps` : mois > trimestre > année.

| 2025 | T1 | T2 | T3 | T4 | Année |
|---|---:|---:|---:|---:|---:|
| Encaissements (millions XOF) | 1 537,7 | 1 038,2 | **2 653,9** | 196,6 | 5 426,3 |

Au niveau des mois, le détail montre **trois pics** : janvier (909 M), avril (906 M) et août-septembre (2 263 M). Ce sont les trois tranches, la plus forte étant celle de la rentrée. Mars, mai, novembre et décembre sont presque vides.

**Enseignement pour la trésorerie :** près de la moitié des encaissements de l'année arrive en trois mois.

**Piège évité.** Une hiérarchie se parcourt sur **une seule** dimension. Croiser l'année **de la formation** avec le trimestre **de la date de paiement** placerait les acomptes de juillet-septembre (avant la rentrée) à la **fin** d'une année qu'ils précèdent. Ma première version de cette requête commettait cette erreur.

### Drill down (forage vers le bas) : de la synthèse vers le détail

Le parcours d'un décideur :

| Niveau | Question | Réponse |
|---|---|---|
| 1. Région | Où est le CA ? | **Dakar** : 3 897 M (29 %), loin devant Thiès (1 735 M) et Diourbel (1 247 M) |
| 2. Ville (région de Dakar) | Dakar, c'est uniquement la capitale ? | Non : la ville de Dakar pèse 1 747 M, mais la banlieue (Guédiawaye, Rufisque, Keur Massar, Pikine) en apporte **2 150 M** |
| 3. Filière (ville de Dakar) | Qu'y achète-t-on ? | Des **Masters** : Business Intelligence (189 M), IA (168 M), Cybersécurité (133 M) |

### Slice (tranche) : on fixe **une** dimension

Tranche « année académique = 2024-2025 », toutes filières. Les 10 filières au taux d'abandon le plus élevé :

| Filière | Inscriptions | Abandon | Recouvrement |
|---|---:|---:|---:|
| Réseaux et Télécommunications (Licence) | 341 | **9,38 %** | 90,74 % |
| Marketing Digital (Licence) | 152 | 9,21 % | 88,28 % |
| Intelligence Artificielle (Certificat) | 144 | 8,33 % | 89,19 % |
| … | | | |

Les **Licences** et les **Certificats** abandonnent plus que les Masters. C'est une piste pour la Phase 14.

### Dice (dé) : on restreint **plusieurs** dimensions → un sous-cube

Sous-cube « années 2024-2025 et 2025-2026 × régions Dakar et Thiès × niveau Master » :

| Année | Région | CA | Paiements | Paiement moyen |
|---|---|---:|---:|---:|
| 2024-2025 | Dakar | 787 M | 1 231 | 686 384 |
| 2024-2025 | Thiès | 348 M | 565 | 674 753 |
| 2025-2026 | Dakar | 718 M | 1 212 | 659 105 |
| 2025-2026 | Thiès | 327 M | 537 | 680 336 |

### Pivot (rotation) : on fait tourner les axes

La même donnée, les années passées **en colonnes** pour comparer d'un coup d'œil (CA en millions XOF) :

| Région | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---:|---:|---:|
| Dakar | 846,7 | 1 455,5 | 1 594,6 |
| Thiès | 351,3 | 648,4 | 735,0 |
| Diourbel | 266,9 | 465,9 | 514,2 |
| … | | | |

Toutes les régions progressent. 2023-2024 est plus faible parce qu'elle compte moins d'inscriptions (3 617, contre 6 191 l'année suivante) : c'est la première année de la période étudiée.

Le **pivot pédagogique** (catégorie × niveau du module) montre un taux de validation **par tentative** d'environ 74 %, homogène (de 71,6 % à 75,8 %). Cette **métrique** diffère du **KPI** de réussite, qui compte par couple étudiant-quiz (93,13 %) ; la Phase 11 explique cette différence.

## 3. Synthèse

| Opération | Geste | SQL | Exemple EduSmart |
|---|---|---|---|
| **Cube** | Toutes les combinaisons et tous les totaux | `GROUP BY CUBE (a, b, c)` | `dw.cube_finance` |
| **Roll up** | Remonter une hiérarchie | `GROUP BY ROLLUP (année, trimestre, mois)` | Encaissements 2025 |
| **Drill down** | Descendre une hiérarchie | filtre sur le niveau supérieur + regroupement au niveau inférieur | Région → ville → filière |
| **Slice** | Fixer une dimension | `WHERE annee_academique = '2024-2025'` | Abandon par filière |
| **Dice** | Restreindre plusieurs dimensions | `WHERE annee IN (…) AND region IN (…) AND niveau = …` | Masters à Dakar et Thiès |
| **Pivot** | Tourner les axes | `SUM(…) FILTER (WHERE …)`, un par colonne | Régions × années |

Dans Power BI (L8), ces gestes deviennent des clics : hiérarchie de dates et de régions (drill down et roll up), segments (slice et dice), matrice (pivot).

## Références

- PDF « BI Recherche P8 », Phase 10.
- E. F. Codd, *Providing OLAP to User-Analysts* (1993) : origine du terme OLAP.
- Documentation PostgreSQL : `GROUPING SETS`, `CUBE` et `ROLLUP`.
