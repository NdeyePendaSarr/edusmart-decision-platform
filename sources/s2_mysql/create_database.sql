-- =============================================================================
-- EduSmart — Source 2 : MySQL « Plateforme pédagogique »
-- Base : edusmart_learning   (MySQL 8.0.16 minimum)
-- Fichier : create_database.sql
-- -----------------------------------------------------------------------------
-- Adaptations MySQL (décisions validées, Étape 1 § 4.B) :
--   * UUID          -> CHAR(36)   (MySQL n'a pas de type UUID natif)
--   * BOOLEAN       -> TINYINT(1) (BOOLEAN est un alias de TINYINT(1) en MySQL)
--   * NUMERIC(p,s)  -> DECIMAL(p,s) (synonymes en MySQL)
--
-- Stratégie des contraintes (différente de PostgreSQL, voir README § 4) :
--   * CHECK concernées par une anomalie -> NOT ENFORCED dès la création.
--     ATTENTION : en MySQL, NOT ENFORCED = la règle n'est vérifiée NI pour
--     les lignes existantes NI pour les nouvelles (≠ NOT VALID de PostgreSQL).
--   * CHECK non concernées -> ENFORCED (actives).
--   * FOREIGN KEY : toutes déclarées. Les orphelins volontaires sont insérés
--     avec FOREIGN_KEY_CHECKS = 0 (MySQL ne vérifie pas l'existant quand on
--     réactive les contrôles), puis les FK protègent les nouvelles lignes.
--
-- Script idempotent (DROP puis CREATE). En MySQL, chaque instruction DDL
-- valide implicitement la transaction : pas de rollback possible ici.
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS temps_connexion;
DROP TABLE IF EXISTS progression;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS quiz;
DROP TABLE IF EXISTS cours;
DROP TABLE IF EXISTS modules;

SET FOREIGN_KEY_CHECKS = 1;

-- -----------------------------------------------------------------------------
-- 1. modules — chaque module regroupe plusieurs cours
-- -----------------------------------------------------------------------------
CREATE TABLE modules (
    id_module      CHAR(36)      NOT NULL                 COMMENT 'Identifiant technique (UUID)',
    code_module    VARCHAR(20)   NOT NULL                 COMMENT 'Code du module, ex. MOD-IA-01',
    nom_module     VARCHAR(150)  NOT NULL                 COMMENT 'Nom',
    categorie      VARCHAR(100)  NOT NULL                 COMMENT 'Développement, Data, IA... - écritures variables (anomalie B01)',
    niveau         VARCHAR(30)   NOT NULL                 COMMENT 'DEBUTANT, INTERMEDIAIRE, AVANCE',
    duree_heures   INT                                    COMMENT 'Durée estimée',
    actif          TINYINT(1)    DEFAULT 1                COMMENT 'Module actif - modules inactifs volontaires (B02)',
    CONSTRAINT pk_modules PRIMARY KEY (id_module),
    CONSTRAINT uq_modules_code UNIQUE (code_module),
    CONSTRAINT ck_modules_duree CHECK (duree_heures > 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci
  COMMENT = 'Modules de formation (PDF Source 2, table 1)';

-- -----------------------------------------------------------------------------
-- 2. cours — leçons appartenant à un module
-- -----------------------------------------------------------------------------
CREATE TABLE cours (
    id_cours       CHAR(36)      NOT NULL                 COMMENT 'Identifiant (UUID)',
    id_module      CHAR(36)                               COMMENT 'Module',
    titre          VARCHAR(200)  NOT NULL                 COMMENT 'Titre - doublons volontaires (B03)',
    ordre          INT                                    COMMENT 'Position dans le module',
    duree_minutes  INT                                    COMMENT 'Durée',
    type_cours     VARCHAR(30)   NOT NULL                 COMMENT 'Vidéo, PDF, TP, Projet',
    statut         VARCHAR(20)   DEFAULT 'PUBLIE'         COMMENT 'Statut',
    CONSTRAINT pk_cours PRIMARY KEY (id_cours),
    CONSTRAINT fk_cours_module FOREIGN KEY (id_module) REFERENCES modules (id_module),
    CONSTRAINT ck_cours_ordre CHECK (ordre > 0),
    CONSTRAINT ck_cours_duree CHECK (duree_minutes > 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci
  COMMENT = 'Cours (PDF Source 2, table 2)';

-- -----------------------------------------------------------------------------
-- 3. quiz — quiz associés aux cours
-- -----------------------------------------------------------------------------
CREATE TABLE quiz (
    id_quiz        CHAR(36)      NOT NULL                 COMMENT 'Identifiant (UUID)',
    id_cours       CHAR(36)                               COMMENT 'Cours',
    titre          VARCHAR(150)  NOT NULL                 COMMENT 'Titre',
    nb_questions   INT                                    COMMENT 'Nombre de questions',
    score_max      DECIMAL(5,2)                           COMMENT 'Score maximal',
    duree_minutes  INT                                    COMMENT 'Durée - valeurs incohérentes volontaires (B04)',
    CONSTRAINT pk_quiz PRIMARY KEY (id_quiz),
    CONSTRAINT fk_quiz_cours FOREIGN KEY (id_cours) REFERENCES cours (id_cours),
    CONSTRAINT ck_quiz_nb_questions CHECK (nb_questions > 0),
    CONSTRAINT ck_quiz_score_max CHECK (score_max > 0),
    -- B04 : durées nulles volontaires
    CONSTRAINT ck_quiz_duree CHECK (duree_minutes > 0) NOT ENFORCED
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci
  COMMENT = 'Quiz (PDF Source 2, table 3)';

-- -----------------------------------------------------------------------------
-- 4. notes — résultats des étudiants aux quiz
--    PDF : « Ne pas utiliser id_etudiant de PostgreSQL. Utiliser student_code ».
-- -----------------------------------------------------------------------------
CREATE TABLE notes (
    id_note        CHAR(36)      NOT NULL                 COMMENT 'Identifiant (UUID)',
    id_quiz        CHAR(36)                               COMMENT 'Quiz',
    student_code   VARCHAR(30)   NOT NULL                 COMMENT 'Identifiant LMS (LMS-XXXXXX) - formats incompatibles (B13)',
    date_passage   TIMESTAMP     NOT NULL                 COMMENT 'Date',
    score          DECIMAL(5,2)                           COMMENT 'Score obtenu - > score_max volontaire (B14)',
    tentative      INT           DEFAULT 1                COMMENT 'Tentative',
    valide         TINYINT(1)    DEFAULT 0                COMMENT 'Quiz validé',
    CONSTRAINT pk_notes PRIMARY KEY (id_note),
    CONSTRAINT fk_notes_quiz FOREIGN KEY (id_quiz) REFERENCES quiz (id_quiz),
    CONSTRAINT ck_notes_score CHECK (score >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci
  COMMENT = 'Résultats aux quiz (PDF Source 2, table 4). Doublons volontaires (B12)';

CREATE INDEX idx_notes_student_code ON notes (student_code);

-- -----------------------------------------------------------------------------
-- 5. progression — suivi de l'avancement
--    Règle du PDF « une seule progression par étudiant et par module » :
--    PAS de contrainte UNIQUE, car des doublons sont volontaires (B15).
--    Index non unique à la place ; la règle est contrôlée en qualité.
-- -----------------------------------------------------------------------------
CREATE TABLE progression (
    id_progression CHAR(36)      NOT NULL                 COMMENT 'Identifiant (UUID)',
    student_code   VARCHAR(30)   NOT NULL                 COMMENT 'Étudiant (LMS)',
    id_module      CHAR(36)                               COMMENT 'Module - modules inexistants volontaires (B07)',
    pourcentage    DECIMAL(5,2)                           COMMENT 'Progression - > 100 (B05) et < 0 (B06) volontaires',
    dernier_cours  CHAR(36)      NULL                     COMMENT 'Dernier cours consulté (UUID, pas de FK dans le PDF)',
    date_maj       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT 'Dernière mise à jour',
    CONSTRAINT pk_progression PRIMARY KEY (id_progression),
    CONSTRAINT fk_progression_module FOREIGN KEY (id_module) REFERENCES modules (id_module),
    CONSTRAINT ck_progression_pourcentage CHECK (pourcentage BETWEEN 0 AND 100) NOT ENFORCED
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci
  COMMENT = 'Progression par étudiant et par module (PDF Source 2, table 5)';

CREATE INDEX idx_progression_etudiant_module ON progression (student_code, id_module);

-- -----------------------------------------------------------------------------
-- 6. temps_connexion — historique des connexions
-- -----------------------------------------------------------------------------
CREATE TABLE temps_connexion (
    id_connexion     CHAR(36)     NOT NULL                COMMENT 'Identifiant (UUID)',
    student_code     VARCHAR(30)  NOT NULL                COMMENT 'Étudiant (LMS)',
    date_connexion   TIMESTAMP    NOT NULL                COMMENT 'Début',
    date_deconnexion TIMESTAMP    NULL                    COMMENT 'Fin - absente volontairement (B08)',
    duree_minutes    INT                                  COMMENT 'Durée - négatives volontaires (B09)',
    appareil         VARCHAR(50)  NULL                    COMMENT 'Mobile, PC, Tablette - écritures variables (B11)',
    navigateur       VARCHAR(50)  NULL                    COMMENT 'Chrome, Firefox... - manquant volontairement (B16)',
    adresse_ip       VARCHAR(45)  NULL                    COMMENT 'IPv4 ou IPv6 - invalides volontaires (B10)',
    CONSTRAINT pk_temps_connexion PRIMARY KEY (id_connexion),
    CONSTRAINT ck_temps_connexion_duree CHECK (duree_minutes >= 0) NOT ENFORCED
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci
  COMMENT = 'Historique des connexions (PDF Source 2, table 6)';

CREATE INDEX idx_temps_connexion_student ON temps_connexion (student_code);
