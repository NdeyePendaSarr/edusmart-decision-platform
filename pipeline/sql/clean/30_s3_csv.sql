-- =============================================================================
-- Couche CLEAN — Source 3 CSV RH (Lot L5)
-- staging.stg_csv_* -> clean.enseignants, departements, salaires, absences
-- Particularités : champ vide = chaîne vide en staging (décision L4) ; les doublons
-- sont des lignes STRICTEMENT identiques (même identifiant) : on garde la première
-- (_row_number) et on rejette les suivantes. Les constats portent sur les lignes conservées.
-- =============================================================================
SELECT quality.reinitialiser('s3_csv');

-- -------------------------------------------------------------- enseignants --
DROP TABLE IF EXISTS t_ens;
CREATE TEMP TABLE t_ens AS
SELECT s.*, clean.telephone(s.telephone) AS tel_c, clean.synonyme('specialite', s.specialite) AS specialite_c,
       CASE WHEN clean.vide(s.grade) IS NOT NULL THEN clean.synonyme('grade', s.grade) END AS grade_c,
       clean.date_multi(s.date_naissance) AS naissance_d, clean.date_multi(s.date_embauche) AS embauche_d,
       row_number() OVER (PARTITION BY s.teacher_code, s.nom, s.prenom, s.sexe, s.date_naissance, s.telephone, s.email,
                                       s.specialite, s.grade, s.date_embauche, s.statut ORDER BY s._row_number) AS rn
FROM staging.stg_csv_enseignants s;

SELECT quality.rejeter('CSV_ENSEIGNANT_DOUBLON', 'enseignants', $q$
    SELECT t.teacher_code, t._row_number, 'Ligne identique à une ligne précédente', to_jsonb(s)
    FROM t_ens t JOIN staging.stg_csv_enseignants s USING (_row_number) WHERE t.rn > 1 $q$);
DROP TABLE IF EXISTS t_ens1;
CREATE TEMP TABLE t_ens1 AS SELECT * FROM t_ens WHERE rn = 1;
SELECT quality.constater('CSV_TELEPHONE', 'enseignants', 'SELECT teacher_code, telephone, tel_c FROM t_ens1 WHERE tel_c IS NOT NULL AND telephone <> tel_c');
SELECT quality.constater('CSV_TELEPHONE_INVALIDE', 'enseignants', 'SELECT teacher_code, telephone, NULL FROM t_ens1 WHERE clean.vide(telephone) IS NOT NULL AND tel_c IS NULL');
SELECT quality.constater('CSV_EMAIL_MANQUANT', 'enseignants', 'SELECT teacher_code, NULL, NULL FROM t_ens1 WHERE clean.vide(email) IS NULL');
SELECT quality.constater('CSV_SPECIALITE', 'enseignants', 'SELECT teacher_code, specialite, specialite_c FROM t_ens1 WHERE specialite_c IS NOT NULL AND specialite <> specialite_c');
SELECT quality.constater('CSV_SPECIALITE_INCONNUE', 'enseignants', 'SELECT teacher_code, specialite, NULL FROM t_ens1 WHERE specialite_c IS NULL');
SELECT quality.constater('CSV_GRADE', 'enseignants', 'SELECT teacher_code, grade, grade_c FROM t_ens1 WHERE grade_c IS NOT NULL AND grade <> grade_c');
SELECT quality.constater('CSV_GRADE_INCONNU', 'enseignants', 'SELECT teacher_code, grade, NULL FROM t_ens1 WHERE clean.vide(grade) IS NOT NULL AND grade_c IS NULL');
SELECT quality.constater('CSV_DATE_NAISSANCE', 'enseignants', 'SELECT teacher_code, date_naissance, naissance_d FROM t_ens1 WHERE NOT clean.date_iso(date_naissance) AND naissance_d IS NOT NULL');
SELECT quality.constater('CSV_DATE_EMBAUCHE', 'enseignants', 'SELECT teacher_code, date_embauche, embauche_d FROM t_ens1 WHERE NOT clean.date_iso(date_embauche) AND embauche_d IS NOT NULL');

DROP TABLE IF EXISTS clean.enseignants CASCADE;
CREATE TABLE clean.enseignants AS
SELECT t.teacher_code, t.nom, t.prenom, clean.vide(t.sexe) AS sexe, t.naissance_d AS date_naissance, t.tel_c AS telephone,
       clean.vide(t.email) AS email, COALESCE(t.specialite_c, t.specialite) AS specialite, t.grade_c AS grade,
       t.embauche_d AS date_embauche, t.statut, COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_ens1 t LEFT JOIN quality.anomalies_par_ligne('s3_csv', 'enseignants') a ON a.id_ligne = t.teacher_code;
