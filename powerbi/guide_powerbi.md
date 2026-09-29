# Guide Power BI — Tableau de bord EduSmart

*Lot L8 · Phase 13 · à suivre dans l'ordre. Durée estimée : 3 à 4 heures pour une première construction.*

Justification des choix : [`docs/12_visualisations.md`](../docs/12_visualisations.md) (graphiques) et [`docs/13_powerbi.md`](../docs/13_powerbi.md) (modèle, segments, filtres).

---

## 0. Prérequis

| Élément | Vérification |
|---|---|
| Power BI Desktop (Windows, version récente) | Microsoft Store ou microsoft.com/power-bi |
| DW chargé et KPI calculés | `python -m pipeline.run_pipeline` : code 0, G5a 8/8 |
| Valeurs de référence | `data/reports/kpi_reference.json` existe |
| Identifiants du DW | `docker/.env` : utilisateur `PG_DW_USER` (par défaut `edusmart_dw`), mot de passe `PG_DW_PASSWORD` |

---

## 1. Connexion à l'entrepôt

1. **Accueil › Obtenir des données › Base de données PostgreSQL**.
2. Serveur : `localhost:5434` · Base de données : `edusmart_dw` · Mode : **Importer**.
   L'import est préférable au DirectQuery : environ 500 000 lignes tiennent en mémoire, et DirectQuery limite le DAX et ralentit les visuels.
3. Identifiants : onglet **Base de données**, utilisateur et mot de passe de `docker/.env`.

> ⚠️ **Erreur SSL ou de certificat** : le PostgreSQL de Docker n'utilise pas SSL. Allez dans **Fichier › Options et paramètres › Paramètres de la source de données**, sélectionnez la source, cliquez sur **Modifier les autorisations** et décochez **Chiffrer les connexions**.

4. Dans le navigateur, cochez les **15 tables** du schéma `dw` :
   - `dim_temps`, `dim_etudiant`, `dim_formation`, `dim_module`, `dim_quiz`, `dim_enseignant`, `dim_region` ;
   - `fact_paiements`, `fact_inscriptions`, `fact_notes`, `fact_quiz_activite`, `fact_connexions`, `fact_progression`, `fact_salaires`, `fact_absences` ;
   - facultatif : `v_kpi`, pour la page de contrôle G5b (§ 7).

   Ne cochez pas `cube_*` : Power BI refait lui-même les agrégations.
5. Cliquez sur **Transformer les données** (et non « Charger »).

## 2. Power Query : préparer les tables

| # | Action | Pourquoi |
|---|---|---|
| 2.1 | **Renommer chaque requête** sans le préfixe : `dw dim_temps` devient `dim_temps`, et ainsi de suite pour les 15 | Les mesures de `mesures_kpi.dax` utilisent ces noms exacts |
| 2.2 | `dim_temps` : filtrer `date_key` ≠ **-1** | La ligne « Inconnu », datée du 01/01/1900, crée un trou de 123 ans : Power BI refuserait de la marquer comme table de dates. Aucun fait ne pointe vers -1 (porte G4.6) |
| 2.3 | `dim_temps` : ajouter une colonne « Mois (année académique) » = copie de `libelle_mois` | Elle sera triée d'octobre à septembre (§ 4.2) |
| 2.4 | Vérifier les types : `date_complete` en **Date** ; montants en **Nombre décimal fixe** ; `est_*` en **Nombre entier** ; `est_courant` et `actif` en **Vrai/Faux** | Des types faux faussent les agrégations |
| 2.5 | **Fermer et appliquer** | |

## 3. Le modèle relationnel

Ouvrez la **vue Modèle**. Power BI a pu détecter automatiquement des relations d'après les noms de colonnes.

### 3.1 Supprimer deux relations (sinon, chemins de filtrage ambigus)

| Relation à supprimer | Raison |
|---|---|
| `dim_quiz[module_key]` → `dim_module` | Les faits `fact_notes` et `fact_quiz_activite` portent **déjà** `module_key`. Avec cette relation, deux chemins mèneraient au module, et Power BI désactiverait l'un des deux au hasard |
| `dim_etudiant[region_key]` → `dim_region` | Les faits portent `region_key` : la région **à la date du fait** (SCD 2). Passer par `dim_etudiant` donnerait un second chemin, et un autre sens |

La branche en flocon `dim_quiz` → `dim_module` reste dans le DW (L6) ; dans Power BI, on « aplatit » le modèle en étoiles.

### 3.2 Les 26 relations à obtenir

Toutes de cardinalité **plusieurs à un (\*:1)**, en filtrage croisé **unique** (de la dimension vers le fait), et **actives**.

