-- =============================================================================
-- Chargement des FAITS (Lot L6) — rechargement complet à chaque lot (volumes modestes)
-- Chaque fait est rattaché à la VERSION de l'étudiant valable À SA DATE (SCD 2) :
--     d.etudiant_id = … AND date_du_fait BETWEEN d.date_debut AND d.date_fin
-- Toute référence introuvable pointe vers le membre -1 (jamais de NULL).
-- =============================================================================
TRUNCATE dw.fact_paiements, dw.fact_inscriptions, dw.fact_notes, dw.fact_quiz_activite, dw.fact_connexions,
         dw.fact_progression, dw.fact_salaires, dw.fact_absences;

-- student_code (MySQL, MongoDB) -> clé durable de l'étudiant
DROP TABLE IF EXISTS t_code;
CREATE TEMP TABLE t_code AS
SELECT student_code, COALESCE(id_etudiant::TEXT, 'LMS:' || student_code) AS etudiant_id FROM clean.comptes_lms;
CREATE UNIQUE INDEX ON t_code (student_code);

-- 1. Paiements
INSERT INTO dw.fact_paiements
SELECT p.id_paiement, COALESCE(t.date_key, -1), COALESCE(d.etudiant_key, -1), COALESCE(f.formation_key, -1),
       COALESCE(d.region_key, -1), p.reference, p.mode_paiement, p.statut, p.tranche, p.montant,
       CASE WHEN p.statut = 'VALIDE' AND NOT p.montant_negatif THEN COALESCE(p.montant, 0) ELSE 0 END,
       p.montant_negatif::INT, p.reference_partagee::INT
FROM clean.paiements p JOIN clean.inscriptions i USING (id_inscription)
LEFT JOIN dw.dim_temps t ON t.date_complete = p.date_paiement
LEFT JOIN dw.dim_etudiant d ON d.etudiant_id = i.id_etudiant::TEXT AND p.date_paiement BETWEEN d.date_debut AND d.date_fin
LEFT JOIN dw.dim_formation f ON f.id_classe = i.id_classe;

-- 2. Inscriptions
INSERT INTO dw.fact_inscriptions
SELECT i.id_inscription, COALESCE(t.date_key, -1), COALESCE(d.etudiant_key, -1), COALESCE(f.formation_key, -1),
       COALESCE(d.region_key, -1), i.statut, i.type_inscription, 1, COALESCE(i.bourse, FALSE)::INT,
       (i.statut = 'ABANDON')::INT, (i.statut = 'DIPLOME')::INT, ('PG_INSCRIPTION_TARDIVE' = ANY (i._anomalies))::INT,
       i.reduction, round(f.frais_annuels * (1 - COALESCE(i.reduction, 0) / 100), 2)
FROM clean.inscriptions i
LEFT JOIN dw.dim_temps t ON t.date_complete = i.date_inscription
LEFT JOIN dw.dim_etudiant d ON d.etudiant_id = i.id_etudiant::TEXT AND i.date_inscription BETWEEN d.date_debut AND d.date_fin
LEFT JOIN dw.dim_formation f ON f.id_classe = i.id_classe;

-- 3. Notes
INSERT INTO dw.fact_notes
SELECT n.id_note, COALESCE(t.date_key, -1), COALESCE(d.etudiant_key, -1), COALESCE(q.quiz_key, -1),
       COALESCE(q.module_key, -1), n.tentative, n.score, q.score_max,
       round(n.score / NULLIF(q.score_max, 0) * 20, 2), COALESCE(n.valide, FALSE)::INT, 1
FROM clean.notes n
LEFT JOIN t_code c ON c.student_code = n.student_code
LEFT JOIN dw.dim_temps t ON t.date_complete = n.date_passage::DATE
LEFT JOIN dw.dim_etudiant d ON d.etudiant_id = c.etudiant_id AND n.date_passage::DATE BETWEEN d.date_debut AND d.date_fin
LEFT JOIN dw.dim_quiz q ON q.id_quiz = n.id_quiz;