ALTER TABLE clean.enseignants ADD PRIMARY KEY (teacher_code);

-- ------------------------------------------------------------- departements --
DROP TABLE IF EXISTS t_dep;
CREATE TEMP TABLE t_dep AS
SELECT s.*, clean.synonyme('departement', s.nom_departement) AS nom_c FROM staging.stg_csv_departements s;

SELECT quality.rejeter('CSV_DEPARTEMENT_VARIANTE', 'departements', $q$
    SELECT t.id_departement, t._row_number, 'Fusionné dans le département ' || c.id_departement || ' (' || t.nom_c || ')', to_jsonb(s)
    FROM t_dep t JOIN staging.stg_csv_departements s USING (_row_number)
    JOIN t_dep c ON c.nom_departement = t.nom_c WHERE t.nom_departement <> t.nom_c $q$);
SELECT quality.constater('CSV_BUDGET_MANQUANT', 'departements', 'SELECT id_departement, NULL, NULL FROM t_dep WHERE clean.vide(budget_annuel) IS NULL');

DROP TABLE IF EXISTS clean.departements CASCADE;
CREATE TABLE clean.departements AS
SELECT t.id_departement::INT AS id_departement, t.nom_departement, clean.vide(t.responsable) AS responsable,
       clean.nombre(t.budget_annuel)::NUMERIC(12,2) AS budget_annuel, clean.vide(t.batiment) AS batiment,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_dep t LEFT JOIN quality.anomalies_par_ligne('s3_csv', 'departements') a ON a.id_ligne = t.id_departement
WHERE NOT EXISTS (SELECT 1 FROM quality.rejets r WHERE r.batch_id = current_setting('edusmart.batch_id')
                  AND r.code_source = 's3_csv' AND r.table_source = 'departements' AND r.rang = t._row_number);
ALTER TABLE clean.departements ADD PRIMARY KEY (id_departement);

-- ----------------------------------------------------------------- salaires --
DROP TABLE IF EXISTS t_sal;
CREATE TEMP TABLE t_sal AS
SELECT s.*, clean.mois(s.mois) AS mois_n, clean.synonyme('mode_paiement', s.mode_paiement) AS mode_c,
       clean.nombre(s.salaire_base) AS base_n, clean.nombre(s.primes) AS primes_n, clean.nombre(s.retenues) AS retenues_n,
       clean.nombre(s.salaire_net) AS net_n,
       row_number() OVER (PARTITION BY s.id_salaire, s.teacher_code, s.mois, s.annee, s.salaire_base, s.primes, s.retenues,
                                       s.salaire_net, s.mode_paiement ORDER BY s._row_number) AS rn
FROM staging.stg_csv_salaires s;

SELECT quality.rejeter('CSV_SALAIRE_DOUBLON', 'salaires', $q$
    SELECT t.id_salaire, t._row_number, 'Ligne identique à une ligne précédente', to_jsonb(s)
    FROM t_sal t JOIN staging.stg_csv_salaires s USING (_row_number) WHERE t.rn > 1 $q$);
DROP TABLE IF EXISTS t_sal1;
CREATE TEMP TABLE t_sal1 AS
SELECT *, (ARRAY['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'])[mois_n] AS mois_c
FROM t_sal WHERE rn = 1;
SELECT quality.constater('CSV_PRIMES_INCOHERENTES', 'salaires', 'SELECT id_salaire, primes, NULL FROM t_sal1 WHERE primes_n > base_n');
SELECT quality.constater('CSV_SALAIRE_NEGATIF', 'salaires', $q$
    SELECT id_salaire, salaire_net, base_n + primes_n - retenues_n FROM t_sal1
    WHERE net_n < 0 AND primes_n <= base_n AND base_n + primes_n - retenues_n >= 0 $q$);
SELECT quality.constater('CSV_MODE_PAIEMENT', 'salaires', 'SELECT id_salaire, mode_paiement, mode_c FROM t_sal1 WHERE mode_c IS NOT NULL AND mode_paiement <> mode_c');
SELECT quality.constater('CSV_MOIS', 'salaires', 'SELECT id_salaire, mois, mois_c FROM t_sal1 WHERE mois_c IS NOT NULL AND mois <> mois_c');

