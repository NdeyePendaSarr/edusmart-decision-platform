-- =============================================================================
-- Couche CLEAN — Source 5 Redis (Lot L5)
-- staging.stg_redis_keys (une ligne par clé) -> clean.redis_sessions, redis_last_course, redis_last_quiz,
--   redis_progress, redis_notifications, redis_leaderboard, redis_compteurs
-- Dépend de clean.evenements (MongoDB) et clean.comptes_lms (MySQL) : à exécuter APRÈS S2 et S4.
-- Instant de référence : edusmart.redis_snapshot (C24, 15/09/2026 23:00), et non l'heure réelle.
-- =============================================================================
SELECT quality.reinitialiser('s5_redis');

-- --------------------------------------------------------------- sessions --
DROP TABLE IF EXISTS t_ses;
CREATE TEMP TABLE t_ses AS
SELECT s.cle, s._row_number, substr(s.cle, 9) AS session_id, s.valeur ->> 'student_code' AS code,
       s.valeur ->> 'status' AS status, (s.valeur ->> 'login_time')::TIMESTAMP AS login_time,
       (s.valeur ->> 'last_activity')::TIMESTAMP AS last_activity, s.valeur ->> 'device' AS plateforme,
       s.valeur ->> 'ip' AS ip, s.ttl::INT AS ttl, s._batch_id,
       CASE WHEN (s.valeur ->> 'last_activity')::TIMESTAMP < current_setting('edusmart.redis_snapshot')::TIMESTAMP - INTERVAL '24 hours' THEN 'EXPIREE'
            WHEN (s.valeur ->> 'last_activity')::TIMESTAMP < current_setting('edusmart.redis_snapshot')::TIMESTAMP - INTERVAL '30 minutes' THEN 'INACTIVE'
            ELSE 'ONLINE' END AS statut_c,
       m.code_mongo
FROM staging.stg_redis_keys s
LEFT JOIN (SELECT session_id, min(student_code) AS code_mongo FROM clean.evenements
           WHERE session_id IN (SELECT substr(cle, 9) FROM staging.stg_redis_keys WHERE cle LIKE 'session:%')
           GROUP BY session_id) m ON m.session_id = substr(s.cle, 9)
WHERE s.cle LIKE 'session:%';

SELECT quality.constater('RD_SESSION_EXPIREE', 'sessions', 'SELECT cle, status, statut_c FROM t_ses WHERE statut_c = ''EXPIREE''');
SELECT quality.constater('RD_SESSION_INACTIVE', 'sessions', 'SELECT cle, status, statut_c FROM t_ses WHERE statut_c = ''INACTIVE''');
SELECT quality.constater('RD_SESSION_ETUDIANT_RECUPERE', 'sessions', 'SELECT cle, NULL, code_mongo FROM t_ses WHERE code IS NULL AND code_mongo IS NOT NULL');
SELECT quality.constater('RD_SESSION_SANS_ETUDIANT', 'sessions', 'SELECT cle, NULL, NULL FROM t_ses WHERE code IS NULL AND code_mongo IS NULL');

DROP TABLE IF EXISTS clean.redis_sessions CASCADE;
CREATE TABLE clean.redis_sessions AS
SELECT t.session_id, COALESCE(t.code, t.code_mongo) AS student_code, t.statut_c AS statut, t.status AS statut_source,
       t.login_time, t.last_activity, t.plateforme, t.ip, t.ttl, COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_ses t LEFT JOIN quality.anomalies_par_ligne('s5_redis', 'sessions') a ON a.id_ligne = t.cle;
ALTER TABLE clean.redis_sessions ADD PRIMARY KEY (session_id);

-- ----------------------------------------------- étudiants inconnus (E06) --
-- Population de référence : les comptes LMS observés dans MySQL (clean.comptes_lms)
DROP TABLE IF EXISTS t_cles_etudiant;
CREATE TEMP TABLE t_cles_etudiant AS
SELECT s.*, split_part(s.cle, ':', 1) AS famille, substr(s.cle, strpos(s.cle, ':') + 1) AS code,
       EXISTS (SELECT 1 FROM clean.comptes_lms c WHERE c.student_code = substr(s.cle, strpos(s.cle, ':') + 1)) AS connu
FROM staging.stg_redis_keys s
WHERE split_part(s.cle, ':', 1) IN ('last_course', 'last_quiz', 'progress', 'notifications');

