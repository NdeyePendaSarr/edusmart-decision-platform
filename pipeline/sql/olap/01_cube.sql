-- =============================================================================
-- Phase 10 — Le CUBE OLAP EduSmart (Lot L7)
-- Un cube = une mesure agrégée pour TOUTES les combinaisons de ses axes, totaux compris.
-- GROUP BY CUBE(a, b, c) calcule les 2^3 = 8 regroupements en une seule requête.
-- Les cubes sont matérialisés dans le DW (dw.cube_*) : les analyses les lisent sans recalcul.
-- =============================================================================

-- @titre Cube financier : CA par année académique x région x niveau (8 regroupements)
DROP TABLE IF EXISTS dw.cube_finance;
CREATE TABLE dw.cube_finance AS
SELECT COALESCE(f.annee_academique, 'TOUTES') AS annee_academique,
       COALESCE(r.region, 'TOUTES') AS region,
       COALESCE(f.niveau, 'TOUS') AS niveau,
       SUM(p.montant_ca) AS ca, COUNT(*) AS nb_paiements,
       GROUPING(f.annee_academique, r.region, f.niveau) AS niveau_agregation   -- 0 = cellule détaillée, 7 = total général
FROM dw.fact_paiements p
JOIN dw.dim_formation f USING (formation_key)
JOIN dw.dim_region r ON r.region_key = p.region_key
GROUP BY CUBE (f.annee_academique, r.region, f.niveau);

-- @titre Cube pédagogique : taux de validation des tentatives par catégorie x niveau x année
DROP TABLE IF EXISTS dw.cube_pedagogie;
CREATE TABLE dw.cube_pedagogie AS
SELECT COALESCE(m.categorie, 'TOUTES') AS categorie, COALESCE(m.niveau, 'TOUS') AS niveau,
       COALESCE(t.annee_academique, 'TOUTES') AS annee_academique,
       COUNT(*) AS tentatives, SUM(n.est_valide) AS validations,
       round(SUM(n.est_valide)::NUMERIC / COUNT(*), 4) AS taux_validation,
       round(AVG(n.score_sur_20), 2) AS score_moyen_sur_20,
       GROUPING(m.categorie, m.niveau, t.annee_academique) AS niveau_agregation
FROM dw.fact_notes n
JOIN dw.dim_module m USING (module_key)
JOIN dw.dim_temps t USING (date_key)
GROUP BY CUBE (m.categorie, m.niveau, t.annee_academique);

-- @titre Aperçu du cube financier : les totaux (une ou plusieurs dimensions agrégées)
SELECT annee_academique, region, niveau, ca, nb_paiements, niveau_agregation
FROM dw.cube_finance WHERE niveau_agregation IN (3, 5, 6, 7)
ORDER BY niveau_agregation DESC, ca DESC LIMIT 12;
