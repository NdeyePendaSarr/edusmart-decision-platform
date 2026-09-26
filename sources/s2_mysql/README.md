# Source 2 — MySQL « Plateforme pédagogique »

Base : `edusmart_learning` · Conteneur : `edusmart_mysql` (port Windows 3307) · MySQL 8.0.16+

Ce document est le **document de présentation** exigé par le cadrage (Données
EduSmart.pdf, livrable 5) : structure, relations internes, contraintes,
anomalies introduites volontairement et volume généré.

---

## 1. Fichiers livrés

| Fichier | Rôle |
|---|---|
| `create_database.sql` | Les 6 tables avec toutes leurs contraintes (CHECK actives ou `NOT ENFORCED`, clés étrangères) |
| `check_constraints.sql` | Diagnostic en lecture seule : état des contraintes, violations, catégories en comparaison exacte |
| `generate_data.py` | Contenus, activité des 9 500 comptes LMS, anomalies ; export CSV + codes + journal |
| `anomalies.py` | Catalogue, injection et **mesure** des 16 types d'anomalies (B01 à B16) |
| `insert_data.py` | `LOAD DATA LOCAL INFILE`, avec repli automatique sur des INSERT groupés ; contrôle des volumes et des avertissements |
| `verify_source.py` | Porte G1 : 45 contrôles en base + rapport Markdown |

Module commun créé pour cette source : `common/learning_catalog.py`
(catégories, thèmes, formats de codes, lien département → catégorie).

## 2. Exécution

```powershell
python -m common.referential                 # si pas déjà fait (L1)
python -m sources.s2_mysql.generate_data     # ~10 s, aucun besoin de Docker
python -m sources.s2_mysql.insert_data       # ~15 s, conteneur mysql démarré
python -m sources.s2_mysql.verify_source     # porte G1 -> data/reports/s2_mysql_G1.md
```

**Repli sur des INSERT groupés.** Si `LOAD DATA LOCAL` est refusé, le script bascule
automatiquement sur des INSERT groupés (message `repli sur INSERT groupés`). On peut
aussi forcer ce mode avec `--force-inserts`. Le résultat est identique ; seul le temps
de chargement change légèrement.

## 3. Structure et relations

```
modules (300) 1──< cours (~800) 1──< quiz (~1 000) 1──< notes (~300 000)
     1
     └──< progression (~60 000)          temps_connexion (~60 000) : aucune FK (PDF)

notes, progression, temps_connexion : student_code (LMS-XXXXXX), SANS table étudiant
```

