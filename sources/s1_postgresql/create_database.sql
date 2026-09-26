-- =============================================================================
-- EduSmart — Source 1 : PostgreSQL « Gestion académique »
-- Base : edusmart_academic
-- Fichier : create_database.sql  (1/3 : structure)
-- -----------------------------------------------------------------------------
-- Stratégie validée (Étape 1, Q7) : « insertion puis contraintes NOT VALID »
--   1. create_database.sql : tables + clés primaires + UNIQUE et NOT NULL non
--      concernés par les anomalies.        <- CE FICHIER (avant insertion)
--   2. add_constraints.sql : CHECK et FOREIGN KEY ajoutés APRÈS insertion.
--   3. check_constraints.sql : diagnostic des violations (Phase 15).
--
-- Pourquoi ? Le PDF impose à la fois des contraintes (ex. montant >= 0) et des
-- anomalies qui les violent (ex. paiements négatifs). Créer les CHECK dès le
-- départ rendrait l'insertion des anomalies impossible.
--
-- Script idempotent : il supprime puis recrée les tables. À n'exécuter que
-- sur la base de génération (jamais sur une base de production).
-- Prérequis : PostgreSQL 13+ (gen_random_uuid() est natif).
-- =============================================================================

SET client_encoding = 'UTF8';

DROP TABLE IF EXISTS paiements    CASCADE;
DROP TABLE IF EXISTS inscriptions CASCADE;
DROP TABLE IF EXISTS classes      CASCADE;
DROP TABLE IF EXISTS filieres     CASCADE;
DROP TABLE IF EXISTS etudiants    CASCADE;

-- -----------------------------------------------------------------------------
-- 1. etudiants — informations personnelles des étudiants
-- -----------------------------------------------------------------------------
CREATE TABLE etudiants (
    id_etudiant     UUID          NOT NULL DEFAULT gen_random_uuid(),
    matricule       VARCHAR(20)   NOT NULL,
    nom             VARCHAR(100)  NOT NULL,
    prenom          VARCHAR(100)  NOT NULL,
    -- ÉCART ASSUMÉ : CHAR(1) dans le PDF, élargi à VARCHAR(10) pour accueillir
    -- les anomalies demandées (« Homme », « Garçon »...). Le CHECK ('M','F')
    -- est ajouté en NOT VALID dans add_constraints.sql.
    sexe            VARCHAR(10),
    date_naissance  DATE          NOT NULL,
    telephone       VARCHAR(20)   NULL,
    email           VARCHAR(150),
    adresse         TEXT          NULL,
    ville           VARCHAR(100)  NOT NULL,
    region          VARCHAR(100)  NOT NULL,
    pays            VARCHAR(100)  DEFAULT 'Sénégal',
    date_creation   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_etudiants PRIMARY KEY (id_etudiant),
    CONSTRAINT uq_etudiants_matricule UNIQUE (matricule),   -- aucune anomalie prévue : UNIQUE immédiat
    CONSTRAINT uq_etudiants_email UNIQUE (email)            -- idem (NULL autorisé, NULL multiples permis)
);

COMMENT ON TABLE  etudiants                IS 'Informations personnelles des étudiants (PDF Source 1, table 1)';
COMMENT ON COLUMN etudiants.id_etudiant    IS 'Identifiant technique (UUID). Seule clé à utiliser en clé étrangère';
COMMENT ON COLUMN etudiants.matricule      IS 'Matricule officiel, unique. Ne jamais l''utiliser comme clé étrangère (PDF)';
COMMENT ON COLUMN etudiants.sexe           IS 'Attendu M ou F ; variantes volontaires (anomalie A01). VARCHAR(10) : écart assumé';
COMMENT ON COLUMN etudiants.telephone      IS 'Téléphone, peut être absent ; formats variables (anomalies A02, A03)';
COMMENT ON COLUMN etudiants.adresse        IS 'Adresse, peut être absente (anomalie A04)';
COMMENT ON COLUMN etudiants.date_creation  IS 'Date de création de la fiche étudiant';

-- -----------------------------------------------------------------------------
-- 2. filieres — formations proposées
-- -----------------------------------------------------------------------------
CREATE TABLE filieres (
    id_filiere    UUID           NOT NULL DEFAULT gen_random_uuid(),
    code_filiere  VARCHAR(20)    NOT NULL,
    nom_filiere   VARCHAR(150)   NOT NULL,
    departement   VARCHAR(100)   NOT NULL,
    niveau        VARCHAR(30)    NOT NULL,
    duree_mois    INTEGER,
    cout_total    NUMERIC(12,2),
    statut        VARCHAR(20)    DEFAULT 'ACTIVE',
    CONSTRAINT pk_filieres PRIMARY KEY (id_filiere),
    CONSTRAINT uq_filieres_code UNIQUE (code_filiere)
);

