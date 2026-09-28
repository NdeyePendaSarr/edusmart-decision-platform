-- =============================================================================
-- Chargement des DIMENSIONS (Lot L6) — incrémental : les clés de substitution sont stables
-- Paramètre : edusmart.date_effet (date d'extraction du lot) = date de début d'une nouvelle version SCD 2
-- =============================================================================

-- ------------------------------------------------------------ dim_temps (fixe) --
INSERT INTO dw.dim_temps
SELECT to_char(d, 'YYYYMMDD')::INT, d::DATE, extract(DAY FROM d), extract(ISODOW FROM d),
       (ARRAY['lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche'])[extract(ISODOW FROM d)],
       extract(ISODOW FROM d) >= 6, extract(WEEK FROM d), extract(MONTH FROM d),
       (ARRAY['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'])[extract(MONTH FROM d)],
       to_char(d, 'YYYY-MM'), extract(QUARTER FROM d), extract(YEAR FROM d),
       CASE WHEN extract(MONTH FROM d) >= 10 THEN extract(YEAR FROM d) || '-' || (extract(YEAR FROM d) + 1)
            ELSE (extract(YEAR FROM d) - 1) || '-' || extract(YEAR FROM d) END,
       (extract(MONTH FROM d)::INT + 2) % 12 + 1,
       ((extract(MONTH FROM d)::INT + 2) % 12) / 3 + 1
FROM generate_series(DATE '2023-01-01', DATE '2026-12-31', INTERVAL '1 day') AS d
ON CONFLICT (date_key) DO NOTHING;

-- ---------------------------------------------------------------- dim_region --
INSERT INTO dw.dim_region (ville, region, pays)
SELECT ville, region, 'Sénégal' FROM clean.ref_villes ORDER BY region, ville
ON CONFLICT (ville, region) DO NOTHING;

-- ------------------------------------------------ dim_formation (SCD 1) --
INSERT INTO dw.dim_formation (id_classe, code_classe, nom_classe, annee_academique, groupe, code_filiere, nom_filiere,
                              niveau, departement, duree_mois, cout_total, frais_annuels, responsable)
SELECT c.id_classe, c.code_classe, c.nom_classe, c.annee_academique, right(c.code_classe, 1), f.code_filiere, f.nom_filiere,
       f.niveau, f.departement, f.duree_mois, f.cout_total,
       round(f.cout_total / CASE f.niveau WHEN 'LICENCE' THEN 3 WHEN 'MASTER' THEN 2 ELSE 1 END, 2), c.responsable
FROM clean.classes c JOIN clean.filieres f USING (id_filiere)
ON CONFLICT (id_classe) DO UPDATE SET code_classe = EXCLUDED.code_classe, nom_classe = EXCLUDED.nom_classe,
    annee_academique = EXCLUDED.annee_academique, groupe = EXCLUDED.groupe, code_filiere = EXCLUDED.code_filiere,
    nom_filiere = EXCLUDED.nom_filiere, niveau = EXCLUDED.niveau, departement = EXCLUDED.departement,
    duree_mois = EXCLUDED.duree_mois, cout_total = EXCLUDED.cout_total, frais_annuels = EXCLUDED.frais_annuels,
    responsable = EXCLUDED.responsable;

-- --------------------------------------------------- dim_module (SCD 1) --
INSERT INTO dw.dim_module (id_module, code_module, nom_module, categorie, niveau, duree_heures, actif)
SELECT id_module, code_module, nom_module, categorie, niveau, duree_heures, actif FROM clean.modules
ON CONFLICT (id_module) DO UPDATE SET code_module = EXCLUDED.code_module, nom_module = EXCLUDED.nom_module,
    categorie = EXCLUDED.categorie, niveau = EXCLUDED.niveau, duree_heures = EXCLUDED.duree_heures, actif = EXCLUDED.actif;

-- ----------------------------------------------------- dim_quiz (SCD 1) --
INSERT INTO dw.dim_quiz (id_quiz, code_quiz, titre, nb_questions, score_max, duree_minutes, id_cours, code_cours,
                         titre_cours, type_cours, ordre_cours, module_key)
SELECT q.id_quiz, q.code_quiz, q.titre, q.nb_questions, q.score_max, q.duree_minutes, c.id_cours, c.code_cours,
       c.titre, c.type_cours, c.ordre, COALESCE(m.module_key, -1)
FROM clean.quiz q JOIN clean.cours c USING (id_cours) LEFT JOIN dw.dim_module m ON m.id_module = c.id_module
ON CONFLICT (id_quiz) DO UPDATE SET code_quiz = EXCLUDED.code_quiz, titre = EXCLUDED.titre,
    nb_questions = EXCLUDED.nb_questions, score_max = EXCLUDED.score_max, duree_minutes = EXCLUDED.duree_minutes,
    id_cours = EXCLUDED.id_cours, code_cours = EXCLUDED.code_cours, titre_cours = EXCLUDED.titre_cours,
    type_cours = EXCLUDED.type_cours, ordre_cours = EXCLUDED.ordre_cours, module_key = EXCLUDED.module_key;

-- ------------------------------------------------ dim_enseignant (SCD 1) --
INSERT INTO dw.dim_enseignant (teacher_code, nom, prenom, sexe, specialite, grade, statut, date_embauche)
SELECT teacher_code, nom, prenom, sexe, specialite, grade, statut, date_embauche FROM clean.enseignants
ON CONFLICT (teacher_code) DO UPDATE SET nom = EXCLUDED.nom, prenom = EXCLUDED.prenom, sexe = EXCLUDED.sexe,
    specialite = EXCLUDED.specialite, grade = EXCLUDED.grade, statut = EXCLUDED.statut, date_embauche = EXCLUDED.date_embauche;

-- ------------------------------------------------- dim_etudiant (SCD 2) --
-- Population : étudiants inscrits + comptes LMS sans inscription (définition validée en L3)
DROP TABLE IF EXISTS t_src_etu;
CREATE TEMP TABLE t_src_etu AS
SELECT e.id_etudiant::TEXT AS etudiant_id, e.id_etudiant, e.matricule, e.student_code, e.nom, e.prenom, e.sexe,
       e.date_naissance, CASE WHEN e.student_code IS NULL THEN 'SANS_LMS' ELSE 'APPARIE' END AS rapprochement,
       e.ville, e.region, COALESCE(r.region_key, -1) AS region_key
FROM clean.etudiants e LEFT JOIN dw.dim_region r ON r.ville = e.ville AND r.region = e.region
UNION ALL
SELECT 'LMS:' || c.student_code, NULL, NULL, c.student_code, NULL, NULL, NULL, NULL, 'LMS_SEUL', NULL, NULL, -1
FROM clean.comptes_lms c WHERE NOT c.a_inscription;
CREATE INDEX ON t_src_etu (etudiant_id);

-- (1) SCD 1 : corrections écrasées dans TOUTES les versions (une correction n'est pas une évolution)
UPDATE dw.dim_etudiant d
SET matricule = s.matricule, student_code = s.student_code, nom = s.nom, prenom = s.prenom, sexe = s.sexe,
    date_naissance = s.date_naissance, rapprochement = s.rapprochement
FROM t_src_etu s
WHERE d.etudiant_id = s.etudiant_id
  AND (d.matricule, d.student_code, d.nom, d.prenom, d.sexe, d.date_naissance, d.rapprochement)
      IS DISTINCT FROM (s.matricule, s.student_code, s.nom, s.prenom, s.sexe, s.date_naissance, s.rapprochement);

-- (2) SCD 2 : la localisation a changé -> on ferme la version courante et on en ouvre une nouvelle
DROP TABLE IF EXISTS t_chg;
CREATE TEMP TABLE t_chg AS
SELECT s.*, d.etudiant_key AS cle_courante, d.version AS version_courante, d.date_debut AS debut_courant
FROM t_src_etu s JOIN dw.dim_etudiant d ON d.etudiant_id = s.etudiant_id AND d.est_courant
WHERE (d.ville, d.region) IS DISTINCT FROM (s.ville, s.region);

--   changement le jour même où la version a commencé : simple mise à jour (pas de version d'un jour vide)
UPDATE dw.dim_etudiant d SET ville = c.ville, region = c.region, region_key = c.region_key
FROM t_chg c WHERE d.etudiant_key = c.cle_courante AND c.debut_courant >= current_setting('edusmart.date_effet')::DATE;

UPDATE dw.dim_etudiant d SET date_fin = current_setting('edusmart.date_effet')::DATE - 1, est_courant = FALSE
FROM t_chg c WHERE d.etudiant_key = c.cle_courante AND c.debut_courant < current_setting('edusmart.date_effet')::DATE;

INSERT INTO dw.dim_etudiant (etudiant_id, id_etudiant, matricule, student_code, nom, prenom, sexe, date_naissance,
                             rapprochement, ville, region, region_key, date_debut, date_fin, est_courant, version)
SELECT etudiant_id, id_etudiant, matricule, student_code, nom, prenom, sexe, date_naissance, rapprochement,
       ville, region, region_key, current_setting('edusmart.date_effet')::DATE, DATE '9999-12-31', TRUE, version_courante + 1
FROM t_chg WHERE debut_courant < current_setting('edusmart.date_effet')::DATE;

-- (3) Nouveaux étudiants : version 1, valable « depuis toujours » (l'historique antérieur est inconnu)
INSERT INTO dw.dim_etudiant (etudiant_id, id_etudiant, matricule, student_code, nom, prenom, sexe, date_naissance,
                             rapprochement, ville, region, region_key, date_debut, date_fin, est_courant, version)
SELECT s.etudiant_id, s.id_etudiant, s.matricule, s.student_code, s.nom, s.prenom, s.sexe, s.date_naissance,
       s.rapprochement, s.ville, s.region, s.region_key, DATE '1900-01-01', DATE '9999-12-31', TRUE, 1
FROM t_src_etu s WHERE NOT EXISTS (SELECT 1 FROM dw.dim_etudiant d WHERE d.etudiant_id = s.etudiant_id);

ANALYZE dw.dim_temps, dw.dim_region, dw.dim_formation, dw.dim_module, dw.dim_quiz, dw.dim_enseignant, dw.dim_etudiant;
