-- =============================================================================
-- EduSmart Data Warehouse — Couche OR : DIMENSIONS (Phases 7 et 9, Lot L6)
-- -----------------------------------------------------------------------------
-- Clés de substitution (entiers) : indépendantes des identifiants sources, qui
-- sont incompatibles entre eux (Phase 1). Chaque dimension possède un membre
-- « Inconnu » de clé -1 : un fait n'a JAMAIS de clé étrangère NULL (porte G4).
-- Évolution des attributs : SCD 2 pour la localisation de l'étudiant, SCD 1
-- ailleurs (détail dans docs/07_conception_dw.md).
-- Script idempotent (IF NOT EXISTS).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dw;

-- (L'étape DW du journal est autorisée par pipeline/sql/meta/01_meta_tables.sql.)

-- -----------------------------------------------------------------------------
-- dim_temps — grain : le JOUR
-- Hiérarchies : jour > mois > trimestre > année (civile)
--               jour > mois > année académique (octobre -> septembre, rentrée C7)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_temps (
    date_key             INTEGER PRIMARY KEY,          -- AAAAMMJJ ; -1 = inconnue
    date_complete        DATE NOT NULL UNIQUE,
    jour                 SMALLINT NOT NULL,
    jour_semaine         SMALLINT NOT NULL,            -- 1 = lundi
    libelle_jour         TEXT NOT NULL,
    est_weekend          BOOLEAN NOT NULL,
    semaine_iso          SMALLINT NOT NULL,
    mois                 SMALLINT NOT NULL,
    libelle_mois         TEXT NOT NULL,
    annee_mois           TEXT NOT NULL,                -- '2025-10'
    trimestre            SMALLINT NOT NULL,
    annee                SMALLINT NOT NULL,
    annee_academique     TEXT NOT NULL,                -- '2025-2026'
    mois_academique      SMALLINT NOT NULL,            -- 1 = octobre ... 12 = septembre
    trimestre_academique SMALLINT NOT NULL             -- 1 = oct-déc, 2 = janv-mars, 3 = avr-juin, 4 = juil-sept
);

-- -----------------------------------------------------------------------------
-- dim_region — grain : la VILLE ; hiérarchie ville > région > pays
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_region (
    region_key  SERIAL PRIMARY KEY,
    ville       TEXT NOT NULL,
    region      TEXT NOT NULL,
    pays        TEXT NOT NULL,
    CONSTRAINT uq_dim_region UNIQUE (ville, region)
);

-- -----------------------------------------------------------------------------
-- dim_formation — grain : la CLASSE (offre diplômante, PostgreSQL)
-- Hiérarchie : classe > filière > (niveau, département) ; + année académique
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_formation (
    formation_key     SERIAL PRIMARY KEY,
    id_classe         UUID UNIQUE,
    code_classe       TEXT NOT NULL,
    nom_classe        TEXT NOT NULL,
    annee_academique  TEXT NOT NULL,
    groupe            TEXT,
    code_filiere      TEXT NOT NULL,
    nom_filiere       TEXT NOT NULL,
    niveau            TEXT NOT NULL,
    departement       TEXT NOT NULL,
    duree_mois        INTEGER,
    cout_total        NUMERIC(12,2),
    frais_annuels     NUMERIC(12,2),                   -- coût total / nombre d'années du parcours
    responsable       TEXT
);

-- -----------------------------------------------------------------------------
-- dim_module — grain : le MODULE (contenus pédagogiques, MySQL) ; hiérarchie module > catégorie
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_module (
    module_key    SERIAL PRIMARY KEY,
    id_module     UUID UNIQUE,
    code_module   TEXT NOT NULL,
    nom_module    TEXT NOT NULL,
    categorie     TEXT NOT NULL,
    niveau        TEXT NOT NULL,
    duree_heures  INTEGER,
    actif         BOOLEAN
);

-- -----------------------------------------------------------------------------
-- dim_quiz — grain : le QUIZ ; hiérarchie quiz > cours > module (> catégorie via dim_module)
-- (clé étrangère vers dim_module : seule « branche en flocon » assumée du modèle)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_quiz (
    quiz_key      SERIAL PRIMARY KEY,
    id_quiz       UUID UNIQUE,
    code_quiz     TEXT,                                -- QUIZ-n (NULL si absent de mapping_courses)
    titre         TEXT NOT NULL,
    nb_questions  INTEGER,
    score_max     NUMERIC(5,2),
    duree_minutes INTEGER,
    id_cours      UUID,
    code_cours    TEXT,
    titre_cours   TEXT,
    type_cours    TEXT,
    ordre_cours   INTEGER,
    module_key    INTEGER NOT NULL REFERENCES dw.dim_module (module_key)
);

-- -----------------------------------------------------------------------------
-- dim_enseignant — grain : l'ENSEIGNANT (SCD 1 : la valeur courante écrase l'ancienne)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_enseignant (
    enseignant_key  SERIAL PRIMARY KEY,
    teacher_code    TEXT UNIQUE,
    nom             TEXT NOT NULL,
    prenom          TEXT NOT NULL,
    sexe            TEXT,
    specialite      TEXT,
    grade           TEXT,
    statut          TEXT,
    date_embauche   DATE
);