| Fait | Colonnes → dimension |
|---|---|
| `fact_paiements` | `date_key` → `dim_temps` · `etudiant_key` → `dim_etudiant` · `formation_key` → `dim_formation` · `region_key` → `dim_region` |
| `fact_inscriptions` | `date_key` · `etudiant_key` · `formation_key` · `region_key` (mêmes dimensions) |
| `fact_notes` | `date_key` · `etudiant_key` · `quiz_key` → `dim_quiz` · `module_key` → `dim_module` |
| `fact_quiz_activite` | `date_key` · `etudiant_key` · `quiz_key` · `module_key` · `region_key` |
| `fact_connexions` | `date_key` · `etudiant_key` |
| `fact_progression` | `date_key` · `etudiant_key` · `module_key` |
| `fact_salaires` | `date_key` · `enseignant_key` → `dim_enseignant` |
| `fact_absences` | `date_key` · `enseignant_key` |

Toute relation manquante se crée en faisant glisser la colonne du fait sur la clé de la dimension.

> **Pas de filtrage bidirectionnel.** Il créerait des ambiguïtés entre les 8 faits, et un segment sur un fait filtrerait les autres de façon imprévisible.

## 4. Réglages du modèle

### 4.1 Table de dates
Sélectionnez `dim_temps`, puis **Outils de table › Marquer comme table de dates**, colonne `date_complete`.

### 4.2 Tris
| Colonne | Trier par |
|---|---|
| `dim_temps[libelle_mois]` | `mois` |
| `dim_temps[Mois (année académique)]` | `mois_academique` (octobre = 1) |
| `dim_temps[libelle_jour]` | `jour_semaine` |

### 4.3 Hiérarchies (clic droit sur la colonne de tête › Créer une hiérarchie)
| Table | Hiérarchie | Niveaux |
|---|---|---|
| `dim_temps` | Calendrier | `annee` › `trimestre` › `libelle_mois` › `date_complete` |
| `dim_temps` | Année académique | `annee_academique` › `trimestre_academique` › `Mois (année académique)` |
| `dim_region` | Géographie | `region` › `ville` |
| `dim_formation` | Offre diplômante | `departement` › `nom_filiere` › `nom_classe` |
| `dim_module` | Offre en ligne | `categorie` › `nom_module` |

### 4.4 Masquer les colonnes techniques (vue Rapport)
Toutes les colonnes `*_key`, les identifiants (`id_*`, `event_id`, `etudiant_id`…) et les colonnes de validité SCD 2 (`date_debut`, `date_fin`, `version`). L'utilisateur ne voit ainsi que des colonnes métier.

## 5. Les mesures

1. **Accueil › Entrer des données** : créez une table vide nommée `Mesures`, puis supprimez sa colonne une fois des mesures ajoutées. Toutes les mesures y sont rangées, à l'écart des tables.
2. Pour chaque mesure de [`mesures_kpi.dax`](mesures_kpi.dax) : **Nouvelle mesure**, puis collez la définition, **sans les commentaires `//`**.
3. Formats :