DROP TABLE IF EXISTS clean.salaires CASCADE;
CREATE TABLE clean.salaires AS
SELECT t.id_salaire::INT AS id_salaire, t.teacher_code, t.annee::INT AS annee, t.mois_n AS mois, t.mois_c AS mois_libelle,
       t.base_n::NUMERIC(12,2) AS salaire_base,
       CASE WHEN t.primes_n <= t.base_n THEN t.primes_n END::NUMERIC(12,2) AS primes,
       t.retenues_n::NUMERIC(12,2) AS retenues,
       CASE WHEN t.net_n < 0 AND t.primes_n <= t.base_n THEN t.base_n + t.primes_n - t.retenues_n ELSE t.net_n END::NUMERIC(12,2) AS salaire_net,
       COALESCE(t.mode_c, clean.vide(t.mode_paiement)) AS mode_paiement,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_sal1 t LEFT JOIN quality.anomalies_par_ligne('s3_csv', 'salaires') a ON a.id_ligne = t.id_salaire;
ALTER TABLE clean.salaires ADD PRIMARY KEY (id_salaire);

-- ----------------------------------------------------------------- absences --
DROP TABLE IF EXISTS t_abs;
CREATE TEMP TABLE t_abs AS
SELECT s.*, clean.date_multi(s.date_absence) AS date_d, e.date_embauche,
       row_number() OVER (PARTITION BY s.id_absence, s.teacher_code, s.date_absence, s.motif, s.justifiee, s.duree_heures,
                                       s.remplace ORDER BY s._row_number) AS rn
FROM staging.stg_csv_absences s LEFT JOIN clean.enseignants e ON e.teacher_code = s.teacher_code;

SELECT quality.rejeter('CSV_ABSENCE_DOUBLON', 'absences', $q$
    SELECT t.id_absence, t._row_number, 'Ligne identique à une ligne précédente', to_jsonb(s)
    FROM t_abs t JOIN staging.stg_csv_absences s USING (_row_number) WHERE t.rn > 1 $q$);
SELECT quality.rejeter('CSV_DATE_ABSENCE_INCOHERENTE', 'absences', $q$
    SELECT t.id_absence, t._row_number,
           CASE WHEN t.date_d > current_setting('edusmart.date_reference')::DATE THEN 'Date future : ' ELSE 'Avant l''embauche : ' END || t.date_absence,
           to_jsonb(s)
    FROM t_abs t JOIN staging.stg_csv_absences s USING (_row_number)
    WHERE t.rn = 1 AND (t.date_d > current_setting('edusmart.date_reference')::DATE OR t.date_d < t.date_embauche) $q$);
DROP TABLE IF EXISTS t_abs1;
CREATE TEMP TABLE t_abs1 AS SELECT * FROM t_abs WHERE rn = 1;
SELECT quality.constater('CSV_DATE_ABSENCE', 'absences', 'SELECT id_absence, date_absence, date_d FROM t_abs1 WHERE NOT clean.date_iso(date_absence) AND date_d IS NOT NULL');
SELECT quality.constater('CSV_MOTIF_MANQUANT', 'absences', 'SELECT id_absence, NULL, NULL FROM t_abs1 WHERE clean.vide(motif) IS NULL');
SELECT quality.constater('CSV_DUREE_ABSENCE', 'absences', 'SELECT id_absence, duree_heures, NULL FROM t_abs1 WHERE clean.nombre(duree_heures) > 24');

DROP TABLE IF EXISTS clean.absences CASCADE;
CREATE TABLE clean.absences AS
SELECT t.id_absence::INT AS id_absence, t.teacher_code, t.date_d AS date_absence, clean.vide(t.motif) AS motif,
       clean.booleen(t.justifiee) AS justifiee,
       CASE WHEN clean.nombre(t.duree_heures) <= 24 THEN clean.nombre(t.duree_heures)::INT END AS duree_heures,
       clean.booleen(t.remplace) AS remplace, COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_abs1 t LEFT JOIN quality.anomalies_par_ligne('s3_csv', 'absences') a ON a.id_ligne = t.id_absence
WHERE NOT EXISTS (SELECT 1 FROM quality.rejets r WHERE r.batch_id = current_setting('edusmart.batch_id')
                  AND r.code_source = 's3_csv' AND r.table_source = 'absences' AND r.rang = t._row_number);
ALTER TABLE clean.absences ADD PRIMARY KEY (id_absence);

-- Statistiques à jour pour le planificateur (tables recréées)
ANALYZE clean.enseignants, clean.departements, clean.salaires, clean.absences;
