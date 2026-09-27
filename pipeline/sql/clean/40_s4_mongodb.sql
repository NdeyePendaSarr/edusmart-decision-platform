-- =============================================================================
-- Couche CLEAN — Source 4 MongoDB (Lot L5)
-- staging.stg_mongo_events (document JSONB complet) -> clean.evenements (une colonne par champ)
-- Le schéma flexible est respecté : un champ de contexte absent (LOGIN sans quiz_code)
-- n'est PAS une anomalie. Seuls les 13 champs standard sont contrôlés.
-- =============================================================================
SELECT quality.reinitialiser('s4_mongodb');

DROP TABLE IF EXISTS t_evt;
CREATE TEMP TABLE t_evt AS
SELECT s._row_number, s.event_id, s._batch_id, s.document AS d,
       row_number() OVER (PARTITION BY s.event_id ORDER BY s._row_number) AS rn,
       -- champs standard absents (student_code exclu : il a sa propre règle)
       ( (NOT s.document ? 'event_id')::INT + (NOT s.document ? 'timestamp')::INT + (NOT s.document ? 'event_type')::INT
       + (NOT s.document ? 'device')::INT + (NOT s.document ? 'operating_system')::INT + (NOT s.document ? 'app_version')::INT
       + (NOT s.document ? 'ip_address')::INT + (NOT s.document ? 'city')::INT + (NOT s.document ? 'country')::INT
       + (NOT s.document ? 'session_id')::INT + (NOT s.document ? 'duration_seconds')::INT + (NOT s.document ? 'success')::INT
       + (NOT s.document ? 'metadata')::INT ) AS nb_absents,
       ( SELECT count(*) FROM unnest(ARRAY['event_id','timestamp','event_type','device','operating_system','app_version',
                                           'ip_address','city','country','session_id','duration_seconds','success','metadata']) k
         WHERE jsonb_typeof(s.document -> k) = 'null' ) AS nb_nuls,
       jsonb_typeof(s.document -> 'timestamp') AS type_ts,
       clean.horodatage_json(s.document -> 'timestamp') AS ts,
       s.document ->> 'student_code' AS code,
       s.document ->> 'session_id' AS session_id,
       s.document ->> 'city' AS city, clean.cle(s.document ->> 'city') AS city_k,
       s.document ->> 'app_version' AS app_version, clean.version(s.document ->> 'app_version') AS version_c,
       s.document ->> 'operating_system' AS os,
       s.document ->> 'ip_address' AS ip,
       CASE WHEN jsonb_typeof(s.document -> 'duration_seconds') = 'number'
            THEN (s.document ->> 'duration_seconds')::INT END AS duree
FROM staging.stg_mongo_events s;

-- Référentiels (jointures plutôt que fonctions ligne à ligne : 300 000 documents)
DROP TABLE IF EXISTS t_evt2;
CREATE TEMP TABLE t_evt2 AS
SELECT t.*, COALESCE(v1.ville, v2.ville) AS ville_c, COALESCE(v1.region, v2.region) AS region_c, o.valeur AS os_c,
       sess.code_session
FROM t_evt t
LEFT JOIN clean.ref_villes v1 ON v1.cle = t.city_k
LEFT JOIN clean.ref_villes v2 ON v1.cle IS NULL AND t.city_k ~ '(.)\1$' AND v2.cle = left(t.city_k, -1)
LEFT JOIN clean.ref_synonymes o ON o.domaine = 'os' AND o.cle = clean.cle(t.os)
LEFT JOIN (SELECT session_id, min(code) AS code_session FROM t_evt WHERE code IS NOT NULL GROUP BY session_id) sess
       ON sess.session_id = t.session_id
WHERE t.rn = 1;

SELECT quality.rejeter('MG_DOUBLON', 'events', $q$
    SELECT t.event_id, t._row_number, 'Événement déjà journalisé', t.d FROM t_evt t WHERE t.rn > 1 $q$);
