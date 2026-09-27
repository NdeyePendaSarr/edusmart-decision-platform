-- =============================================================================
-- EduSmart Data Warehouse — Couche STAGING (bronze), Lot L4
-- Fichier GÉNÉRÉ depuis pipeline/registry.py (python -m pipeline.registry).
-- Ne pas modifier à la main : un test vérifie qu'il correspond au registre.
--
-- Principe ELT : toutes les colonnes source en TEXT (JSONB pour MongoDB et
-- Redis). Aucune valeur n'est interprétée ni corrigée à ce stade : un montant
-- négatif, une date '12/09/2026' ou un sexe 'Garçon' se chargent sans erreur.
-- Colonnes techniques : lot, source, instant d'extraction, rang de la ligne.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS staging;

-- s1_postgresql.etudiants : Étudiants (gestion académique)
CREATE TABLE IF NOT EXISTS staging.stg_pg_etudiants (
    id_etudiant          TEXT,
    matricule            TEXT,
    nom                  TEXT,
    prenom               TEXT,
    sexe                 TEXT,
    date_naissance       TEXT,
    telephone            TEXT,
    email                TEXT,
    adresse              TEXT,
    ville                TEXT,
    region               TEXT,
    pays                 TEXT,
    date_creation        TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_pg_etudiants PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_pg_etudiants IS 'Bronze - s1_postgresql.etudiants (PostgreSQL 15), copie brute';

-- s1_postgresql.filieres : Formations proposées
CREATE TABLE IF NOT EXISTS staging.stg_pg_filieres (
    id_filiere           TEXT,
    code_filiere         TEXT,
    nom_filiere          TEXT,
    departement          TEXT,
    niveau               TEXT,
    duree_mois           TEXT,
    cout_total           TEXT,
    statut               TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_pg_filieres PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_pg_filieres IS 'Bronze - s1_postgresql.filieres (PostgreSQL 15), copie brute';

-- s1_postgresql.classes : Classes par filière et année
CREATE TABLE IF NOT EXISTS staging.stg_pg_classes (
    id_classe            TEXT,
    code_classe          TEXT,
    nom_classe           TEXT,
    id_filiere           TEXT,
    annee_academique     TEXT,
    capacite             TEXT,
    salle                TEXT,
    responsable          TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_pg_classes PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_pg_classes IS 'Bronze - s1_postgresql.classes (PostgreSQL 15), copie brute';

-- s1_postgresql.inscriptions : Inscriptions étudiant / classe
CREATE TABLE IF NOT EXISTS staging.stg_pg_inscriptions (
    id_inscription       TEXT,
    id_etudiant          TEXT,
    id_classe            TEXT,
    date_inscription     TEXT,
    statut               TEXT,
    type_inscription     TEXT,
    bourse               TEXT,
    reduction            TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_pg_inscriptions PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_pg_inscriptions IS 'Bronze - s1_postgresql.inscriptions (PostgreSQL 15), copie brute';

-- s1_postgresql.paiements : Paiements des étudiants
CREATE TABLE IF NOT EXISTS staging.stg_pg_paiements (
    id_paiement          TEXT,
    id_inscription       TEXT,
    reference            TEXT,
    date_paiement        TEXT,
    montant              TEXT,
    mode_paiement        TEXT,
    statut               TEXT,
    tranche              TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_pg_paiements PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_pg_paiements IS 'Bronze - s1_postgresql.paiements (PostgreSQL 15), copie brute';

-- s2_mysql.modules : Modules de formation
CREATE TABLE IF NOT EXISTS staging.stg_mysql_modules (
    id_module            TEXT,
    code_module          TEXT,
    nom_module           TEXT,
    categorie            TEXT,
    niveau               TEXT,
    duree_heures         TEXT,
    actif                TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mysql_modules PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mysql_modules IS 'Bronze - s2_mysql.modules (MySQL 8.0), copie brute';

-- s2_mysql.cours : Cours des modules
CREATE TABLE IF NOT EXISTS staging.stg_mysql_cours (
    id_cours             TEXT,
    id_module            TEXT,
    titre                TEXT,
    ordre                TEXT,
    duree_minutes        TEXT,
    type_cours           TEXT,
    statut               TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mysql_cours PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mysql_cours IS 'Bronze - s2_mysql.cours (MySQL 8.0), copie brute';

-- s2_mysql.quiz : Quiz des cours
CREATE TABLE IF NOT EXISTS staging.stg_mysql_quiz (
    id_quiz              TEXT,
    id_cours             TEXT,
    titre                TEXT,
    nb_questions         TEXT,
    score_max            TEXT,
    duree_minutes        TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mysql_quiz PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mysql_quiz IS 'Bronze - s2_mysql.quiz (MySQL 8.0), copie brute';

-- s2_mysql.notes : Résultats aux quiz
CREATE TABLE IF NOT EXISTS staging.stg_mysql_notes (
    id_note              TEXT,
    id_quiz              TEXT,
    student_code         TEXT,
    date_passage         TEXT,
    score                TEXT,
    tentative            TEXT,
    valide               TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mysql_notes PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mysql_notes IS 'Bronze - s2_mysql.notes (MySQL 8.0), copie brute';

-- s2_mysql.progression : Progression par module
CREATE TABLE IF NOT EXISTS staging.stg_mysql_progression (
    id_progression       TEXT,
    student_code         TEXT,
    id_module            TEXT,
    pourcentage          TEXT,
    dernier_cours        TEXT,
    date_maj             TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mysql_progression PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mysql_progression IS 'Bronze - s2_mysql.progression (MySQL 8.0), copie brute';

-- s2_mysql.temps_connexion : Historique des connexions
CREATE TABLE IF NOT EXISTS staging.stg_mysql_temps_connexion (
    id_connexion         TEXT,
    student_code         TEXT,
    date_connexion       TEXT,
    date_deconnexion     TEXT,
    duree_minutes        TEXT,
    appareil             TEXT,
    navigateur           TEXT,
    adresse_ip           TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mysql_temps_connexion PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mysql_temps_connexion IS 'Bronze - s2_mysql.temps_connexion (MySQL 8.0), copie brute';

-- s3_csv.enseignants : Enseignants (export RH)
CREATE TABLE IF NOT EXISTS staging.stg_csv_enseignants (
    teacher_code         TEXT,
    nom                  TEXT,
    prenom               TEXT,
    sexe                 TEXT,
    date_naissance       TEXT,
    telephone            TEXT,
    email                TEXT,
    specialite           TEXT,
    grade                TEXT,
    date_embauche        TEXT,
    statut               TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_csv_enseignants PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_csv_enseignants IS 'Bronze - s3_csv.enseignants (Fichier CSV), copie brute';

-- s3_csv.departements : Départements (export RH)
CREATE TABLE IF NOT EXISTS staging.stg_csv_departements (
    id_departement       TEXT,
    nom_departement      TEXT,
    responsable          TEXT,
    budget_annuel        TEXT,
    batiment             TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_csv_departements PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_csv_departements IS 'Bronze - s3_csv.departements (Fichier CSV), copie brute';

-- s3_csv.salaires : Salaires des enseignants (export RH)
CREATE TABLE IF NOT EXISTS staging.stg_csv_salaires (
    id_salaire           TEXT,
    teacher_code         TEXT,
    mois                 TEXT,
    annee                TEXT,
    salaire_base         TEXT,
    primes               TEXT,
    retenues             TEXT,
    salaire_net          TEXT,
    mode_paiement        TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_csv_salaires PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_csv_salaires IS 'Bronze - s3_csv.salaires (Fichier CSV), copie brute';

-- s3_csv.absences : Absences des enseignants (export RH)
CREATE TABLE IF NOT EXISTS staging.stg_csv_absences (
    id_absence           TEXT,
    teacher_code         TEXT,
    date_absence         TEXT,
    motif                TEXT,
    justifiee            TEXT,
    duree_heures         TEXT,
    remplace             TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_csv_absences PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_csv_absences IS 'Bronze - s3_csv.absences (Fichier CSV), copie brute';

-- s4_mongodb.events : Journaux de l'application mobile (document JSON complet)
CREATE TABLE IF NOT EXISTS staging.stg_mongo_events (
    _mongo_id            TEXT,
    event_id             TEXT,
    document             JSONB,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_mongo_events PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_mongo_events IS 'Bronze - s4_mongodb.events (MongoDB 6), copie brute';

-- s5_redis.keys : Snapshot de toutes les clés (type, valeur, durée de vie)
CREATE TABLE IF NOT EXISTS staging.stg_redis_keys (
    cle                  TEXT,
    type_redis           TEXT,
    valeur               JSONB,
    ttl                  TEXT,
    _batch_id            TEXT      NOT NULL,
    _source              TEXT      NOT NULL,
    _extracted_at        TIMESTAMP NOT NULL,
    _row_number          INTEGER   NOT NULL,
    CONSTRAINT pk_stg_redis_keys PRIMARY KEY (_batch_id, _row_number)
);
COMMENT ON TABLE staging.stg_redis_keys IS 'Bronze - s5_redis.keys (Redis 7), copie brute';
