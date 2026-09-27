-- =============================================================================
-- Couche CLEAN — Source 2 MySQL (Lot L5)
-- staging.stg_mysql_* -> clean.modules, cours, quiz, notes, progression, temps_connexion, comptes_lms
-- =============================================================================
SELECT quality.reinitialiser('s2_mysql');

-- ------------------------------------------------------------------ modules --
DROP TABLE IF EXISTS t_mod;
CREATE TEMP TABLE t_mod AS
SELECT s.*, clean.synonyme('categorie_module', s.categorie) AS categorie_c, clean.booleen(s.actif) AS actif_b
FROM staging.stg_mysql_modules s;
SELECT quality.constater('MY_CATEGORIE', 'modules', 'SELECT id_module, categorie, categorie_c FROM t_mod WHERE categorie_c IS NOT NULL AND categorie <> categorie_c');
SELECT quality.constater('MY_CATEGORIE_INCONNUE', 'modules', 'SELECT id_module, categorie, NULL FROM t_mod WHERE categorie_c IS NULL');
SELECT quality.constater('MY_MODULE_INACTIF', 'modules', 'SELECT id_module, actif, NULL FROM t_mod WHERE NOT actif_b');

DROP TABLE IF EXISTS clean.modules CASCADE;
CREATE TABLE clean.modules AS
SELECT t.id_module::UUID AS id_module, t.code_module, t.nom_module, COALESCE(t.categorie_c, t.categorie) AS categorie,
       t.niveau, t.duree_heures::INT AS duree_heures, t.actif_b AS actif,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_mod t LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'modules') a ON a.id_ligne = t.id_module;
ALTER TABLE clean.modules ADD PRIMARY KEY (id_module);

-- -------------------------------------------------------------------- cours --
DROP TABLE IF EXISTS t_cou;
CREATE TEMP TABLE t_cou AS
SELECT s.*, COUNT(*) OVER (PARTITION BY s.titre) AS nb_titre FROM staging.stg_mysql_cours s;
SELECT quality.constater('MY_TITRE_DOUBLON', 'cours', 'SELECT id_cours, titre, NULL FROM t_cou WHERE nb_titre > 1');

DROP TABLE IF EXISTS clean.cours CASCADE;
CREATE TABLE clean.cours AS
SELECT t.id_cours::UUID AS id_cours, t.id_module::UUID AS id_module, m.code_externe AS code_cours, t.titre,
       t.ordre::INT AS ordre, t.duree_minutes::INT AS duree_minutes, t.type_cours, t.statut,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_cou t
LEFT JOIN clean.ref_mapping_contenus m ON m.type_objet = 'COURSE' AND m.id_mysql = t.id_cours
LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'cours') a ON a.id_ligne = t.id_cours;
ALTER TABLE clean.cours ADD PRIMARY KEY (id_cours);

-- --------------------------------------------------------------------- quiz --
DROP TABLE IF EXISTS t_qui;
CREATE TEMP TABLE t_qui AS
SELECT s.*, s.duree_minutes::INT AS duree_i, s.nb_questions::INT AS nb_i FROM staging.stg_mysql_quiz s;
SELECT quality.constater('MY_QUIZ_DUREE', 'quiz', $q$
    SELECT id_quiz, duree_minutes, NULL FROM t_qui
    WHERE duree_i <= 0 OR duree_i::NUMERIC / nb_i < 0.25 OR duree_i::NUMERIC / nb_i > 10 $q$);

DROP TABLE IF EXISTS clean.quiz CASCADE;
CREATE TABLE clean.quiz AS
SELECT t.id_quiz::UUID AS id_quiz, t.id_cours::UUID AS id_cours, m.code_externe AS code_quiz, t.titre,
       t.nb_i AS nb_questions, t.score_max::NUMERIC(5,2) AS score_max,
       CASE WHEN NOT (t.duree_i <= 0 OR t.duree_i::NUMERIC / t.nb_i < 0.25 OR t.duree_i::NUMERIC / t.nb_i > 10)
            THEN t.duree_i END AS duree_minutes,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_qui t
LEFT JOIN clean.ref_mapping_contenus m ON m.type_objet = 'QUIZ' AND m.id_mysql = t.id_quiz
LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'quiz') a ON a.id_ligne = t.id_quiz;
ALTER TABLE clean.quiz ADD PRIMARY KEY (id_quiz);