| Table | Clé primaire | Clé étrangère | Remarque |
|---|---|---|---|
| modules | id_module CHAR(36) | — | code_module UNIQUE (format `MOD-IA-01`) |
| cours | id_cours | id_module → modules | — |
| quiz | id_quiz | id_cours → cours | — |
| notes | id_note | id_quiz → quiz | student_code (pas d'id_etudiant, conformément au PDF) |
| progression | id_progression | id_module → modules | dernier_cours sans FK (non prévue par le PDF) |
| temps_connexion | id_connexion | — | — |

**Adaptations de types MySQL :**
- UUID → `CHAR(36)` ;
- BOOLEAN → `TINYINT(1)` ;
- NUMERIC → `DECIMAL` ;
- les `TIMESTAMP` sont conservés, conformément au PDF.

## 4. Contraintes : différences avec PostgreSQL

| Contrainte | Règle | État | Pourquoi |
|---|---|---|---|
| ck_quiz_duree | durée > 0 | **NOT ENFORCED** | Anomalie B04 |
| ck_progression_pourcentage | entre 0 et 100 | **NOT ENFORCED** | Anomalies B05, B06 |
| ck_temps_connexion_duree | durée ≥ 0 | **NOT ENFORCED** | Anomalie B09 |
| ck_modules_duree, ck_cours_ordre, ck_cours_duree, ck_quiz_nb_questions, ck_quiz_score_max, ck_notes_score | règles du PDF | ENFORCED | Aucune anomalie |
| fk_cours_module, fk_quiz_cours, fk_notes_quiz, fk_progression_module | intégrité | Déclarées | Orphelins B07 chargés avec `FOREIGN_KEY_CHECKS = 0` |
| « Une seule progression par étudiant et par module » | règle métier du PDF | Index **non unique** | Doublons B15 volontaires |

**À retenir pour la soutenance :**

| | PostgreSQL `NOT VALID` | MySQL `NOT ENFORCED` |
|---|---|---|
| Lignes existantes | Non vérifiées | Non vérifiées |
| **Nouvelles lignes** | **Vérifiées** | **Non vérifiées** |

MySQL n'offre pas l'équivalent de `NOT VALID` pour les CHECK. Les tests d'intégration
démontrent les deux comportements.

**Piège de la collation.** `utf8mb4_unicode_ci` ignore la casse et les accents :
- `GROUP BY categorie` **fusionne** `Data`, `DATA` et `data`, et cache donc l'anomalie B01 ;
- un `WHERE` sur `student_code` retrouverait `lms-000154`.

`check_constraints.sql` utilise `COLLATE utf8mb4_bin` et `REGEXP_LIKE(..., 'c')` pour
comparer exactement. L'ETL devra en tenir compte.

## 5. Anomalies volontaires

Chaque type touche entre 2 % et 5 % de sa table. Le journal est dans
`data/anomalies/s2_mysql_anomalies.csv` et n'est **jamais lu par l'ETL**.

| Code | Table.colonne | Anomalie | Exemple | Nb (graine 2026) | Taux |
|---|---|---|---|---:|---:|
| B01 | modules.categorie | Écriture variable | `DATA`, `data science`, `Reseaux`, `Mgmt` | 11 | 3,67 % |
| B02 | modules.actif | Module inactif, mais encore suivi | `0` | 13 | 4,33 % |
| B03 | cours.titre | Titre en double | 2 cours, même titre | 18 | 2,26 % |
| B04 | quiz.duree_minutes | Durée incohérente | `0`, 1 min pour 20 questions, 600 min | 24 | 2,44 % |
| B05 | progression.pourcentage | > 100 % | `127.40` | 1 636 | 2,87 % |
| B06 | progression.pourcentage | Négative | `-12.35` | 1 544 | 2,71 % |
| B07 | progression.id_module | Module inexistant | UUID inconnu | 1 775 | 3,12 % |
| B08 | temps_connexion.date_deconnexion | Connexion sans fin | NULL (durée NULL aussi) | 1 658 | 2,67 % |
| B09 | temps_connexion.duree_minutes | Durée négative | `-35` | 2 453 | 3,95 % |
| B10 | temps_connexion.adresse_ip | IP invalide | `312.4.8.1`, `10.2.3`, `abc.def.ghi.jkl` | 1 929 | 3,10 % |
| B11 | temps_connexion.appareil | Écriture variable | `mobile`, `Téléphone`, `pc`, `Tablet` | 2 675 | 4,30 % |
| B12 | notes | Résultat en double | même contenu, autre id | 7 438 | 2,55 % |
| B13 | notes.student_code | Format incompatible | `LMS000154`, `lms-000154`, `LMS-154` | 7 721 | 2,65 % |
| B14 | notes.score | Score > score maximal | `24.50` sur 20 | 14 473 | 4,96 % |
| B15 | progression | Deux progressions (étudiant, module) | — | 2 003 | 3,52 % |
| B16 | temps_connexion.navigateur | Navigateur manquant | NULL | 1 304 | 2,10 % |

**Total : 46 675 anomalies journalisées.** Chacune est recomptée en base, et la mesure
est égale au journal pour les 16 types.

**Correspondance avec la liste du PDF :**
- catégories → B01 ;
- modules inactifs → B02 ;
- doublons de titres → B03 ;
- durées de quiz → B04 ;
- progressions > 100 % → B05 ;
- valeurs négatives → B06 ;
- modules inexistants → B07 ;
- connexions sans déconnexion → B08 ;
- durées négatives → B09 ;
- IP invalides → B10 ;
- appareils → B11 ;
- doublons → B12, B15 ;
- identifiants incompatibles → B13, en plus de l'incompatibilité **structurelle** (`student_code` au lieu d'un UUID, 500 comptes LMS absents de PostgreSQL) ;
- incohérences → B14 ;
- valeurs manquantes → B08, B16.

## 6. Correspondance des codes de contenus

MongoDB et Redis désignent les contenus par des codes (`COURSE-15`, `QUIZ-3`), qui
n'existent pas dans MySQL (le PDF ne prévoit pas de colonne code pour les cours et les quiz).

| Fichier | Contenu | Lecteur |
|---|---|---|
| `mappings/mapping_courses.csv` | 300 modules + 758 cours + 936 quiz = **1 994 codes** | Pipeline ETL |
| `data/referential/referentiel_contenus.csv` | Les 2 083 codes (100 %) | Générateurs MongoDB et Redis, tests. **Jamais l'ETL** |

**5 % des cours et des quiz sont absents du mapping** (40 cours, 49 quiz), comme c'était
décidé : leurs codes apparaîtront dans MongoDB et Redis sans pouvoir être résolus. Ces
absences se découvrent par anti-jointure, comme les étudiants non rapprochés. La colonne
`statut_correspondance` (définie en L1) vaut donc toujours `APPARIE`.

**Rapprochement des étudiants avec PostgreSQL.** Il n'existe **aucun lien direct** :
MySQL connaît `student_code`, PostgreSQL connaît `id_etudiant` et `matricule`.
Le lien passe par `mapping_etudiants.csv` (9 000 paires).

## 7. Conventions et écarts assumés

