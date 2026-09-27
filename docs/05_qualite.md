# Phase 5 — Contrôle qualité des données

*EduSmart Decision Platform · Lot L5 · Étape 3 du module BI*

> **Objectif du PDF :** comprendre qu'un ETL ne consiste pas seulement à déplacer des données.
>
> **TP :** construire un rapport qualité indiquant le nombre de lignes extraites, les lignes rejetées, les doublons, les valeurs manquantes, les incohérences détectées et les corrections effectuées.
>
> Les chiffres ci-dessous sont ceux du rapport automatique `data/reports/qualite_<lot>.md`, produit à chaque exécution du pipeline.

---

## 1. Qu'est-ce que la qualité des données ?

La **qualité des données** est leur **aptitude à l'usage** : une donnée est de qualité si elle permet de prendre la bonne décision. Ce n'est donc pas une propriété absolue.
- Un téléphone mal formaté ne gêne pas le calcul du CA.
- Un montant négatif, lui, le fausse.

On la mesure selon plusieurs **dimensions**, et on la rend visible par des **règles** exécutées à chaque chargement.

Dans un ETL, la qualité se traite **dans le pipeline**, et pas après coup dans le tableau de bord. Sinon, chaque rapport corrige à sa façon, et deux rapports finissent par donner deux chiffres différents (Phase 1, point 9).

## 2. Les cinq dimensions demandées par le PDF

| Dimension | Définition | Exemple EduSmart | Règles | Taux de conformité mesuré |
|---|---|---|---:|---|
| **Complétude** | La donnée attendue est présente | Téléphone manquant, document MongoDB tronqué, connexion sans déconnexion | 14 | de 86,4 % (MongoDB) à 99,7 % (Redis) |
| **Unicité** | Un fait réel n'est enregistré qu'une fois | Inscription saisie deux fois, événement journalisé deux fois, ligne RH exportée deux fois | 11 | de 95,9 % (MongoDB) à 98,8 % (Redis) |
| **Cohérence** | Les données sont conformes entre elles et aux référentiels | `DAKAR` et `Dakar`, 19 écritures d'un mode de paiement, paiement sans inscription | 39 | de 88,8 % (MongoDB) à 98,8 % (MySQL) |
| **Exactitude** | La valeur est correcte et plausible | Montant négatif, progression à 127 %, score au-dessus du maximum, date au mauvais format | 25 | de 91,7 % (MongoDB) à 97,7 % (Redis) |
| **Fraîcheur** | La donnée est assez récente pour l'usage | MySQL et MongoDB à jour au 15/09/2026 ; derniers paiements PostgreSQL en mai | mesure par source | voir le § 4 |

Taux de conformité = 1 − lignes en défaut / lignes contrôlées, pour chaque source (tableau complet dans le rapport, § 3).

**Deux remarques de méthode :**
- **Une anomalie peut relever de plusieurs dimensions** selon l'angle d'analyse. Une référence de paiement partagée est un défaut d'**unicité** ; un paiement orphelin est un défaut de **cohérence** (intégrité référentielle). Chaque règle est rattachée à **une seule** dimension, documentée dans le catalogue.
- **Certaines anomalies échappent à tout schéma.** 3 des 11 anomalies MongoDB (villes mal écrites, doublons, adresses IP invalides) passent le validateur `$jsonSchema` (L2-d). Seules des règles **métier** les détectent.

## 3. Méthode appliquée

### 3.1 Trois actions, décidées règle par règle

| Action | Principe | Nombre de règles | Anomalies traitées |
|---|---|---:|---:|
| **CORRIGÉ** | La bonne valeur se déduit **sans ambiguïté** (référentiel, format, recalcul) | 30 | 55 853 |
| **REJETÉ** | La ligne est inutilisable ou en double : écartée de la couche clean et **conservée intégralement** dans `quality.rejets` | 14 | 25 932 |
| **SIGNALÉ** | La vraie valeur est **inconnaissable** : la ligne est gardée et marquée (colonne `_anomalies`), la valeur invalide est neutralisée à NULL | 45 | 78 161 |

**Principe : on ne fabrique jamais une valeur.** Une progression de 127 % peut provenir d'une vraie progression de 27 % comme de 100 %. La plafonner à 100 reviendrait à **inventer** une donnée : on la **signale** et on la neutralise.

À l'inverse, une durée de connexion négative se **recalcule** exactement à partir des heures de connexion et de déconnexion : on la **corrige**.

### 3.2 Des corrections fondées sur d'autres données

Plusieurs corrections exploitent la redondance entre les sources ou à l'intérieur d'une même source :

