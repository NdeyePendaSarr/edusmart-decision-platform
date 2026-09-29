# Phase 13 — Power BI

*EduSmart Decision Platform · Lot L8 · Étape 6 du module BI*

> **PDF :** créer le modèle relationnel, les mesures, les KPI, les segments, les filtres, les visualisations, le tableau de bord interactif.
>
> Mode opératoire : [`powerbi/guide_powerbi.md`](../powerbi/guide_powerbi.md) · mesures : [`powerbi/mesures_kpi.dax`](../powerbi/mesures_kpi.dax) · contrôle : `scripts/verifier_g5b.py`.

---

## 1. Le modèle relationnel

Power BI importe les 15 tables du schéma `dw` (7 dimensions, 8 faits) et reproduit la **constellation** de la Phase 8. Les 26 relations sont de cardinalité **plusieurs à un**, filtrent **de la dimension vers le fait**, et sont toutes actives.

**Deux adaptations par rapport au DW, et pourquoi :**

| Dans le DW (L6) | Dans Power BI | Raison |
|---|---|---|
| `dim_quiz` → `dim_module` (branche en flocon) | **Supprimée** | Les faits portent déjà `module_key`. Deux chemins vers le module rendraient le filtrage **ambigu**, et Power BI désactiverait arbitrairement l'un des deux. Le modèle Power BI est une constellation d'**étoiles pures** |
| `dim_etudiant.region_key` | **Relation supprimée** (la colonne reste) | Les faits portent la région **à la date du fait** (SCD 2). C'est elle qui fait foi : le paiement de 2024 reste attribué à la région de 2024 |
| Ligne « Inconnu » (−1) de `dim_temps` (1900) | **Filtrée** dans Power Query | Pour marquer `dim_temps` comme table de dates, les dates doivent être contiguës. Aucun fait n'utilise −1 (porte G4.6) |

**Pas de filtrage bidirectionnel.** Avec 8 faits qui partagent `dim_etudiant`, un filtre remontant d'un fait vers une dimension se propagerait aux 7 autres faits : les résultats dépendraient du visuel où l'on clique.

## 2. Mesures ou colonnes calculées ?

| | **Mesure** (DAX) | **Colonne calculée** |
|---|---|---|
| Calculée | Au moment de l'affichage, **dans le contexte du filtre** | Au chargement, une fois par ligne |
| Stockage | Aucun | En mémoire |
| Usage | Tout ce qui s'**agrège** : taux, sommes, médianes | Ce qui **catégorise** une ligne : tranche de score, libellé |

**Les 8 KPI sont des mesures.** Un taux de recouvrement ne s'additionne pas d'une ligne à l'autre : il se **recalcule** pour chaque sélection (une région, une année, une filière). Une colonne calculée donnerait un taux figé, faux dès qu'on filtre.

**Aucune colonne calculée n'est nécessaire** : les indicateurs par ligne (`montant_ca`, `est_abandon`, `score_sur_20`, `est_termine`…) ont été calculés **une fois, dans le DW** (L6). Le calcul se fait au plus près des données, et une seule fois.

Les mesures se répartissent en deux familles (`mesures_kpi.dax`) : les **8 KPI** (Phase 11), puis les **mesures d'appui** aux visuels. Ces dernières sont des métriques : impayés, tentatives, heures connectées…

## 3. Les KPI dans le tableau de bord

- Une **carte** par KPI, en tête de la page « Vue Direction ».
- **Mise en forme conditionnelle** d'après les cibles proposées en L7 (`[Cible recouvrement]`, `[Cible abandon]`) : l'écart saute aux yeux.
- La **Satisfaction** a sa carte, qui affiche « Non mesurée : aucune source ». Un manque de données visible vaut mieux qu'une case absente, qui laisserait croire qu'on l'a oubliée.

## 4. Segments et filtres

| Outil | Qui l'utilise | Niveau | Usage EduSmart |
|---|---|---|---|
| **Segment** | Le décideur, sur la page | Visible, interactif | Année académique, région, niveau, catégorie |
| **Filtre de visuel** | Le concepteur | Un seul visuel | « 10 premières filières par impayés » |
| **Filtre de page** | Le concepteur | Toute la page | Une page RH limitée aux enseignants permanents |
| **Filtre de rapport** | Le concepteur | Toutes les pages | Aucun : les données sont déjà propres (L5) |

**Le piège des deux « années académiques ».**
- `dim_formation[annee_academique]` est l'année **de la formation payée**. Elle sert au CA et au recouvrement, conformément à la définition L7.
- `dim_temps[annee_academique]` est l'année **de la date de l'événement**. Elle sert aux connexions et aux notes.

Utiliser la seconde sur la page Finance ferait réapparaître l'année « 2022-2023 » fictive (les acomptes d'été). Chaque page utilise donc **explicitement** la bonne colonne.

## 5. Interactivité

| Mécanisme | Usage |
|---|---|
| **Filtrage croisé** | Un clic sur une région filtre les autres visuels de la page |
| **Modifier les interactions** | Les cartes KPI de la page 1 **ne** sont **pas** filtrées par ce clic : les chiffres globaux restent visibles pendant l'exploration |
| **Drill down** (hiérarchies) | Géographie (région › ville), Calendrier (année › trimestre › mois), Offre (département › filière › classe) : les opérations de la Phase 10, en un clic |
| **Segments synchronisés** | Région et niveau conservés entre les pages Direction et Finance |

## 6. Le tableau de bord

| Page | Question du décideur | Visuels principaux |
|---|---|---|
| **Vue Direction** | Où en sommes-nous ? | 8 cartes KPI + Satisfaction, CA et montant dû par année, CA par région |
| **Finance** | L'argent rentre-t-il ? | Courbe mensuelle (saisonnalité), carte de chaleur du recouvrement (filière × année), Top 10 des impayés |
| **Pédagogie** | Les étudiants apprennent-ils ? | Histogramme des scores, carte de chaleur catégorie × niveau, nuage tentatives × score |
| **Engagement** | Sont-ils présents ? | Carte de chaleur jour × heure, boxplot par appareil, étudiants actifs |
| RH (facultative) | Masse salariale et absences | Courbe, barres par motif |
| Contrôle G5b (masquée) | Les mesures sont-elles justes ? | Tableau des 8 mesures, 6 décimales |

**Principes de mise en page :**
- une page = une question ;
- lecture en « Z » : KPI en haut, détail en bas ;
- 6 visuels au maximum par page ;
- titres qui énoncent la conclusion ;
- une couleur d'accent réservée à ce qui s'écarte de la cible.

## 7. Porte G5b

Chaque mesure DAX, **sans filtre**, doit retrouver la valeur SQL de référence (`kpi_reference.json`, validée par G5a en L7). `scripts/verifier_g5b.py` compare les valeurs recopiées depuis Power BI, avec des tolérances explicites :
- le centime pour le CA ;
- l'exactitude pour les effectifs et la médiane ;
- 10⁻⁶ pour les ratios.

Le fichier de saisie ne contient pas les valeurs attendues : la saisie reste « à l'aveugle ».

La chaîne de confiance est alors complète : **SQL (DW) = Python (clean) = DAX (Power BI)**, soit trois langages et trois couches pour les mêmes 8 chiffres.

## Références

- PDF « BI Recherche P8 », Phase 13.
- M. Russo et A. Ferrari, *The Definitive Guide to DAX*, 2ᵉ éd. (2019) : contexte de filtre, mesures ou colonnes calculées.
- Microsoft Learn, *Modélisation en schéma en étoile dans Power BI* : relations, cardinalité, direction du filtrage.