| # | Sujet | Choix | Justification |
|---|---|---|---|
| S2-01 | Types | CHAR(36), TINYINT(1), DECIMAL | Validé (Étape 1) |
| S2-02 | CHECK | NOT ENFORCED seulement si une anomalie les viole | Même logique que la Source 1 |
| S2-03 | Unicité (étudiant, module) | Index non unique | Doublons B15 volontaires |
| S2-04 | Anomalies B12 à B16 | Ajoutées au titre des « Contraintes générales » du PDF | Doublons, identifiants incompatibles, incohérences, valeurs manquantes |
| S2-05 | Catégories | 8 catégories canoniques (Développement, Data, IA, Réseaux, Cybersécurité, Management, Finance, Marketing) | PDF : « Développement, Data, IA... » ; une catégorie par département de la Source 1 |
| S2-06 | Modules | 13 thèmes × 3 niveaux par catégorie ; nom `Thème - Niveau` ; code `MOD-XXX-NN` | Format de l'exemple MongoDB `MOD-IA-01` |
| S2-07 | Cours et quiz | 1 à 5 cours par module ; 0 à 2 quiz par cours ; score maximal 20 (70 %), 10 ou 100 | Volumes validés |
| S2-08 | Lien avec la filière | 70 % des modules d'un étudiant dans la catégorie de son département | Cohérence inter-sources, utile pour l'analyse |
| S2-09 | Fenêtre d'activité | De la rentrée d'entrée jusqu'à la fin du parcours (diplôme, abandon après ~4 mois, ou date de référence) | Cohérence avec les statuts de la Source 1 |
| S2-10 | Date de référence | **15/09/2026** : aucune activité après | Date fixe pour la reproductibilité ; cohérente avec les exemples MongoDB et Redis (convention C20) |
| S2-11 | Notes | Score selon le niveau de l'étudiant + progrès par tentative ; validé si ≥ 50 % du score maximal (10/20) ; jusqu'à 5 tentatives ; 65 % repassent un quiz réussi pour améliorer leur note | Volume de ~300 000 notes |
| S2-12 | Progression | 33 % terminées (100 %), 57 % partielles, 10 % à peine commencées ; quiz passés au prorata | Réalisme |
| S2-13 | Connexions | 2 à 11 par compte ; durée médiane ~28 min ; Mobile 55 % / PC 35 % / Tablette 10 % | Volume validé ; usage mobile au Sénégal |
| S2-14 | Adresses IP | Faker `ipv4_public` (90 %) et `ipv6` (10 %) | Utilisation de Faker |
| S2-15 | mapping_courses | 5 % des cours et quiz absents ; `statut_correspondance` = APPARIE | Décision validée ; même logique que mapping_etudiants |

## 8. Volumes obtenus (graine 2026)

| Table | Lignes | Cible validée | Écart |
|---|---:|---|---:|
| modules | 300 | 300 | 0 |
| cours | 798 | ~800 | −0,2 % |
| quiz | 985 | ~1 000 | −1,5 % |
| notes | 299 049 (dont 7 438 doublons) | ~300 000 | −0,3 % |
| progression | 58 944 (dont 2 003 doublons) | ~60 000 | −1,8 % |
| temps_connexion | 62 142 | ~60 000 | +3,6 % |

**Indicateurs (données propres) :**
- 74 % de quiz validés ;
- progression moyenne de 65 % ;
- tentatives : 1 (122 651), 2 (89 362), 3 (55 594), 4 (24 693), 5 (6 749) ;
- notes datées du 01/10/2023 au 15/09/2026.

## 9. Porte G1

`verify_source.py` exécute **45 contrôles** :

| Groupe | Contrôles |
|---|---|
| V1 Volumes | 6 tables (modules exact, les autres à ±5 %) |
| V2 Anomalies | 16 types : mesure en base = journal, taux dans [2 %, 5 %] |
| V3 Contraintes | 9 CHECK (6 ENFORCED, 3 NOT ENFORCED) + 4 FK déclarées |
| V4 Relations | Aucun orphelin, sauf les progressions B07 |
| V5 Identifiants | 9 500 comptes LMS exactement (dont les 500 orphelins), une progression par compte au minimum, mapping_etudiants trouvé en base, mapping_courses valide (identifiants existants, codes uniques, 100 % des modules, 95 % des cours et quiz) |

## 10. Tests

| Fichier | Portée |
|---|---|
| `tests/test_s2_mysql.py` | 30 tests sans base : données propres, fenêtres d'activité, lien avec la filière, codes, anomalies, CSV, découpage SQL, reproductibilité |
| `tests/test_learning_catalog.py` | 4 tests sur le catalogue |
| `tests/test_s2_mysql_integration.py` | 5 tests sur une vraie base : G1, CHECK actif, NOT ENFORCED, FK, rechargement idempotent |

Le test d'intégration est désactivé par défaut, car il **recharge la base** :

```powershell
$env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s2_mysql_integration.py -v
```