| Correction | Fondement | Résultat |
|---|---|---|
| Événement MongoDB sans `student_code` | Les autres événements de **la même session** | 8 606 sur 8 606 retrouvés |
| Session Redis sans étudiant | La même session dans **MongoDB** | 10 sur 10 retrouvées |
| Compteurs Redis faux | Recalcul à partir des sessions et des événements nettoyés | 241 connectés (et non 737), 43 vidéos (et non 88) : **exactement** les valeurs réelles |
| Salaire net négatif | Formule `base + primes − retenues` | 151 corrigés |
| Durée de connexion négative | Heure de déconnexion − heure de connexion | 2 453 corrigées |

### 3.3 Catalogue et traçabilité

- **89 règles** dans `pipeline/qualite_regles.py`, chargées dans `quality.regles`. Chaque règle précise sa dimension, son action et les **anomalies du volet A qu'elle couvre**.
- **Une ligne `quality.constats` par constat** : règle, ligne source, colonne, valeur **avant**, valeur **après**, action. Chaque correction est donc **réversible et justifiable**.
- Les **référentiels** (villes, synonymes) ont été construits par **profilage** des valeurs distinctes du staging. Une valeur absente de ces listes n'est **pas devinée** : une règle « … inconnu(e) » la signale.
- **Des règles d'intégration** s'ajoutent aux anomalies du volet A :
  - 1 000 étudiants sans compte LMS ;
  - 500 comptes LMS sans inscription ;
  - 9 885 événements portant un code de contenu non résoluble (les 5 % absents de `mapping_courses.csv`).

## 4. Le rapport qualité (TP)

Lot `B20260927T100618`, 5 sources :

| Indicateur exigé par le PDF | Total |
|---|---:|
| **Lignes extraites** | 797 378 |
| **Lignes rejetées** | 25 795 |
| Lignes en couche clean | 772 432 |
| **Doublons** | 24 570 |
| **Valeurs manquantes** | 44 322 |
| **Incohérences détectées** | 103 000 |
| **Corrections effectuées** | 55 853 |

Le rapport détaille ces indicateurs **pour chacune des 21 tables**, et le nombre de constats **pour chacune des 89 règles**.

**Fraîcheur**, rapportée à la date de référence de la simulation (15/09/2026, C20) :

| Source | Dernière donnée | Interprétation |
|---|---|---|
| MySQL, MongoDB | 15/09/2026 au soir | À jour |
| CSV RH | 28/08/2026 | Dernière absence avant la date de référence ; salaires versés jusqu'en août (C20) |
| PostgreSQL | 03/05/2026 | Retard **métier** : les tranches de l'année se terminent en avril-mai |
| Redis | 15/09/2026 23:00 | L'instant de son snapshot (C24) |

La fraîcheur se juge **par rapport à l'usage** : un retard de 135 jours n'est pas un défaut pour les paiements, alors qu'il en serait un pour les connexions.

## 5. Porte G3 : toutes les anomalies sont-elles traitées ?

La porte G3 confronte **chacune des 159 946 anomalies du journal** du volet A (la vérité terrain, lue **uniquement** par ce contrôle) aux constats de l'entrepôt.

**Résultat : 159 946 / 159 946 anomalies traitées, 69 types sur 69 à 100 %.**

Chaque règle détecte **exactement** le nombre d'anomalies injectées : aucune anomalie oubliée. Les seuls constats « hors journal » viennent de règles qui signalent volontairement **les deux lignes** d'une paire (référence de paiement partagée, titre de cours dupliqué). Il n'y a donc **aucune fausse détection**.

## 6. Ce que cette phase démontre

| Idée clé | Preuve |
|---|---|
| Un ETL doit contrôler, pas seulement déplacer | 25 795 lignes rejetées et 55 853 corrections, qu'un simple déplacement aurait fait entrer dans les indicateurs |
| La qualité se mesure | Un taux par dimension et par source, à chaque lot |
| Corriger n'est pas inventer | 45 règles **signalent** au lieu de deviner |
| Tout est tracé | Valeur avant et après, règle, action : chaque chiffre du DW est justifiable |
| Les sources se corrigent mutuellement | Étudiants retrouvés par la session, compteurs Redis recalculés à l'unité près |

## Références

- PDF « BI Recherche P8 », Phase 5 (recherche et TP) ; Phase 15 (tests).
- DAMA International, *DAMA-DMBOK : Data Management Body of Knowledge* (2ᵉ éd., 2017) : dimensions de la qualité des données.
- Code : `pipeline/qualite_regles.py`, `pipeline/sql/clean/`, `pipeline/rapport_qualite.py`, `pipeline/verify_g3.py`.