SELECT quality.rejeter('RD_ETUDIANT_INCONNU', 'cles_etudiant', $q$
    SELECT code, _row_number, 'Clé ' || cle || ' : étudiant absent des autres systèmes', to_jsonb(t) - 'connu'
    FROM t_cles_etudiant t WHERE NOT connu $q$);

-- ---------------------------------------------------- dernier cours / quiz --
DROP TABLE IF EXISTS clean.redis_last_course CASCADE;
CREATE TABLE clean.redis_last_course AS
SELECT t.code AS student_code, t.valeur #>> '{}' AS course_code, m.id_mysql::UUID AS id_cours, t._batch_id
FROM t_cles_etudiant t LEFT JOIN clean.ref_mapping_contenus m ON m.code_externe = t.valeur #>> '{}'
WHERE t.famille = 'last_course' AND t.connu;
ALTER TABLE clean.redis_last_course ADD PRIMARY KEY (student_code);

DROP TABLE IF EXISTS clean.redis_last_quiz CASCADE;
CREATE TABLE clean.redis_last_quiz AS
SELECT t.code AS student_code, t.valeur #>> '{}' AS quiz_code, m.id_mysql::UUID AS id_quiz, t._batch_id
FROM t_cles_etudiant t LEFT JOIN clean.ref_mapping_contenus m ON m.code_externe = t.valeur #>> '{}'
WHERE t.famille = 'last_quiz' AND t.connu;
ALTER TABLE clean.redis_last_quiz ADD PRIMARY KEY (student_code);

-- --------------------------------------------------------------- progress --
DROP TABLE IF EXISTS t_prg;
CREATE TEMP TABLE t_prg AS
SELECT t.cle, t.code, t.valeur ->> 'module' AS module_code, t.valeur ->> 'course' AS course_code,
       clean.nombre(t.valeur ->> 'progress') AS pct, t.valeur ->> 'progress' AS progress_brut,
       (t.valeur ->> 'last_update')::TIMESTAMP AS last_update, t.ttl::INT AS ttl, t._batch_id
FROM t_cles_etudiant t WHERE t.famille = 'progress' AND t.connu;
SELECT quality.constater('RD_PROGRESSION_HORS_BORNES', 'progress', 'SELECT cle, progress_brut, NULL FROM t_prg WHERE pct NOT BETWEEN 0 AND 100');

DROP TABLE IF EXISTS clean.redis_progress CASCADE;
CREATE TABLE clean.redis_progress AS
SELECT t.code AS student_code, t.module_code, t.course_code,
       CASE WHEN t.pct BETWEEN 0 AND 100 THEN t.pct END::NUMERIC(5,2) AS progress, t.last_update, t.ttl,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_prg t LEFT JOIN quality.anomalies_par_ligne('s5_redis', 'progress') a ON a.id_ligne = t.cle;
ALTER TABLE clean.redis_progress ADD PRIMARY KEY (student_code);

-- ---------------------------------------------------------- notifications --
DROP TABLE IF EXISTS t_ntf;
CREATE TEMP TABLE t_ntf AS
SELECT t.cle, t.code, t._row_number, t._batch_id, m.message, m.rang,
       row_number() OVER (PARTITION BY t.cle, m.message ORDER BY m.rang) AS rn
FROM t_cles_etudiant t CROSS JOIN LATERAL jsonb_array_elements_text(t.valeur) WITH ORDINALITY AS m(message, rang)
WHERE t.famille = 'notifications' AND t.connu;
SELECT quality.rejeter('RD_NOTIFICATION_DOUBLON', 'notifications', $q$
    SELECT cle, _row_number, 'Notification répétée : ' || message, jsonb_build_object('cle', cle, 'rang', rang, 'message', message)
    FROM t_ntf WHERE rn > 1 $q$);

DROP TABLE IF EXISTS clean.redis_notifications CASCADE;
CREATE TABLE clean.redis_notifications AS
SELECT code AS student_code, row_number() OVER (PARTITION BY code ORDER BY rang) AS rang, message, _batch_id
FROM t_ntf WHERE rn = 1;
ALTER TABLE clean.redis_notifications ADD PRIMARY KEY (student_code, rang);

