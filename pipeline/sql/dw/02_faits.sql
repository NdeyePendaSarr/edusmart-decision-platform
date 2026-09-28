-- =============================================================================
-- EduSmart Data Warehouse — Couche OR : FAITS (constellation de 8 faits, Phases 7 et 8)
-- -----------------------------------------------------------------------------
-- Chaque fait déclare :
--   - son GRAIN, garanti par une contrainte UNIQUE (porte G4) ;
--   - des clés étrangères RÉELLES vers les dimensions (jamais NULL : membre -1) ;
--   - des mesures additives (sommes), semi-additives (pourcentage) ou des indicateurs 0/1.
-- Les dimensions dim_temps et dim_etudiant sont PARTAGÉES (dimensions conformes).
-- =============================================================================

-- 1. Paiements — grain : UN paiement
CREATE TABLE IF NOT EXISTS dw.fact_paiements (
    id_paiement         UUID PRIMARY KEY,                          -- grain (dimension dégénérée)
    date_key            INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    etudiant_key        INTEGER NOT NULL REFERENCES dw.dim_etudiant (etudiant_key),
    formation_key       INTEGER NOT NULL REFERENCES dw.dim_formation (formation_key),
    region_key          INTEGER NOT NULL REFERENCES dw.dim_region (region_key),
    reference           TEXT,
    mode_paiement       TEXT,
    statut              TEXT,
    tranche             TEXT,
    montant             NUMERIC(12,2),                             -- montant brut (peut être négatif : A14)
    montant_ca          NUMERIC(12,2) NOT NULL,                    -- définition validée en L3 : VALIDE et non négatif
    est_montant_negatif SMALLINT NOT NULL,
    est_reference_partagee SMALLINT NOT NULL
);

-- 2. Inscriptions — grain : UNE inscription (étudiant x classe)
CREATE TABLE IF NOT EXISTS dw.fact_inscriptions (
    id_inscription     UUID PRIMARY KEY,
    date_key           INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    etudiant_key       INTEGER NOT NULL REFERENCES dw.dim_etudiant (etudiant_key),
    formation_key      INTEGER NOT NULL REFERENCES dw.dim_formation (formation_key),
    region_key         INTEGER NOT NULL REFERENCES dw.dim_region (region_key),
    statut             TEXT,
    type_inscription   TEXT,
    nb_inscriptions    SMALLINT NOT NULL DEFAULT 1,
    est_boursier       SMALLINT NOT NULL,
    est_abandon        SMALLINT NOT NULL,
    est_diplome        SMALLINT NOT NULL,
    est_tardive        SMALLINT NOT NULL,
    reduction          NUMERIC(5,2),                               -- NULL si neutralisée (A11)
    montant_du         NUMERIC(12,2)                               -- frais annuels après réduction
);

-- 3. Notes — grain : UNE tentative d'un étudiant à un quiz (MySQL)
CREATE TABLE IF NOT EXISTS dw.fact_notes (
    id_note          UUID PRIMARY KEY,
    date_key         INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    etudiant_key     INTEGER NOT NULL REFERENCES dw.dim_etudiant (etudiant_key),
    quiz_key         INTEGER NOT NULL REFERENCES dw.dim_quiz (quiz_key),
    module_key       INTEGER NOT NULL REFERENCES dw.dim_module (module_key),
    tentative        SMALLINT,
    score            NUMERIC(5,2),                                 -- NULL si neutralisé (B14)
    score_max        NUMERIC(5,2),
    score_sur_20     NUMERIC(5,2),
    est_valide       SMALLINT NOT NULL,
    nb_tentatives    SMALLINT NOT NULL DEFAULT 1
);

-- 4. Activité quiz — grain : UN événement QUIZ_STARTED ou QUIZ_SUBMITTED (MongoDB)
CREATE TABLE IF NOT EXISTS dw.fact_quiz_activite (
    event_id          TEXT PRIMARY KEY,
    date_key          INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    heure             SMALLINT,
    etudiant_key      INTEGER NOT NULL REFERENCES dw.dim_etudiant (etudiant_key),
    quiz_key          INTEGER NOT NULL REFERENCES dw.dim_quiz (quiz_key),
    module_key        INTEGER NOT NULL REFERENCES dw.dim_module (module_key),
    region_key        INTEGER NOT NULL REFERENCES dw.dim_region (region_key),   -- lieu de l'événement
    event_type        TEXT NOT NULL,
    plateforme        TEXT,
    app_version       TEXT,
    session_id        TEXT,
    duree_secondes    INTEGER,
    score             NUMERIC(6,2),
    tentative         SMALLINT,
    est_succes        SMALLINT,
    nb_evenements     SMALLINT NOT NULL DEFAULT 1
);

