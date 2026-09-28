-- =============================================================================
-- Phase 10 — DRILL DOWN (forage vers le bas) : de la synthèse vers le détail
-- Parcours d'un décideur : quelle région pèse le plus ? -> dans cette région, quelles villes ?
-- -> dans la première ville, quelles filières ?
-- =============================================================================

-- @titre Drill down niveau 1 : CA par région
SELECT r.region, SUM(p.montant_ca) AS ca, COUNT(DISTINCT d.etudiant_id) AS etudiants_payeurs
FROM dw.fact_paiements p JOIN dw.dim_region r USING (region_key) JOIN dw.dim_etudiant d USING (etudiant_key)
GROUP BY r.region ORDER BY ca DESC LIMIT 8;

-- @titre Drill down niveau 2 : dans la région de Dakar, CA par ville
SELECT r.ville, SUM(p.montant_ca) AS ca, COUNT(DISTINCT d.etudiant_id) AS etudiants_payeurs
FROM dw.fact_paiements p JOIN dw.dim_region r USING (region_key) JOIN dw.dim_etudiant d USING (etudiant_key)
WHERE r.region = 'Dakar'
GROUP BY r.ville ORDER BY ca DESC;

-- @titre Drill down niveau 3 : à Dakar (ville), CA par filière
SELECT f.nom_filiere, f.niveau, SUM(p.montant_ca) AS ca
FROM dw.fact_paiements p JOIN dw.dim_region r USING (region_key) JOIN dw.dim_formation f USING (formation_key)
WHERE r.ville = 'Dakar'
GROUP BY f.nom_filiere, f.niveau ORDER BY ca DESC LIMIT 10;
