# EduSmart Decision Platform

Plateforme décisionnelle construite à partir de **5 sources de données hétérogènes**
(PostgreSQL, MySQL, CSV, MongoDB, Redis) : pipeline **ELT**, Data Warehouse PostgreSQL
en couches, modèle en **constellation de faits**, KPI et tableau de bord **Power BI**.

Projet du module *Business Intelligence et Analyse Décisionnelle*.
Les PDF du projet sont la seule source de vérité. Tout écart est tracé dans le
[registre des conventions](#7-registre-des-conventions-et-écarts-assumés).

---

## 1. État d'avancement

| Lot | Contenu | État |
|---|---|---|
| L0 | Infrastructure Docker, configuration, journalisation | Validé (G0 : 5/5) |
| L1 | Référentiel maître, données sénégalaises, correspondances | Livré |
| L2-a | Source 1 : PostgreSQL | Validé (G1 : 39/39) ([détails](sources/s1_postgresql/README.md)) |
| L2-b | Source 2 : MySQL | Validé (G1 : 45/45) ([détails](sources/s2_mysql/README.md)) |
| L2-c | Source 3 : CSV RH | Validé (G1 : 50/50) ([détails](sources/s3_csv/README.md)) |
| L2-d | Source 4 : MongoDB | Livré, en attente de G1 ([détails](sources/s4_mongodb/README.md)) |
| L2-e | Source 5 : Redis | À venir |
| L3 à L10 | Plateforme BI (phases 1 à 18) | À venir |

## 2. Arborescence actuelle

```
edusmart-decision-platform/
├── docker/
│   ├── docker-compose.yml        6 services (5 bases + Adminer)
│   ├── .env.example              modèle de configuration (à copier en .env)
│   └── init/pg_dw/01_create_schemas.sql
├── common/
│   ├── academic_catalog.py       départements, 25 filières, vivier de 120 enseignants
│   ├── anomaly_journal.py        journal des anomalies injectées (toutes sources)
│   ├── config.py                 configuration centralisée
│   ├── learning_catalog.py       catégories, thèmes et codes des contenus pédagogiques
│   ├── logger.py                 journalisation console + fichier
│   ├── seed.py                   graine et générateurs reproductibles
│   ├── senegalese_data.py        noms, 14 régions, villes, téléphone +221
│   └── referential.py            référentiel maître + correspondances
├── scripts/check_infrastructure.py   point de contrôle G0
├── sources/
│   ├── s1_postgresql/            Source 1 : SQL, génération, insertion, vérification G1
│   ├── s2_mysql/                 Source 2 : idem pour MySQL
│   ├── s3_csv/                   Source 3 : schéma, génération, vérification G1 + output/*.csv (livrés)
│   └── s4_mongodb/               Source 4 : validateur, génération, insertion, vérification G1
├── mappings/
│   ├── mapping_etudiants.csv     9 000 paires matricule <-> student_code
│   └── mapping_courses.csv       codes MODULE / COURSE-n / QUIZ-n <-> UUID MySQL (rempli en L2-b)
├── data/                         GÉNÉRÉ, non versionné :
│   ├── referential/              référentiel maître caché
│   ├── generated/<source>/       CSV intermédiaires + summary.json
│   ├── anomalies/                journaux d'anomalies (vérité terrain)
│   └── reports/                  rapports des portes G1
├── tests/                        163 tests unitaires + 16 tests d'intégration
├── requirements.txt
└── pytest.ini
```

## 3. Prérequis (Windows)

| Outil | Version | Remarque |
|---|---|---|
| Docker Desktop | récent, moteur WSL 2 | Doit être démarré avant `docker compose` |
| Python | 3.11 ou 3.12 | Cocher « Add Python to PATH » à l'installation |
| Power BI Desktop | récent | Connecteur PostgreSQL intégré |
| Git | récent | Recommandé |

## 4. Installation et démarrage

Toutes les commandes sont à lancer dans **PowerShell**, depuis la racine du projet.

```powershell
# 1. Configuration : copier le modèle puis REMPLACER les mots de passe « change_me_... »
Copy-Item docker\.env.example docker\.env
notepad docker\.env

# 2. Démarrage des conteneurs
cd docker
docker compose up -d
docker compose ps          # attendre l'état « healthy » pour chaque service (~30 s pour MySQL)
cd ..

# 3. Environnement Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # si refusé : Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

# 4. Point de contrôle G0
python -m scripts.check_infrastructure

# 5. Référentiel maître (L1)
python -m common.referential

# 6. Tests unitaires
python -m pytest
```

### Services et ports

| Service | Conteneur | Port Windows | Base | Rôle |
|---|---|---|---|---|
| pg_source | edusmart_pg_source | 5435 | edusmart_academic | Source 1 |
| pg_dw | edusmart_pg_dw | 5434 | edusmart_dw | Data Warehouse |
| mysql | edusmart_mysql | 3307 | edusmart_learning | Source 2 |
| mongo | edusmart_mongo | 27018 | edusmart_mobile | Source 4 |
| redis | edusmart_redis | 6380 | db 0 | Source 5 |
| adminer | edusmart_adminer | 8081 | — | Administration web |

Les ports Windows sont décalés pour éviter tout conflit avec des bases locales ou
d'autres projets Docker (voir C14 et C16). Ils sont modifiables dans `docker/.env`.

**Ports réservés par un autre projet sur ce poste** : 5433 (PostgreSQL), 27017 (MongoDB)
et 8080 (Airflow). Aucun port EduSmart ne les utilise.

## 5. Point de contrôle G0

| # | Vérification | Commande ou action | Attendu |
|---|---|---|---|
| 1 | Conteneurs démarrés | `docker compose ps` | 6 services, 5 « healthy » |
| 2 | Connexions Python | `python -m scripts.check_infrastructure` | `Résultat G0 : 5/5` |
| 3 | Schémas du DW | inclus dans la vérification 2 | `5 schémas OK` |
| 4 | Adminer | http://localhost:8081 | Écran de connexion |
| 5 | Power BI → DW | voir ci-dessous | Schémas visibles dans le navigateur |

### Connexion Power BI → PostgreSQL (Docker)

1. **Accueil → Obtenir les données → Base de données PostgreSQL**.
2. Serveur : `localhost:5434`. Base de données : `edusmart_dw`. Mode : **Importer**.
3. Authentification : onglet **Base de données**, avec l'utilisateur et le mot de passe `PG_DW_*` de `docker/.env`.
4. Le conteneur n'active pas SSL. Si Power BI propose une **connexion non chiffrée**, l'accepter : c'est normal en local.
5. Le navigateur affiche la base. Les schémas sont encore vides à ce stade : c'est attendu, car les tables arrivent en L4 à L6.

**Adminer** : choisir le système (PostgreSQL ou MySQL), puis le serveur `pg_source`, `pg_dw` ou `mysql`. Ce sont les noms des services Docker, pas `localhost`.

## 6. Référentiel maître (L1)

Aucune source ne relie `id_etudiant`/`matricule` (PostgreSQL) à `student_code`
(MySQL, MongoDB, Redis). Le référentiel maître est une population fictive
unique, **générée par graine**, dans laquelle puisent les 5 générateurs. Les
sources décrivent ainsi les mêmes personnes, tout en gardant des identifiants
incompatibles, comme dans une vraie entreprise.

| Fichier | Contenu | Qui le lit ? |
|---|---|---|
| `data/referential/referentiel_maitre.csv` | 10 500 personnes (10 000 PG + 500 LMS orphelines) | Générateurs L2 et tests uniquement. **Jamais le pipeline ETL** |
| `mappings/mapping_etudiants.csv` | 9 000 paires connues | Pipeline ETL (artefact d'intégration) |
| `mappings/mapping_courses.csv` | 1 994 codes de contenus (voir C22) | Pipeline ETL |

**Répartition** (graine 2026) :

| Statut | Nombre | Signification |
|---|---|---|
| APPARIE | 9 000 | Étudiant PG avec compte LMS |
| SANS_LMS | 1 000 | Étudiant PG sans compte LMS |
| LMS_ORPHELIN | 500 | Compte LMS absent de PostgreSQL |

Les 1 000 SANS_LMS et les 500 orphelins **n'apparaissent pas** dans
`mapping_etudiants.csv`. L'ETL devra les découvrir par anti-jointure, ce qui
alimente le constat « nombre réel d'étudiants » des phases 1 et 11.

## 7. Registre des conventions et écarts assumés

| # | Sujet | Convention | Justification |
|---|---|---|---|
| C1 | Nom de la base MongoDB | `edusmart_mobile` | Le PDF Source 4 ne nomme que la collection `events` |
| C2 | Format du matricule | `ESM-AAAA-NNNNN` (année de rentrée) | Non spécifié par le PDF Source 1 (VARCHAR(20)) |
| C3 | student_code | `LMS-XXXXXX`, numéros mélangés | Format du PDF MySQL ; aucun lien d'ordre avec le matricule |
| C4 | Référentiel maître | Hors sources, caché | Décision validée (Étape 2, Q5) |
| C5 | mapping_etudiants | 9 000 paires seulement | Rend visibles les étudiants non rapprochables |
| C6 | Attributs du référentiel | Identité ajoutée (nom, sexe, naissance, ville, région, année d'entrée) | Cohérence entre les 5 sources |
| C7 | Période | Oct. 2023 → sept. 2026, rentrée le 1er octobre | Décisions validées (points 2 et 9) |
| C8 | Année d'entrée | Poids 36 / 33 / 31 % | Convention de génération |
| C9 | Âge | 18 à 35 ans à la rentrée | Plausibilité ; date de naissance antérieure à aujourd'hui (PDF Source 1) |
| C10 | Régions | 14 régions, poids indicatifs, Dakar 30 % | Non officiel ; réaliste pour une formation en ligne |
| C11 | Téléphone | `+221 7X XXX XX XX` canonique, 4 variantes pour les anomalies | Décision validée (Q19) |
| C12 | Faker | Version épinglée (40.39.0) | Même graine avec une autre version = données différentes |
| C13 | Redis | Pas de persistance disque | Redis volatile (PDF Source 5) ; snapshot régénéré par graine (point 6) |
| C14 | Ports Windows | 5435 / 5434 / 3307 / 27018 / 6380 / 8081 | Éviter les conflits avec des bases locales et un autre projet (5433, 27017, 8080 occupés) |
| C16 | Nom de projet Compose | `name: edusmart` + `container_name: edusmart_*` | Conteneurs, volumes et réseau préfixés : aucune collision avec un autre projet Docker |
| C15 | Devise | XOF (FCFA) | Décision validée (Q17) |
| C17 | Catalogue académique partagé | `common/academic_catalog.py` : 8 départements, 25 filières (LIC-/MAS-/CERT-) | Mêmes départements pour PostgreSQL et le CSV RH |
| C18 | Vivier d'enseignants | 120 enseignants `ENS-NNNN`, noms uniques, créés en L2-a et enrichis en L2-c | Seul pont (par le nom) entre `classes.responsable` et `enseignants.csv` |
| C19 | Journal d'anomalies | `data/anomalies/<source>_anomalies.csv`, jamais lu par l'ETL | Vérité terrain pour G1 et la Phase 15 |
| C20 | Date de référence | 15/09/2026 : aucune activité simulée après (`GenerationConfig.date_reference`) | Données identiques quel que soit le jour d'exécution ; cohérente avec les exemples MongoDB et Redis |
| C21 | Catalogue pédagogique | `common/learning_catalog.py` : 8 catégories (une par département), codes `MOD-XXX-NN`, `COURSE-n`, `QUIZ-n` | Codes partagés par MySQL, MongoDB et Redis |
| C22 | Codes de contenus | `mapping_courses.csv` livré (95 % des cours et quiz) ; `data/referential/referentiel_contenus.csv` caché (100 %) | Même logique que mapping_etudiants : les absents se découvrent par anti-jointure |
| C23 | Sessions mobiles | `data/referential/sessions_mobile.csv` (caché) : 51 711 sessions MongoDB, dont 700 ouvertes le 15/09/2026 au soir | Base des sessions Redis (L2-e) |

Les écarts propres à chaque source sont documentés dans son README
(ex. [Source 1, § 6](sources/s1_postgresql/README.md#6-conventions-et-écarts-assumés)).

## 8. Reproductibilité

- La graine `EDUSMART_SEED` (2026) se règle dans `docker/.env`. Chaque générateur utilise son propre espace de noms (`get_rng("pg_etudiants")`...) : modifier un générateur ne décale pas les autres.
- Même graine + même version de Faker = mêmes fichiers, octet pour octet. C'est vérifié par un test et par une empreinte MD5 identique sur deux exécutions.

## 9. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `port is already allocated` | Port déjà utilisé sur Windows | Modifier le port dans `docker/.env` |
| `schémas manquants` au G0 | Le script d'init ne s'exécute qu'au 1er démarrage | `docker compose down -v` puis `up -d` (**efface les données**) |
| `mot de passe absent ou non modifié` | `docker/.env` absent ou non modifié | Étape 1 de l'installation |
| MySQL « unhealthy » | Premier démarrage lent | Attendre 30 à 60 s |
| `Activate.ps1 cannot be loaded` | Politique d'exécution PowerShell | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Accents mal affichés en console | Encodage de la console | `chcp 65001` ; le fichier de log reste en UTF-8 |