-- 4. Activité quiz (MongoDB)
INSERT INTO dw.fact_quiz_activite
SELECT e.event_id, COALESCE(t.date_key, -1), extract(HOUR FROM e.horodatage), COALESCE(d.etudiant_key, -1),
       COALESCE(q.quiz_key, -1), COALESCE(q.module_key, m.module_key, -1), COALESCE(r.region_key, -1),
       e.event_type, e.plateforme, e.app_version, e.session_id, e.duration_seconds,
       CASE WHEN jsonb_typeof(e.metadata -> 'score') = 'number' THEN (e.metadata ->> 'score')::NUMERIC END,
       CASE WHEN jsonb_typeof(e.metadata -> 'attempt') = 'number' THEN (e.metadata ->> 'attempt')::INT END,
       e.success::INT, 1
FROM clean.evenements e
LEFT JOIN t_code c ON c.student_code = e.student_code
LEFT JOIN dw.dim_temps t ON t.date_complete = e.horodatage::DATE
LEFT JOIN dw.dim_etudiant d ON d.etudiant_id = c.etudiant_id AND e.horodatage::DATE BETWEEN d.date_debut AND d.date_fin
LEFT JOIN dw.dim_quiz q ON q.id_quiz = e.id_quiz
LEFT JOIN dw.dim_module m ON m.id_module = e.id_module
LEFT JOIN dw.dim_region r ON r.ville = e.ville AND r.region = e.region
WHERE e.event_type IN ('QUIZ_STARTED', 'QUIZ_SUBMITTED');

-- 5. Connexions
INSERT INTO dw.fact_connexions
SELECT x.id_connexion, COALESCE(t.date_key, -1), extract(HOUR FROM x.date_connexion), COALESCE(d.etudiant_key, -1),
       x.appareil, x.navigateur, x.duree_secondes, 1, (x.date_deconnexion IS NULL)::INT
FROM clean.temps_connexion x
LEFT JOIN t_code c ON c.student_code = x.student_code
LEFT JOIN dw.dim_temps t ON t.date_complete = x.date_connexion::DATE
LEFT JOIN dw.dim_etudiant d ON d.etudiant_id = c.etudiant_id AND x.date_connexion::DATE BETWEEN d.date_debut AND d.date_fin;

-- 6. Progression (instantané par couple étudiant x module)
INSERT INTO dw.fact_progression
SELECT p.id_progression, COALESCE(t.date_key, -1), COALESCE(d.etudiant_key, -1), COALESCE(m.module_key, -1),
       COALESCE(c.etudiant_id, 'INCONNU:' || p.student_code), p.pourcentage, COALESCE(p.pourcentage = 100, FALSE)::INT
FROM clean.progression p
LEFT JOIN t_code c ON c.student_code = p.student_code
LEFT JOIN dw.dim_temps t ON t.date_complete = p.date_maj::DATE
LEFT JOIN dw.dim_etudiant d ON d.etudiant_id = c.etudiant_id AND p.date_maj::DATE BETWEEN d.date_debut AND d.date_fin
LEFT JOIN dw.dim_module m ON m.id_module = p.id_module;

-- 7. Salaires (enseignant x mois ; date = 1er jour du mois)
INSERT INTO dw.fact_salaires
SELECT s.id_salaire, COALESCE(t.date_key, -1), COALESCE(e.enseignant_key, -1), s.mode_paiement, s.salaire_base,
       s.primes, s.retenues, s.salaire_net
FROM clean.salaires s
LEFT JOIN dw.dim_temps t ON t.date_complete = make_date(s.annee, s.mois, 1)
LEFT JOIN dw.dim_enseignant e ON e.teacher_code = s.teacher_code;

-- 8. Absences
INSERT INTO dw.fact_absences
SELECT a.id_absence, COALESCE(t.date_key, -1), COALESCE(e.enseignant_key, -1), a.motif, a.duree_heures,
       a.justifiee::INT, a.remplace::INT, 1
FROM clean.absences a
LEFT JOIN dw.dim_temps t ON t.date_complete = a.date_absence
LEFT JOIN dw.dim_enseignant e ON e.teacher_code = a.teacher_code;

ANALYZE dw.fact_paiements, dw.fact_inscriptions, dw.fact_notes, dw.fact_quiz_activite, dw.fact_connexions,
        dw.fact_progression, dw.fact_salaires, dw.fact_absences;
