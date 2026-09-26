-- =============================================================================
-- EduSmart — Source 2 : MySQL « Plateforme pédagogique »
-- Fichier : check_constraints.sql  (diagnostic en lecture seule, Phase 15)
-- Exécution : Adminer (onglet Requête SQL) ou
--   Get-Content sources\s2_mysql\check_constraints.sql | docker exec -i edusmart_mysql mysql -uedusmart -p edusmart_learning
-- =============================================================================

-- Partie 1 — Contraintes CHECK : actives (ENFORCED = YES) ou non
SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME, cc.CHECK_CLAUSE, tc.ENFORCED
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.CHECK_CONSTRAINTS cc
  ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
WHERE tc.CONSTRAINT_SCHEMA = DATABASE() AND tc.CONSTRAINT_TYPE = 'CHECK'
ORDER BY tc.ENFORCED, tc.TABLE_NAME, tc.CONSTRAINT_NAME;

-- Partie 2 — Clés étrangères déclarées
SELECT TABLE_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME
FROM information_schema.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = DATABASE()
ORDER BY TABLE_NAME;

-- Partie 3 — Violations par règle du PDF
SELECT 'quiz.duree_minutes <= 0'                      AS regle, COUNT(*) AS violations FROM quiz WHERE duree_minutes <= 0
UNION ALL
SELECT 'progression.pourcentage > 100',                COUNT(*) FROM progression WHERE pourcentage > 100
UNION ALL
SELECT 'progression.pourcentage < 0',                  COUNT(*) FROM progression WHERE pourcentage < 0
UNION ALL
SELECT 'progression -> module inexistant',             COUNT(*) FROM progression p
       WHERE NOT EXISTS (SELECT 1 FROM modules m WHERE m.id_module = p.id_module)
UNION ALL
SELECT 'progression : doublons (étudiant, module)',    COUNT(*) - COUNT(DISTINCT student_code, id_module) FROM progression
UNION ALL
SELECT 'temps_connexion.duree_minutes < 0',            COUNT(*) FROM temps_connexion WHERE duree_minutes < 0
UNION ALL
SELECT 'temps_connexion sans déconnexion',             COUNT(*) FROM temps_connexion WHERE date_deconnexion IS NULL
UNION ALL
SELECT 'notes.score > quiz.score_max',                 COUNT(*) FROM notes n JOIN quiz q ON q.id_quiz = n.id_quiz
       WHERE n.score > q.score_max
UNION ALL
SELECT 'notes.student_code hors format LMS-XXXXXX',    COUNT(*) FROM notes
       WHERE NOT REGEXP_LIKE(student_code, '^LMS-[0-9]{6}$', 'c')   -- 'c' : sensible à la casse
UNION ALL
SELECT 'notes.score < 0 (CHECK actif : attendu 0)',    COUNT(*) FROM notes WHERE score < 0;

-- Partie 4 — Répartition des catégories (écritures variables B01)
-- PIÈGE : la collation utf8mb4_unicode_ci ignore la casse et les accents.
-- Un simple « GROUP BY categorie » fusionnerait 'Data', 'DATA' et 'data'
-- et MASQUERAIT l'anomalie. COLLATE utf8mb4_bin force une comparaison exacte.
SELECT categorie COLLATE utf8mb4_bin AS categorie_exacte, COUNT(*) AS modules
FROM modules
GROUP BY categorie COLLATE utf8mb4_bin
ORDER BY modules DESC;
