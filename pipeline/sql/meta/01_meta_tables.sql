-- =============================================================================
-- EduSmart Data Warehouse — MÉTADONNÉES ET TRAÇABILITÉ (Phase 6), Lot L4
-- -----------------------------------------------------------------------------
-- PDF Phase 6 : « Pourquoi conserver la source, la date d'extraction, la
-- version, le nombre de lignes, le statut du traitement ? »
-- TP : créer metadata_sources et etl_execution_log ; chaque exécution
-- enregistre : source, date, durée, nombre de lignes, erreurs, statut.
-- Script idempotent (IF NOT EXISTS) : exécuté au début de chaque pipeline.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS meta;

-- -----------------------------------------------------------------------------
-- 1. metadata_sources : UNE LIGNE PAR OBJET SOURCE (17 objets)
--    Partie descriptive (quoi, où, sous quelle forme) mise à jour depuis
--    pipeline/registry.py + état de la dernière extraction.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.metadata_sources (
    code_source              TEXT        NOT NULL,   -- s1_postgresql, s2_mysql, s3_csv, s4_mongodb, s5_redis
    objet                    TEXT        NOT NULL,   -- table, fichier, collection ou « keys »
    technologie              TEXT        NOT NULL,
    emplacement              TEXT        NOT NULL,   -- hôte:port/base ou chemin du fichier
    table_staging            TEXT        NOT NULL,
    nb_colonnes              INTEGER     NOT NULL,
    encodage                 TEXT,
    separateur               TEXT,
    description              TEXT,
    version_schema           TEXT        NOT NULL,   -- empreinte des colonnes : détecte un changement de structure
    derniere_extraction      TIMESTAMP,
    dernier_batch_id         TEXT,
    derniere_nb_lignes       INTEGER,
    dernier_statut           TEXT,
    mis_a_jour_le            TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_metadata_sources PRIMARY KEY (code_source, objet),
    CONSTRAINT ck_metadata_statut CHECK (dernier_statut IS NULL OR dernier_statut IN ('SUCCES', 'ECHEC'))
);
COMMENT ON TABLE meta.metadata_sources IS 'Catalogue des 17 objets sources et état de leur dernière extraction (Phase 6)';

-- -----------------------------------------------------------------------------
-- 2. etl_execution_log : UNE LIGNE PAR ÉTAPE, PAR OBJET, PAR EXÉCUTION
--    Les 6 informations exigées par le PDF + le lot, l'étape et la version.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.etl_execution_log (
    id_execution        BIGSERIAL    PRIMARY KEY,
    batch_id            TEXT         NOT NULL,       -- un lot = une exécution du pipeline
    etape               TEXT         NOT NULL,       -- EXTRACT, LOAD, VERIFY, TRANSFORM (L5), DW (L6)
    code_source         TEXT         NOT NULL,       -- PDF : source
    objet               TEXT         NOT NULL,
    date_debut          TIMESTAMP    NOT NULL,       -- PDF : date
    date_fin            TIMESTAMP,
    duree_secondes      NUMERIC(10,3),               -- PDF : durée
    nb_lignes           INTEGER,                     -- PDF : nombre de lignes
    nb_erreurs          INTEGER      NOT NULL DEFAULT 0,
    erreurs             TEXT,                        -- PDF : erreurs (message)
    statut              TEXT         NOT NULL,       -- PDF : statut
    version_pipeline    TEXT         NOT NULL,       -- PDF (Phase 6) : version
    CONSTRAINT ck_log_etape  CHECK (etape IN ('EXTRACT', 'LOAD', 'VERIFY', 'TRANSFORM', 'DW')),
    CONSTRAINT ck_log_statut CHECK (statut IN ('EN_COURS', 'SUCCES', 'ECHEC'))
);
-- Mise à niveau d'une base existante : CREATE TABLE IF NOT EXISTS ne modifie pas une table déjà
-- créée. La contrainte est donc redéfinie à chaque initialisation, AVANT toute écriture du journal
-- (correctif L6 : une base créée en L4 refusait l'étape DW).
ALTER TABLE meta.etl_execution_log DROP CONSTRAINT IF EXISTS ck_log_etape;
ALTER TABLE meta.etl_execution_log ADD CONSTRAINT ck_log_etape
    CHECK (etape IN ('EXTRACT', 'LOAD', 'VERIFY', 'TRANSFORM', 'DW'));
CREATE INDEX IF NOT EXISTS idx_log_batch  ON meta.etl_execution_log (batch_id);
CREATE INDEX IF NOT EXISTS idx_log_source ON meta.etl_execution_log (code_source, objet, date_debut);
COMMENT ON TABLE meta.etl_execution_log IS 'Journal de chaque étape du pipeline (Phase 6) : source, date, durée, lignes, erreurs, statut';