SELECT quality.constater('MG_DOCUMENT_INCOMPLET', 'events', 'SELECT event_id, nb_absents || '' champs absents'', NULL FROM t_evt2 WHERE nb_absents >= 5');
SELECT quality.constater('MG_CHAMP_ABSENT', 'events', 'SELECT event_id, ''1 champ absent'', NULL FROM t_evt2 WHERE nb_absents = 1');
SELECT quality.constater('MG_VALEUR_NULLE', 'events', 'SELECT event_id, nb_nuls || '' valeur(s) nulle(s)'', NULL FROM t_evt2 WHERE nb_nuls > 0');
SELECT quality.constater('MG_VILLE', 'events', 'SELECT event_id, city, ville_c FROM t_evt2 WHERE ville_c IS NOT NULL AND city <> ville_c');
SELECT quality.constater('MG_VILLE_INCONNUE', 'events', 'SELECT event_id, city, NULL FROM t_evt2 WHERE city IS NOT NULL AND ville_c IS NULL');
SELECT quality.constater('MG_VERSION', 'events', 'SELECT event_id, app_version, version_c FROM t_evt2 WHERE version_c IS NOT NULL AND app_version <> version_c');
SELECT quality.constater('MG_VERSION_INVALIDE', 'events', 'SELECT event_id, app_version, NULL FROM t_evt2 WHERE app_version IS NOT NULL AND version_c IS NULL');
SELECT quality.constater('MG_OS', 'events', 'SELECT event_id, os, os_c FROM t_evt2 WHERE os_c IS NOT NULL AND os <> os_c');
SELECT quality.constater('MG_ETUDIANT_RECUPERE', 'events', 'SELECT event_id, NULL, code_session FROM t_evt2 WHERE code IS NULL AND code_session IS NOT NULL');
SELECT quality.constater('MG_SANS_ETUDIANT', 'events', 'SELECT event_id, NULL, NULL FROM t_evt2 WHERE code IS NULL AND code_session IS NULL');
SELECT quality.constater('MG_HORODATAGE', 'events', 'SELECT event_id, d->>''timestamp'', ts FROM t_evt2 WHERE type_ts <> ''object'' AND ts IS NOT NULL');
SELECT quality.constater('MG_HORODATAGE_INVALIDE', 'events', 'SELECT event_id, d->>''timestamp'', NULL FROM t_evt2 WHERE type_ts IS NOT NULL AND type_ts <> ''null'' AND ts IS NULL');
SELECT quality.constater('MG_IP_INVALIDE', 'events', 'SELECT event_id, ip, NULL FROM t_evt2 WHERE ip IS NOT NULL AND NOT clean.ip_valide(ip)');
SELECT quality.constater('MG_DUREE_NEGATIVE', 'events', 'SELECT event_id, duree, NULL FROM t_evt2 WHERE duree < 0');
SELECT quality.constater('MG_CONTENU_HORS_MAPPING', 'events', $q$
    SELECT t.event_id, COALESCE(t.d->>'quiz_code', t.d->>'course_code'), NULL FROM t_evt2 t
    WHERE (t.d ? 'course_code' AND NOT EXISTS (SELECT 1 FROM clean.ref_mapping_contenus m WHERE m.code_externe = t.d->>'course_code'))
       OR (t.d ? 'quiz_code'   AND NOT EXISTS (SELECT 1 FROM clean.ref_mapping_contenus m WHERE m.code_externe = t.d->>'quiz_code')) $q$);

DROP TABLE IF EXISTS clean.evenements CASCADE;
CREATE TABLE clean.evenements AS
SELECT t.event_id, COALESCE(t.code, t.code_session) AS student_code, t.ts AS horodatage, t.d->>'event_type' AS event_type,
       t.d->>'module_code' AS module_code, t.d->>'course_code' AS course_code, t.d->>'quiz_code' AS quiz_code,
       mm.id_mysql::UUID AS id_module, mc.id_mysql::UUID AS id_cours, mq.id_mysql::UUID AS id_quiz,
       t.d->>'device' AS modele_appareil, COALESCE(t.os_c, t.os) AS plateforme, t.version_c AS app_version,
       CASE WHEN clean.ip_valide(t.ip) THEN t.ip END AS ip_address,
       COALESCE(t.ville_c, t.city) AS ville, t.region_c AS region, t.d->>'country' AS pays, t.session_id,
       CASE WHEN t.duree >= 0 THEN t.duree END AS duration_seconds,
       CASE WHEN jsonb_typeof(t.d->'success') = 'boolean' THEN (t.d->>'success')::BOOLEAN END AS success,
       CASE WHEN jsonb_typeof(t.d->'metadata') = 'object' THEN t.d->'metadata' END AS metadata,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_evt2 t
LEFT JOIN clean.ref_mapping_contenus mm ON mm.code_externe = t.d->>'module_code'
LEFT JOIN clean.ref_mapping_contenus mc ON mc.code_externe = t.d->>'course_code'
LEFT JOIN clean.ref_mapping_contenus mq ON mq.code_externe = t.d->>'quiz_code'
LEFT JOIN quality.anomalies_par_ligne('s4_mongodb', 'events') a ON a.id_ligne = t.event_id;
ALTER TABLE clean.evenements ADD PRIMARY KEY (event_id);
CREATE INDEX idx_clean_evt_session ON clean.evenements (session_id);
CREATE INDEX idx_clean_evt_student ON clean.evenements (student_code, horodatage);

-- Statistiques à jour pour le planificateur (tables recréées)
ANALYZE clean.evenements;