-- -------------------------------------------------------------------- notes --
DROP TABLE IF EXISTS t_not;
CREATE TEMP TABLE t_not AS
SELECT s.*, clean.student_code(s.student_code) AS code_c, clean.nombre(s.score) AS score_n, q.score_max,
       row_number() OVER (PARTITION BY s.id_quiz, s.student_code, s.tentative, s.date_passage
                          ORDER BY s.id_note) AS rn,
       first_value(s.id_note) OVER (PARTITION BY s.id_quiz, s.student_code, s.tentative, s.date_passage
                                    ORDER BY s.id_note) AS conservee
FROM staging.stg_mysql_notes s LEFT JOIN clean.quiz q ON q.id_quiz = s.id_quiz::UUID;

SELECT quality.rejeter('MY_NOTE_DOUBLON', 'notes', $q$
    SELECT t.id_note, t._row_number, 'Doublon de ' || t.conservee, to_jsonb(s)
    FROM t_not t JOIN staging.stg_mysql_notes s USING (_row_number) WHERE t.rn > 1 $q$);
SELECT quality.constater('MY_STUDENT_CODE', 'notes', 'SELECT id_note, student_code, code_c FROM t_not WHERE code_c IS NOT NULL AND student_code <> code_c');
SELECT quality.constater('MY_STUDENT_CODE_INVALIDE', 'notes', 'SELECT id_note, student_code, NULL FROM t_not WHERE code_c IS NULL');
SELECT quality.constater('MY_SCORE_SUP_MAX', 'notes', 'SELECT id_note, score, NULL FROM t_not WHERE score_n > score_max');

DROP TABLE IF EXISTS clean.notes CASCADE;
CREATE TABLE clean.notes AS
SELECT t.id_note::UUID AS id_note, t.id_quiz::UUID AS id_quiz, t.code_c AS student_code,
       t.date_passage::TIMESTAMP AS date_passage,
       CASE WHEN t.score_n <= t.score_max THEN t.score_n END::NUMERIC(5,2) AS score,
       t.tentative::INT AS tentative, clean.booleen(t.valide) AS valide,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_not t LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'notes') a ON a.id_ligne = t.id_note
WHERE t.rn = 1;
ALTER TABLE clean.notes ADD PRIMARY KEY (id_note);

-- -------------------------------------------------------------- progression --
DROP TABLE IF EXISTS t_pro;
CREATE TEMP TABLE t_pro AS
SELECT s.*, clean.nombre(s.pourcentage) AS pct, (m.id_module IS NOT NULL) AS module_connu,
       row_number() OVER (PARTITION BY s.student_code, s.id_module ORDER BY s.id_progression) AS rn,
       first_value(s.id_progression) OVER (PARTITION BY s.student_code, s.id_module ORDER BY s.id_progression) AS conservee
FROM staging.stg_mysql_progression s LEFT JOIN clean.modules m ON m.id_module = s.id_module::UUID;

SELECT quality.rejeter('MY_PROGRESSION_MODULE_INCONNU', 'progression', $q$
    SELECT t.id_progression, t._row_number, 'Module ' || t.id_module || ' inexistant', to_jsonb(s)
    FROM t_pro t JOIN staging.stg_mysql_progression s USING (_row_number) WHERE NOT t.module_connu $q$);
SELECT quality.rejeter('MY_PROGRESSION_DOUBLON', 'progression', $q$
    SELECT t.id_progression, t._row_number, 'Doublon de ' || t.conservee, to_jsonb(s)
    FROM t_pro t JOIN staging.stg_mysql_progression s USING (_row_number) WHERE t.module_connu AND t.rn > 1 $q$);
SELECT quality.constater('MY_PROGRESSION_HORS_BORNES', 'progression', 'SELECT id_progression, pourcentage, NULL FROM t_pro WHERE pct NOT BETWEEN 0 AND 100');

DROP TABLE IF EXISTS clean.progression CASCADE;
CREATE TABLE clean.progression AS
SELECT t.id_progression::UUID AS id_progression, t.student_code, t.id_module::UUID AS id_module,
       CASE WHEN t.pct BETWEEN 0 AND 100 THEN t.pct END::NUMERIC(5,2) AS pourcentage,
       t.dernier_cours::UUID AS dernier_cours, t.date_maj::TIMESTAMP AS date_maj,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_pro t LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'progression') a ON a.id_ligne = t.id_progression
WHERE NOT EXISTS (SELECT 1 FROM quality.rejets r WHERE r.batch_id = current_setting('edusmart.batch_id')
                  AND r.code_source = 's2_mysql' AND r.table_source = 'progression' AND r.rang = t._row_number);
