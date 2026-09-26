-- =============================================================================
-- EduSmart — Source 1 : PostgreSQL « Gestion académique »
-- Fichier : add_constraints.sql  (2/3 : contraintes, APRÈS insertion)
-- -----------------------------------------------------------------------------
-- Rappel du mécanisme NOT VALID :
--   ALTER TABLE ... ADD CONSTRAINT ... NOT VALID
--   -> la contrainte est créée SANS vérifier les lignes existantes ;
--   -> toute NOUVELLE ligne (INSERT/UPDATE) est vérifiée.
-- La structure cible du PDF est donc documentée et active, tout en
-- conservant les anomalies pédagogiques déjà présentes.
--
-- Deux familles de contraintes :
--   (A) Contraintes que les anomalies VIOLENT       -> NOT VALID (restent non validées)
--   (B) Contraintes qu'aucune anomalie ne concerne  -> NOT VALID puis VALIDATE
--       immédiatement : si l'une échoue, la génération a un bug.
-- Script idempotent (DROP CONSTRAINT IF EXISTS).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (A) Contraintes volontairement NON VALIDÉES
-- -----------------------------------------------------------------------------

-- A01 : sexe ('Homme', 'Garçon', '1'...)
ALTER TABLE etudiants DROP CONSTRAINT IF EXISTS ck_etudiants_sexe;
ALTER TABLE etudiants ADD CONSTRAINT ck_etudiants_sexe
    CHECK (sexe IN ('M', 'F')) NOT VALID;

-- A11 : réductions supérieures à 100 %
ALTER TABLE inscriptions DROP CONSTRAINT IF EXISTS ck_inscriptions_reduction;
ALTER TABLE inscriptions ADD CONSTRAINT ck_inscriptions_reduction
    CHECK (reduction BETWEEN 0 AND 100) NOT VALID;

-- A14 : montants négatifs
ALTER TABLE paiements DROP CONSTRAINT IF EXISTS ck_paiements_montant;
ALTER TABLE paiements ADD CONSTRAINT ck_paiements_montant
    CHECK (montant >= 0) NOT VALID;

-- A16 : paiements orphelins (inscription inexistante)
ALTER TABLE paiements DROP CONSTRAINT IF EXISTS fk_paiements_inscription;
ALTER TABLE paiements ADD CONSTRAINT fk_paiements_inscription
    FOREIGN KEY (id_inscription) REFERENCES inscriptions (id_inscription) NOT VALID;

-- A13 : reference UNIQUE (PDF) — NON POSÉE.
-- PostgreSQL ne propose pas de UNIQUE « NOT VALID » : la contrainte échouerait
-- à cause des doublons volontaires. On la documente et on crée un index
-- NON unique pour les recherches. Contrainte cible, après nettoyage :
--   ALTER TABLE paiements ADD CONSTRAINT uq_paiements_reference UNIQUE (reference);
DROP INDEX IF EXISTS idx_paiements_reference;
CREATE INDEX idx_paiements_reference ON paiements (reference);

-- -----------------------------------------------------------------------------
-- (B) Contraintes VALIDÉES (aucune anomalie ne les concerne)
-- -----------------------------------------------------------------------------

-- « La date de naissance doit être antérieure à la date actuelle » (PDF).
-- NB : CURRENT_DATE dans un CHECK est accepté par PostgreSQL ; la condition
-- ne peut que rester vraie avec le temps pour une date passée.
ALTER TABLE etudiants DROP CONSTRAINT IF EXISTS ck_etudiants_date_naissance;
ALTER TABLE etudiants ADD CONSTRAINT ck_etudiants_date_naissance
    CHECK (date_naissance < CURRENT_DATE) NOT VALID;
ALTER TABLE etudiants VALIDATE CONSTRAINT ck_etudiants_date_naissance;

ALTER TABLE filieres DROP CONSTRAINT IF EXISTS ck_filieres_duree;
ALTER TABLE filieres ADD CONSTRAINT ck_filieres_duree CHECK (duree_mois > 0) NOT VALID;
ALTER TABLE filieres VALIDATE CONSTRAINT ck_filieres_duree;

ALTER TABLE filieres DROP CONSTRAINT IF EXISTS ck_filieres_cout;
ALTER TABLE filieres ADD CONSTRAINT ck_filieres_cout CHECK (cout_total >= 0) NOT VALID;
ALTER TABLE filieres VALIDATE CONSTRAINT ck_filieres_cout;

ALTER TABLE classes DROP CONSTRAINT IF EXISTS ck_classes_capacite;
ALTER TABLE classes ADD CONSTRAINT ck_classes_capacite CHECK (capacite > 0) NOT VALID;
ALTER TABLE classes VALIDATE CONSTRAINT ck_classes_capacite;

ALTER TABLE classes DROP CONSTRAINT IF EXISTS fk_classes_filiere;
ALTER TABLE classes ADD CONSTRAINT fk_classes_filiere
    FOREIGN KEY (id_filiere) REFERENCES filieres (id_filiere) NOT VALID;
ALTER TABLE classes VALIDATE CONSTRAINT fk_classes_filiere;

ALTER TABLE inscriptions DROP CONSTRAINT IF EXISTS fk_inscriptions_etudiant;
ALTER TABLE inscriptions ADD CONSTRAINT fk_inscriptions_etudiant
    FOREIGN KEY (id_etudiant) REFERENCES etudiants (id_etudiant) NOT VALID;
ALTER TABLE inscriptions VALIDATE CONSTRAINT fk_inscriptions_etudiant;

ALTER TABLE inscriptions DROP CONSTRAINT IF EXISTS fk_inscriptions_classe;
ALTER TABLE inscriptions ADD CONSTRAINT fk_inscriptions_classe
    FOREIGN KEY (id_classe) REFERENCES classes (id_classe) NOT VALID;
ALTER TABLE inscriptions VALIDATE CONSTRAINT fk_inscriptions_classe;

-- -----------------------------------------------------------------------------
-- Index de performance sur les clés étrangères (utiles pour l'extraction ETL)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_classes_filiere        ON classes (id_filiere);
CREATE INDEX IF NOT EXISTS idx_inscriptions_etudiant  ON inscriptions (id_etudiant);
CREATE INDEX IF NOT EXISTS idx_inscriptions_classe    ON inscriptions (id_classe);
CREATE INDEX IF NOT EXISTS idx_paiements_inscription  ON paiements (id_inscription);

COMMIT;