-- 5. Connexions — grain : UNE connexion (MySQL, source de référence validée en Étape 2)
CREATE TABLE IF NOT EXISTS dw.fact_connexions (
    id_connexion     UUID PRIMARY KEY,
    date_key         INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    heure            SMALLINT,
    etudiant_key     INTEGER NOT NULL REFERENCES dw.dim_etudiant (etudiant_key),
    appareil         TEXT,
    navigateur       TEXT,
    duree_secondes   INTEGER,                                      -- définition validée en L3 (médiane en secondes)
    nb_connexions    SMALLINT NOT NULL DEFAULT 1,
    est_sans_fin     SMALLINT NOT NULL
);

-- 6. Progression — grain : UN couple (étudiant, module), photographié à sa dernière mise à jour
--    (fait « instantané » : le pourcentage est semi-additif, on le moyenne, on ne le somme pas)
CREATE TABLE IF NOT EXISTS dw.fact_progression (
    id_progression   UUID PRIMARY KEY,
    date_key         INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    etudiant_key     INTEGER NOT NULL REFERENCES dw.dim_etudiant (etudiant_key),
    module_key       INTEGER NOT NULL REFERENCES dw.dim_module (module_key),
    etudiant_id      TEXT NOT NULL,                                -- porte le grain (étudiant durable x module)
    pourcentage      NUMERIC(5,2),                                 -- NULL si neutralisé (B05, B06)
    est_termine      SMALLINT NOT NULL,
    CONSTRAINT uq_fact_progression_grain UNIQUE (etudiant_id, module_key)
);

-- 7. Salaires — grain : UN enseignant x UN mois
CREATE TABLE IF NOT EXISTS dw.fact_salaires (
    id_salaire      INTEGER PRIMARY KEY,
    date_key        INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),   -- 1er jour du mois
    enseignant_key  INTEGER NOT NULL REFERENCES dw.dim_enseignant (enseignant_key),
    mode_paiement   TEXT,
    salaire_base    NUMERIC(12,2),
    primes          NUMERIC(12,2),                                 -- NULL si neutralisées (C11)
    retenues        NUMERIC(12,2),
    salaire_net     NUMERIC(12,2),
    CONSTRAINT uq_fact_salaires_grain UNIQUE (enseignant_key, date_key)
);

-- 8. Absences — grain : UNE absence
CREATE TABLE IF NOT EXISTS dw.fact_absences (
    id_absence       INTEGER PRIMARY KEY,
    date_key         INTEGER NOT NULL REFERENCES dw.dim_temps (date_key),
    enseignant_key   INTEGER NOT NULL REFERENCES dw.dim_enseignant (enseignant_key),
    motif            TEXT,
    duree_heures     INTEGER,                                      -- NULL si neutralisée (C18)
    est_justifiee    SMALLINT,
    est_remplacee    SMALLINT,
    nb_absences      SMALLINT NOT NULL DEFAULT 1
);

-- Index des clés étrangères les plus utilisées en analyse
CREATE INDEX IF NOT EXISTS idx_fp_date ON dw.fact_paiements (date_key);
CREATE INDEX IF NOT EXISTS idx_fp_etu ON dw.fact_paiements (etudiant_key);
CREATE INDEX IF NOT EXISTS idx_fn_date ON dw.fact_notes (date_key);
CREATE INDEX IF NOT EXISTS idx_fn_quiz ON dw.fact_notes (quiz_key);
CREATE INDEX IF NOT EXISTS idx_fq_date ON dw.fact_quiz_activite (date_key);
CREATE INDEX IF NOT EXISTS idx_fc_date ON dw.fact_connexions (date_key);
CREATE INDEX IF NOT EXISTS idx_fi_form ON dw.fact_inscriptions (formation_key);
