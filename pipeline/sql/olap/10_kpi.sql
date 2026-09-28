-- =============================================================================
-- EduSmart — KPI calculés sur le Data Warehouse (Phase 11, Lot L7)
-- -----------------------------------------------------------------------------
-- dw.v_kpi        : les 8 KPI, une ligne chacun (valeurs de RÉFÉRENCE pour Power BI, G5b)
-- dw.v_kpi_annee  : KPI financiers et d'abandon par année académique de la formation
-- Date de référence : 15/09/2026 (convention C20) ; fenêtre « actifs » : 30 jours inclus.
-- Définitions : docs/11_kpi.md (fiches). Recalcul indépendant en Python : pipeline/kpi.py (G5a).
-- =============================================================================

CREATE OR REPLACE VIEW dw.v_kpi AS
WITH p AS (SELECT DATE '2026-09-15' AS reference),
-- 1. CA encaissé : paiements VALIDE rattachés, montants négatifs exclus (définition L3)
ca AS (SELECT SUM(montant_ca) AS v FROM dw.fact_paiements),
-- 2. Recouvrement : CA / montant dû (frais annuels de la classe après réduction)
recouvrement AS (SELECT (SELECT SUM(montant_ca) FROM dw.fact_paiements)
                        / NULLIF((SELECT SUM(montant_du) FROM dw.fact_inscriptions), 0) AS v),
-- 3. Réussite : couples (étudiant durable, quiz) validés au moins une fois / couples tentés (définition L3)
reussite AS (SELECT AVG(valide) AS v FROM (
                 SELECT d.etudiant_id, f.quiz_key, MAX(f.est_valide)::NUMERIC AS valide
                 FROM dw.fact_notes f JOIN dw.dim_etudiant d USING (etudiant_key) GROUP BY 1, 2) x),
-- 4. Abandon : inscriptions au statut ABANDON / inscriptions
abandon AS (SELECT SUM(est_abandon)::NUMERIC / NULLIF(COUNT(*), 0) AS v FROM dw.fact_inscriptions),
-- 5. Progression moyenne : moyenne des pourcentages CONNUS (les valeurs neutralisées en L5 sont ignorées)
progression AS (SELECT AVG(pourcentage) AS v FROM dw.fact_progression),
-- 6. Étudiants actifs : au moins une connexion, une note ou une activité de quiz dans les 30 jours (définition L3)
actifs AS (SELECT COUNT(DISTINCT d.etudiant_id) AS v
           FROM (SELECT etudiant_key, date_key FROM dw.fact_connexions
                 UNION ALL SELECT etudiant_key, date_key FROM dw.fact_notes
                 UNION ALL SELECT etudiant_key, date_key FROM dw.fact_quiz_activite) a
           JOIN dw.dim_temps t USING (date_key) JOIN dw.dim_etudiant d USING (etudiant_key), p
           WHERE t.date_complete BETWEEN p.reference - 29 AND p.reference AND d.etudiant_key <> -1),
-- 7. Temps médian de connexion, en secondes (définition L3 : médiane, source MySQL)
mediane AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY duree_secondes) AS v
            FROM dw.fact_connexions WHERE duree_secondes IS NOT NULL),
-- 8. Nombre réel d'étudiants : personnes distinctes (inscrits + comptes LMS seuls), définition L3
etudiants AS (SELECT COUNT(DISTINCT etudiant_id) AS v FROM dw.dim_etudiant WHERE est_courant AND etudiant_key <> -1)
SELECT 1 AS ordre, 'CA' AS code, 'Chiffre d''affaires encaissé' AS libelle, (SELECT v FROM ca)::NUMERIC AS valeur, 'XOF' AS unite
UNION ALL SELECT 2, 'RECOUVREMENT', 'Taux de recouvrement', (SELECT v FROM recouvrement), 'ratio'
UNION ALL SELECT 3, 'REUSSITE', 'Taux de réussite aux quiz', (SELECT v FROM reussite), 'ratio'
UNION ALL SELECT 4, 'ABANDON', 'Taux d''abandon', (SELECT v FROM abandon), 'ratio'
UNION ALL SELECT 5, 'PROGRESSION', 'Progression moyenne', (SELECT v FROM progression), '%'
UNION ALL SELECT 6, 'ACTIFS_30J', 'Étudiants actifs (30 jours)', (SELECT v FROM actifs), 'étudiants'
UNION ALL SELECT 7, 'CONNEXION_MEDIANE', 'Temps médian de connexion', (SELECT v FROM mediane)::NUMERIC, 'secondes'
UNION ALL SELECT 8, 'ETUDIANTS', 'Nombre réel d''étudiants', (SELECT v FROM etudiants), 'étudiants';

-- Par année académique DE LA FORMATION (et non de la date de paiement : les acomptes de juin à
-- septembre financent l'année qui commence en octobre)
CREATE OR REPLACE VIEW dw.v_kpi_annee AS
WITH ca AS (SELECT f.annee_academique, SUM(p.montant_ca) AS ca
            FROM dw.fact_paiements p JOIN dw.dim_formation f USING (formation_key) GROUP BY 1),
ins AS (SELECT f.annee_academique, COUNT(*) AS inscriptions, SUM(i.est_abandon) AS abandons, SUM(i.montant_du) AS montant_du
        FROM dw.fact_inscriptions i JOIN dw.dim_formation f USING (formation_key) GROUP BY 1)
SELECT ins.annee_academique, COALESCE(ca.ca, 0) AS ca, ins.montant_du,
       round(COALESCE(ca.ca, 0) / NULLIF(ins.montant_du, 0), 4) AS taux_recouvrement,
       ins.inscriptions, ins.abandons, round(ins.abandons::NUMERIC / NULLIF(ins.inscriptions, 0), 4) AS taux_abandon
FROM ins LEFT JOIN ca USING (annee_academique)
ORDER BY 1;