-- ------------------------------------------------------------ classement --
DROP TABLE IF EXISTS clean.redis_leaderboard CASCADE;
CREATE TABLE clean.redis_leaderboard AS
SELECT substr(s.cle, 13) AS classement, e.membre ->> 0 AS student_code, (e.membre ->> 1)::NUMERIC(6,2) AS score,
       e.rang::INT AS rang, s._batch_id
FROM staging.stg_redis_keys s CROSS JOIN LATERAL jsonb_array_elements(s.valeur) WITH ORDINALITY AS e(membre, rang)
WHERE s.cle LIKE 'leaderboard:%'
  AND EXISTS (SELECT 1 FROM clean.comptes_lms c WHERE c.student_code = e.membre ->> 0);
ALTER TABLE clean.redis_leaderboard ADD PRIMARY KEY (classement, student_code);

-- --------------------------------------------------------------- compteurs --
-- Chaque compteur est RECALCULÉ à partir des sessions nettoyées et des événements MongoDB
DROP TABLE IF EXISTS t_cpt;
CREATE TEMP TABLE t_cpt AS
WITH t AS (SELECT current_setting('edusmart.redis_snapshot')::TIMESTAMP AS snap),
online AS (SELECT session_id, student_code FROM clean.redis_sessions WHERE statut = 'ONLINE'),
derniers AS (   -- dernier événement quiz / vidéo de chaque session en ligne, avant le snapshot
    SELECT DISTINCT ON (e.session_id, left(e.event_type, 5)) e.session_id, e.event_type, e.horodatage, e.duration_seconds
    FROM clean.evenements e JOIN online o USING (session_id), t
    WHERE e.horodatage <= t.snap AND e.event_type IN ('QUIZ_STARTED', 'QUIZ_SUBMITTED', 'VIDEO_STARTED', 'VIDEO_FINISHED')
    ORDER BY e.session_id, left(e.event_type, 5), e.horodatage DESC, e.event_type),
brut AS (
    SELECT 'online_users' AS nom, valeur #>> '{}' AS valeur_source FROM staging.stg_redis_keys WHERE cle = 'online_users'
    UNION ALL
    SELECT 'statistics:today.' || k, valeur ->> k FROM staging.stg_redis_keys,
           unnest(ARRAY['active_students', 'active_teachers', 'quiz_running', 'videos_streaming']) k
    WHERE cle = 'statistics:today')
SELECT b.nom, b.valeur_source::INT AS valeur_source,
       CASE b.nom
         WHEN 'online_users' THEN (SELECT count(DISTINCT student_code) FROM online)
         WHEN 'statistics:today.active_students' THEN
              (SELECT count(DISTINCT e.student_code) FROM clean.evenements e, t
               WHERE e.horodatage::DATE = t.snap::DATE AND e.horodatage <= t.snap)
         WHEN 'statistics:today.quiz_running' THEN (SELECT count(*) FROM derniers WHERE event_type = 'QUIZ_STARTED')
         WHEN 'statistics:today.videos_streaming' THEN
              (SELECT count(*) FROM derniers, t WHERE event_type = 'VIDEO_STARTED'
               AND (duration_seconds IS NULL OR horodatage + duration_seconds * INTERVAL '1 second' > t.snap))
       END AS valeur_recalculee
FROM brut b;

SELECT quality.constater('RD_COMPTEUR', 'compteurs', 'SELECT nom, valeur_source, valeur_recalculee FROM t_cpt WHERE valeur_recalculee IS NOT NULL AND valeur_source <> valeur_recalculee');
SELECT quality.constater('RD_COMPTEUR_NON_VERIFIABLE', 'compteurs', 'SELECT nom, valeur_source, NULL FROM t_cpt WHERE valeur_recalculee IS NULL');

DROP TABLE IF EXISTS clean.redis_compteurs CASCADE;
CREATE TABLE clean.redis_compteurs AS
SELECT t.nom, t.valeur_source, COALESCE(t.valeur_recalculee, t.valeur_source) AS valeur,
       (t.valeur_recalculee IS NOT NULL) AS verifiable, COALESCE(a.codes, '{}') AS _anomalies
FROM t_cpt t LEFT JOIN quality.anomalies_par_ligne('s5_redis', 'compteurs') a ON a.id_ligne = t.nom;
ALTER TABLE clean.redis_compteurs ADD PRIMARY KEY (nom);

-- Statistiques à jour pour le planificateur (tables recréées)
ANALYZE clean.redis_sessions, clean.redis_progress;