ALTER TABLE clean.progression ADD PRIMARY KEY (id_progression);

-- ---------------------------------------------------------- temps_connexion --
DROP TABLE IF EXISTS t_con;
CREATE TEMP TABLE t_con AS
SELECT s.*, s.date_connexion::TIMESTAMP AS debut, s.date_deconnexion::TIMESTAMP AS fin, s.duree_minutes::INT AS duree_i,
       clean.synonyme('appareil', s.appareil) AS appareil_c, clean.ip_valide(s.adresse_ip) AS ip_ok
FROM staging.stg_mysql_temps_connexion s;
ALTER TABLE t_con ADD COLUMN duree_c INT;
UPDATE t_con SET duree_c = CASE WHEN duree_i < 0 AND fin IS NOT NULL
                                THEN round(extract(EPOCH FROM fin - debut) / 60)::INT ELSE duree_i END;

SELECT quality.constater('MY_CONNEXION_SANS_FIN', 'temps_connexion', 'SELECT id_connexion, NULL, NULL FROM t_con WHERE fin IS NULL');
SELECT quality.constater('MY_DUREE_NEGATIVE', 'temps_connexion', 'SELECT id_connexion, duree_minutes, duree_c FROM t_con WHERE duree_i < 0');
SELECT quality.constater('MY_IP_INVALIDE', 'temps_connexion', 'SELECT id_connexion, adresse_ip, NULL FROM t_con WHERE NOT ip_ok');
SELECT quality.constater('MY_APPAREIL', 'temps_connexion', 'SELECT id_connexion, appareil, appareil_c FROM t_con WHERE appareil_c IS NOT NULL AND appareil <> appareil_c');
SELECT quality.constater('MY_APPAREIL_INCONNU', 'temps_connexion', 'SELECT id_connexion, appareil, NULL FROM t_con WHERE appareil IS NOT NULL AND appareil_c IS NULL');
SELECT quality.constater('MY_NAVIGATEUR_MANQUANT', 'temps_connexion', 'SELECT id_connexion, NULL, NULL FROM t_con WHERE navigateur IS NULL');

DROP TABLE IF EXISTS clean.temps_connexion CASCADE;
CREATE TABLE clean.temps_connexion AS
SELECT t.id_connexion::UUID AS id_connexion, t.student_code, t.debut AS date_connexion, t.fin AS date_deconnexion,
       CASE WHEN t.duree_c >= 0 THEN t.duree_c END AS duree_minutes,
       CASE WHEN t.duree_c >= 0 THEN t.duree_c * 60 END AS duree_secondes,
       COALESCE(t.appareil_c, t.appareil) AS appareil, t.navigateur,
       CASE WHEN t.ip_ok THEN t.adresse_ip END AS adresse_ip,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_con t LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'temps_connexion') a ON a.id_ligne = t.id_connexion;
ALTER TABLE clean.temps_connexion ADD PRIMARY KEY (id_connexion);

-- --------------------------------------------------------------- comptes_lms --
-- Population des comptes LMS (codes valides observés dans MySQL), rapprochée de PostgreSQL
DROP TABLE IF EXISTS t_lms;
CREATE TEMP TABLE t_lms AS
SELECT c.student_code, m.id_etudiant, m.matricule
FROM (SELECT student_code FROM clean.notes WHERE student_code IS NOT NULL
      UNION SELECT student_code FROM clean.progression UNION SELECT student_code FROM clean.temps_connexion) c
LEFT JOIN clean.ref_mapping_etudiants m ON m.student_code = c.student_code;
SELECT quality.constater('MY_LMS_SANS_INSCRIPTION', 'comptes_lms', 'SELECT student_code, NULL, NULL FROM t_lms WHERE id_etudiant IS NULL');

DROP TABLE IF EXISTS clean.comptes_lms CASCADE;
CREATE TABLE clean.comptes_lms AS
SELECT t.student_code, t.id_etudiant, t.matricule, (t.id_etudiant IS NOT NULL) AS a_inscription,
       COALESCE(a.codes, '{}') AS _anomalies
FROM t_lms t LEFT JOIN quality.anomalies_par_ligne('s2_mysql', 'comptes_lms') a ON a.id_ligne = t.student_code;
ALTER TABLE clean.comptes_lms ADD PRIMARY KEY (student_code);

-- Statistiques à jour pour le planificateur (tables recréées)
ANALYZE clean.modules, clean.cours, clean.quiz, clean.notes, clean.progression, clean.temps_connexion, clean.comptes_lms;