COMMENT ON TABLE  filieres             IS 'Formations proposées par l''établissement (PDF Source 1, table 2)';
COMMENT ON COLUMN filieres.nom_filiere IS 'Libellé ; variantes IA volontaires (anomalie A07)';
COMMENT ON COLUMN filieres.niveau      IS 'LICENCE, MASTER ou CERTIFICAT (convention validée)';
COMMENT ON COLUMN filieres.cout_total  IS 'Coût total du parcours en XOF (FCFA)';

-- -----------------------------------------------------------------------------
-- 3. classes — chaque classe appartient à une filière
-- -----------------------------------------------------------------------------
CREATE TABLE classes (
    id_classe         UUID          NOT NULL DEFAULT gen_random_uuid(),
    code_classe       VARCHAR(30),
    nom_classe        VARCHAR(100)  NOT NULL,
    id_filiere        UUID,
    annee_academique  VARCHAR(20)   NOT NULL,
    capacite          INTEGER,
    salle             VARCHAR(30)   NULL,
    responsable       VARCHAR(100)  NULL,
    CONSTRAINT pk_classes PRIMARY KEY (id_classe),
    CONSTRAINT uq_classes_code UNIQUE (code_classe)
);

COMMENT ON TABLE  classes                  IS 'Classes, rattachées à une filière (PDF Source 1, table 3)';
COMMENT ON COLUMN classes.annee_academique IS 'Attendu AAAA-AAAA ; formats variables (anomalie A09)';
COMMENT ON COLUMN classes.salle            IS 'Salle ; écritures variables A101 / Salle A101 / A-101 (anomalie A08)';
COMMENT ON COLUMN classes.responsable      IS 'Responsable pédagogique (texte libre : nom d''un enseignant)';

-- -----------------------------------------------------------------------------
-- 4. inscriptions — association étudiant / classe
-- -----------------------------------------------------------------------------
CREATE TABLE inscriptions (
    id_inscription    UUID          NOT NULL DEFAULT gen_random_uuid(),
    id_etudiant       UUID,
    id_classe         UUID,
    date_inscription  DATE          NOT NULL,
    statut            VARCHAR(30)   DEFAULT 'INSCRIT',
    type_inscription  VARCHAR(30)   NOT NULL,
    bourse            BOOLEAN       DEFAULT FALSE,
    reduction         NUMERIC(5,2),
    CONSTRAINT pk_inscriptions PRIMARY KEY (id_inscription)
);

COMMENT ON TABLE  inscriptions                  IS 'Inscriptions étudiant/classe (PDF Source 1, table 4). Doublons volontaires (A10)';
COMMENT ON COLUMN inscriptions.statut           IS 'INSCRIT, EN_COURS, DIPLOME, ABANDON, SUSPENDU (convention validée)';
COMMENT ON COLUMN inscriptions.type_inscription IS 'Nouvelle ou Réinscription (PDF)';
COMMENT ON COLUMN inscriptions.reduction        IS 'Réduction en % ; > 100 volontaire (anomalie A11)';
COMMENT ON COLUMN inscriptions.date_inscription IS 'Normalement avant la rentrée (1er octobre) ; après = anomalie A12';

-- -----------------------------------------------------------------------------
-- 5. paiements — historique des paiements
-- -----------------------------------------------------------------------------
CREATE TABLE paiements (
    id_paiement     UUID           NOT NULL DEFAULT gen_random_uuid(),
    id_inscription  UUID,
    -- PDF : reference UNIQUE. Impossible ici : le PDF demande aussi des
    -- références dupliquées (anomalie A13), et PostgreSQL n'accepte pas de
    -- contrainte UNIQUE « NOT VALID ». Voir add_constraints.sql.
    reference       VARCHAR(50),
    date_paiement   DATE           NOT NULL,
    montant         NUMERIC(12,2),
    mode_paiement   VARCHAR(30)    NOT NULL,
    statut          VARCHAR(30)    DEFAULT 'VALIDE',
    tranche         VARCHAR(20)    NOT NULL,
    CONSTRAINT pk_paiements PRIMARY KEY (id_paiement)
);

COMMENT ON TABLE  paiements               IS 'Historique des paiements (PDF Source 1, table 5)';
COMMENT ON COLUMN paiements.reference     IS 'Référence de paiement ; UNIQUE documentée mais non posée (doublons volontaires A13)';
COMMENT ON COLUMN paiements.montant       IS 'Montant en XOF ; négatifs volontaires (anomalie A14)';
COMMENT ON COLUMN paiements.mode_paiement IS 'Orange Money, Wave, Espèces... ; écritures variables (anomalie A15)';
COMMENT ON COLUMN paiements.statut        IS 'VALIDE, EN_ATTENTE, ECHOUE, REMBOURSE (convention validée)';
COMMENT ON COLUMN paiements.tranche       IS '1ERE, 2EME, 3EME (convention validée)';