| Mesure | Format |
|---|---|
| CA encaissé, Montant dû, Impayés, Masse salariale nette | Nombre entier, séparateur de milliers (ou « M » en affichage) |
| Taux de recouvrement, de réussite, d'abandon, de validation, Part des étudiants actifs | Pourcentage, 2 décimales |
| Progression moyenne | Nombre décimal, 2 décimales (c'est déjà un pourcentage de 0 à 100) |
| Temps médian de connexion (min), Score moyen sur 20 | Nombre décimal, 1 décimale |
| Étudiants actifs (30 j), Nombre réel d'étudiants, Connexions… | Nombre entier |

## 6. Les pages du tableau de bord

Chaque page répond à **une** question de décideur. Les segments sont en haut ; on lit les visuels de gauche à droite et de haut en bas.

### Page 1 — « Vue Direction » : où en sommes-nous ?
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Segments : Année académique (dim_formation) · Région · Niveau                │
├─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬────────┤
│ CA      │Recouvr. │Réussite │Abandon  │Progress.│ Actifs  │Connexion│Étudiants│  ← 8 cartes KPI
├─────────┴─────────┴─────────┴─────────┴───┬─────┴─────────┴─────────┴────────┤
│ Histogramme groupé : CA et Montant dû     │ Carte « Satisfaction :           │
│ par année académique                      │ Non mesurée : aucune source »    │
├───────────────────────────────────────────┴──────────────────────────────────┤
│ Barres horizontales : CA par région (triées ; drill down région › ville)     │
└──────────────────────────────────────────────────────────────────────────────┘
```
- **Cartes** avec mise en forme conditionnelle (§ 8) : rouge si Abandon > [Cible abandon], vert si Recouvrement ≥ [Cible recouvrement].
- La carte **Satisfaction** affiche la mesure texte : elle rend le manque de données **visible** au lieu de le cacher.

### Page 2 — « Finance » : l'argent rentre-t-il ?
- **Graphique en courbes** : CA encaissé par `dim_temps[Calendrier]` (mois). Il montre la saisonnalité des trois tranches (Phase 10, roll up).
- **Matrice avec carte de chaleur** : Taux de recouvrement, `dim_formation[nom_filiere]` en lignes, `annee_academique` en colonnes, couleur d'arrière-plan conditionnelle.
- **Barres horizontales** : Impayés par filière (Top 10, filtre de visuel **N premiers**).
- **Tableau** : Paiements négatifs (exclus du CA) par mode de paiement, pour la transparence de la définition du CA.

### Page 3 — « Pédagogie » : les étudiants apprennent-ils ?
- **Histogramme des scores** : graphique en colonnes sur `fact_notes[score_sur_20]` **compartimenté**. Clic droit sur la colonne › Nouveau groupe › Compartiments, taille 1. En axe : le compartiment ; en valeur : Tentatives.
- **Carte de chaleur** : matrice `dim_module[categorie]` × `dim_module[niveau]`, valeur « Taux de validation par tentative », arrière-plan conditionnel.
- **Nuage de points** : un point par étudiant (champ **Valeurs** = `dim_etudiant[etudiant_id]`), X = Tentatives, Y = Score moyen sur 20.
- **Carte** : Taux de réussite (le KPI), à côté du taux par tentative, pour la leçon « KPI ou métrique ».

### Page 4 — « Engagement » : les étudiants sont-ils présents ?
- **Carte de chaleur** : matrice `dim_temps[libelle_jour]` × `fact_connexions[heure]`, valeur Connexions.
- **Boîte à moustaches** : durée de connexion par appareil. Power BI **n'a pas** de boxplot natif : importez le visuel certifié **« Box and Whisker chart »** depuis l'AppSource (Visuels › Obtenir plus de visuels). À défaut, utilisez un visuel Python (voir `docs/12_visualisations.md`).
- **Cartes** : Étudiants actifs (30 j), Part des étudiants actifs, Temps médian de connexion (min).
- **Courbe** : Connexions par mois.

### Page 5 (facultative) — « RH »
Masse salariale nette par mois (courbe) ; Heures d'absence par motif (barres) ; segment `dim_enseignant[grade]`.

### Page « Contrôle G5b » (masquée) — voir § 7

## 7. Porte G5b : les mesures DAX retrouvent les KPI SQL

1. Créez une page **« Contrôle G5b »**, sans aucun segment ni filtre.
2. Ajoutez un visuel **Tableau** contenant les 8 mesures KPI.
3. Pour cette page seulement, formatez chaque mesure en **Nombre décimal, 6 décimales**, et non en pourcentage.
4. Dans un terminal : `python -m scripts.verifier_g5b --modele` crée `powerbi/g5b_valeurs_powerbi.csv`.
5. Recopiez dans la colonne `valeur_powerbi` la valeur affichée pour chaque mesure. Par exemple `0,901016` pour le recouvrement ou `13553901000` pour le CA ; virgule ou point acceptés.
6. `python -m scripts.verifier_g5b` compare aux valeurs de `kpi_reference.json` et écrit `data/reports/G5b.md`.
7. Masquez la page (clic droit sur l'onglet › Masquer la page).

Tolérances : le centime pour le CA ; exact pour les effectifs et la médiane ; 10⁻⁶ pour les ratios et les moyennes.

**En cas d'écart**, dans l'ordre :
1. un filtre oublié sur la page ;
2. une table mal renommée (§ 2.1) ;
3. une relation manquante ou en trop (§ 3) ;
4. la ligne −1 de `dim_temps` supprimée alors qu'un fait la référence (impossible si G4 = 57/57).

## 8. Segments, filtres et interactions

| Élément | Réglage |
|---|---|
| **Année académique** | ⚠️ Pour les pages Direction et Finance, utilisez **`dim_formation[annee_academique]`** (l'année de la formation payée : définition du CA en L7). Pour les pages Pédagogie et Engagement, utilisez **`dim_temps[annee_academique]`** (la date de l'activité). Ce ne sont pas les mêmes années |
| Synchronisation | **Affichage › Synchroniser les segments** : Région et Niveau, synchronisés entre les pages 1 et 2 |
| Filtres de rapport | Aucun (tout est déjà propre dans le DW) |
| Filtres de page ou de visuel | « N premiers » pour les classements (Top 10) |
| Interactions | **Format › Modifier les interactions** : sur la page 1, un clic sur une région filtre les autres visuels mais **pas** les cartes KPI (les chiffres globaux restent visibles) |
| Mise en forme conditionnelle | Cartes KPI : couleur de la valeur par règles, à partir des mesures de cible |

## 9. Enregistrer

- Fichier : `powerbi/EduSmart.pbix`.
- Le `.pbix` ne contient pas le mot de passe, qui est stocké dans les paramètres de Power BI, sur ta machine. Il peut être versionné dans Git ; au-delà de 50 Mo, préfère Git LFS.
- Exporter une version PDF des pages pour le rapport : **Fichier › Exporter › PDF**.
