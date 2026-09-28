-- =============================================================================
-- Phase 10 — PIVOT (rotation) : on fait tourner les axes (lignes <-> colonnes)
-- Même donnée, autre lecture : les années passent en colonnes, pour comparer d'un coup d'œil.
-- =============================================================================

-- @titre Pivot : CA (millions XOF) par région en lignes et année académique en colonnes
SELECT r.region,
       round(SUM(p.montant_ca) FILTER (WHERE f.annee_academique = '2023-2024') / 1e6, 1) AS "2023-2024",
       round(SUM(p.montant_ca) FILTER (WHERE f.annee_academique = '2024-2025') / 1e6, 1) AS "2024-2025",
       round(SUM(p.montant_ca) FILTER (WHERE f.annee_academique = '2025-2026') / 1e6, 1) AS "2025-2026",
       round(SUM(p.montant_ca) / 1e6, 1) AS total
FROM dw.fact_paiements p JOIN dw.dim_formation f USING (formation_key) JOIN dw.dim_region r ON r.region_key = p.region_key
GROUP BY r.region ORDER BY total DESC LIMIT 10;

-- @titre Pivot pédagogique : taux de validation (%) par catégorie en lignes et niveau du module en colonnes
SELECT categorie,
       round(100 * MAX(taux_validation) FILTER (WHERE niveau = 'DEBUTANT'), 1) AS "Débutant",
       round(100 * MAX(taux_validation) FILTER (WHERE niveau = 'INTERMEDIAIRE'), 1) AS "Intermédiaire",
       round(100 * MAX(taux_validation) FILTER (WHERE niveau = 'AVANCE'), 1) AS "Avancé",
       round(100 * MAX(taux_validation) FILTER (WHERE niveau = 'TOUS'), 1) AS "Tous niveaux"
FROM dw.cube_pedagogie
WHERE annee_academique = 'TOUTES' AND categorie <> 'TOUTES'
GROUP BY categorie ORDER BY "Tous niveaux" DESC;