-- -----------------------------------------------------------------------------
-- dim_etudiant — grain : une VERSION d'un étudiant (SCD 2 sur ville et région)
-- Population (définition validée en L3) : étudiants inscrits (PostgreSQL) + comptes
-- LMS sans inscription (MySQL), soit 10 500 personnes distinctes.
-- etudiant_id = clé DURABLE : id_etudiant, ou 'LMS:' || student_code pour un compte seul.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_etudiant (
    etudiant_key    SERIAL PRIMARY KEY,
    etudiant_id     TEXT NOT NULL,
    id_etudiant     UUID,
    matricule       TEXT,
    student_code    TEXT,
    nom             TEXT,
    prenom          TEXT,
    sexe            TEXT,
    date_naissance  DATE,
    rapprochement   TEXT NOT NULL,                     -- APPARIE, SANS_LMS, LMS_SEUL, INCONNU
    -- attributs historisés (SCD 2)
    ville           TEXT,
    region          TEXT,
    region_key      INTEGER NOT NULL REFERENCES dw.dim_region (region_key),
    -- validité de la version
    date_debut      DATE NOT NULL,
    date_fin        DATE NOT NULL,
    est_courant     BOOLEAN NOT NULL,
    version         INTEGER NOT NULL,
    CONSTRAINT uq_dim_etudiant_version UNIQUE (etudiant_id, version),
    CONSTRAINT ck_dim_etudiant_periode CHECK (date_debut <= date_fin)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_etudiant_courant ON dw.dim_etudiant (etudiant_id) WHERE est_courant;
CREATE INDEX IF NOT EXISTS idx_dim_etudiant_periode ON dw.dim_etudiant (etudiant_id, date_debut, date_fin);
CREATE INDEX IF NOT EXISTS idx_dim_etudiant_code ON dw.dim_etudiant (student_code);

-- -----------------------------------------------------------------------------
-- Membres « Inconnu » (clé -1)
-- -----------------------------------------------------------------------------
INSERT INTO dw.dim_temps VALUES (-1, DATE '1900-01-01', 0, 0, 'Inconnu', FALSE, 0, 0, 'Inconnu', 'Inconnu', 0, 0,
                                 'Inconnue', 0, 0) ON CONFLICT DO NOTHING;
INSERT INTO dw.dim_region (region_key, ville, region, pays) VALUES (-1, 'Inconnue', 'Inconnue', 'Inconnu') ON CONFLICT DO NOTHING;
INSERT INTO dw.dim_formation (formation_key, code_classe, nom_classe, annee_academique, code_filiere, nom_filiere, niveau, departement)
VALUES (-1, 'INCONNUE', 'Inconnue', 'Inconnue', 'INCONNUE', 'Inconnue', 'Inconnu', 'Inconnu') ON CONFLICT DO NOTHING;
INSERT INTO dw.dim_module (module_key, code_module, nom_module, categorie, niveau)
VALUES (-1, 'INCONNU', 'Inconnu', 'Inconnue', 'Inconnu') ON CONFLICT DO NOTHING;
INSERT INTO dw.dim_quiz (quiz_key, titre, module_key) VALUES (-1, 'Inconnu', -1) ON CONFLICT DO NOTHING;
INSERT INTO dw.dim_enseignant (enseignant_key, nom, prenom) VALUES (-1, 'Inconnu', 'Inconnu') ON CONFLICT DO NOTHING;
INSERT INTO dw.dim_etudiant (etudiant_key, etudiant_id, rapprochement, region_key, date_debut, date_fin, est_courant, version)
VALUES (-1, 'INCONNU', 'INCONNU', -1, DATE '1900-01-01', DATE '9999-12-31', TRUE, 1) ON CONFLICT DO NOTHING;
