-- =============================================================================
-- EduSmart Data Warehouse — CONTRÔLE QUALITÉ (Phase 5), Lot L5
-- -----------------------------------------------------------------------------
--   quality.regles     catalogue des règles (dimension, action, anomalies couvertes)
--   quality.constats   UNE LIGNE PAR CONSTAT : règle, ligne source, colonne,
--                      valeur avant / après, action (CORRIGE, REJETE, SIGNALE)
--   quality.rejets     contenu intégral des lignes écartées de la couche clean
--   quality.synthese   indicateurs du rapport qualité par table (exigés par le PDF)
--   quality.dimensions taux de conformité par dimension (complétude, unicité,
--                      cohérence, exactitude, fraîcheur)
-- Idempotent : les lignes d'un lot sont remplacées si le lot est retraité.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS quality;

CREATE TABLE IF NOT EXISTS quality.regles (
    code_regle   TEXT PRIMARY KEY,
    dimension    TEXT NOT NULL CHECK (dimension IN ('COMPLETUDE', 'UNICITE', 'COHERENCE', 'EXACTITUDE', 'FRAICHEUR')),
    code_source  TEXT NOT NULL,
    table_cible  TEXT NOT NULL,
    colonne      TEXT,
    action       TEXT NOT NULL CHECK (action IN ('CORRIGE', 'REJETE', 'SIGNALE')),
    anomalies    TEXT[] NOT NULL DEFAULT '{}',     -- codes du volet A couverts (A01, B13...) ; vide = contrôle supplémentaire
    description  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quality.constats (
    id_constat    BIGSERIAL PRIMARY KEY,
    batch_id      TEXT NOT NULL,
    code_regle    TEXT NOT NULL REFERENCES quality.regles (code_regle),
    code_source   TEXT NOT NULL,
    table_source  TEXT NOT NULL,
    id_ligne      TEXT,
    colonne       TEXT,
    valeur_avant  TEXT,
    valeur_apres  TEXT,
    action        TEXT NOT NULL CHECK (action IN ('CORRIGE', 'REJETE', 'SIGNALE'))
);
CREATE INDEX IF NOT EXISTS idx_constats_regle ON quality.constats (batch_id, code_regle);
CREATE INDEX IF NOT EXISTS idx_constats_ligne ON quality.constats (batch_id, code_source, table_source, id_ligne);

CREATE TABLE IF NOT EXISTS quality.rejets (
    id_rejet      BIGSERIAL PRIMARY KEY,
    batch_id      TEXT NOT NULL,
    code_regle    TEXT NOT NULL REFERENCES quality.regles (code_regle),
    code_source   TEXT NOT NULL,
    table_source  TEXT NOT NULL,
    id_ligne      TEXT,
    rang          INTEGER NOT NULL,                 -- _row_number du staging (distingue deux doublons identiques)
    motif         TEXT NOT NULL,
    ligne         JSONB NOT NULL                    -- la ligne de staging complète, pour audit
);
CREATE INDEX IF NOT EXISTS idx_rejets_batch ON quality.rejets (batch_id, code_source, table_source);

CREATE TABLE IF NOT EXISTS quality.synthese (
    batch_id              TEXT NOT NULL,
    code_source           TEXT NOT NULL,
    table_source          TEXT NOT NULL,
    lignes_extraites      INTEGER NOT NULL,
    lignes_rejetees       INTEGER NOT NULL,
    lignes_clean          INTEGER NOT NULL,
    doublons              INTEGER NOT NULL,
    valeurs_manquantes    INTEGER NOT NULL,
    incoherences          INTEGER NOT NULL,
    corrections           INTEGER NOT NULL,
    PRIMARY KEY (batch_id, code_source, table_source)
);

CREATE TABLE IF NOT EXISTS quality.dimensions (
    batch_id           TEXT NOT NULL,
    dimension          TEXT NOT NULL,
    code_source        TEXT NOT NULL,
    lignes_controlees  INTEGER NOT NULL,
    lignes_en_defaut   INTEGER NOT NULL,
    taux_conformite    NUMERIC(6,4),
    mesure             TEXT,
    PRIMARY KEY (batch_id, dimension, code_source)
);

-- -----------------------------------------------------------------------------
-- Fonctions utilitaires : une règle = un appel.
--   quality.constater(regle, table, requête renvoyant (id, avant, après))
--   quality.rejeter  (regle, table, requête renvoyant (id, rang, motif, ligne JSONB))
-- La source, la colonne et l'action viennent du catalogue quality.regles.
-- Le lot courant est lu dans le paramètre de session edusmart.batch_id.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION quality.constater(p_regle TEXT, p_table TEXT, p_requete TEXT) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
    EXECUTE format($f$
        INSERT INTO quality.constats (batch_id, code_regle, code_source, table_source, id_ligne, colonne,
                                      valeur_avant, valeur_apres, action)
        SELECT current_setting('edusmart.batch_id'), r.code_regle, r.code_source, %L, q.id::TEXT, r.colonne,
               q.avant::TEXT, q.apres::TEXT, r.action
        FROM (%s) AS q(id, avant, apres) CROSS JOIN quality.regles r WHERE r.code_regle = %L$f$,
        p_table, p_requete, p_regle);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

CREATE OR REPLACE FUNCTION quality.rejeter(p_regle TEXT, p_table TEXT, p_requete TEXT) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
    EXECUTE format($f$
        INSERT INTO quality.rejets (batch_id, code_regle, code_source, table_source, id_ligne, rang, motif, ligne)
        SELECT current_setting('edusmart.batch_id'), r.code_regle, r.code_source, %L, q.id::TEXT, q.rang::INTEGER,
               q.motif, q.ligne
        FROM (%s) AS q(id, rang, motif, ligne) CROSS JOIN quality.regles r WHERE r.code_regle = %L$f$,
        p_table, p_requete, p_regle);
    GET DIAGNOSTICS n = ROW_COUNT;
    EXECUTE format($f$
        INSERT INTO quality.constats (batch_id, code_regle, code_source, table_source, id_ligne, colonne,
                                      valeur_avant, valeur_apres, action)
        SELECT current_setting('edusmart.batch_id'), r.code_regle, r.code_source, %L, q.id::TEXT, r.colonne,
               NULL, q.motif, 'REJETE'
        FROM (%s) AS q(id, rang, motif, ligne) CROSS JOIN quality.regles r WHERE r.code_regle = %L$f$,
        p_table, p_requete, p_regle);
    RETURN n;
END $$;

-- Remise à zéro des traces d'une source pour le lot courant (retraitement idempotent)
CREATE OR REPLACE FUNCTION quality.reinitialiser(p_source TEXT) RETURNS VOID LANGUAGE sql AS $$
    DELETE FROM quality.constats WHERE batch_id = current_setting('edusmart.batch_id') AND code_source = p_source;
    DELETE FROM quality.rejets   WHERE batch_id = current_setting('edusmart.batch_id') AND code_source = p_source;
$$;

-- Anomalies (codes de règles) d'une table, par identifiant de ligne : alimente la colonne _anomalies
CREATE OR REPLACE FUNCTION quality.anomalies_par_ligne(p_source TEXT, p_table TEXT)
RETURNS TABLE (id_ligne TEXT, codes TEXT[]) LANGUAGE sql STABLE AS $$
    SELECT id_ligne, array_agg(DISTINCT code_regle ORDER BY code_regle)
    FROM quality.constats
    WHERE batch_id = current_setting('edusmart.batch_id') AND code_source = p_source AND table_source = p_table
      AND action <> 'REJETE'
    GROUP BY id_ligne
$$;
