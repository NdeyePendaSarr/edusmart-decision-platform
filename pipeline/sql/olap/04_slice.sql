-- =============================================================================
-- Phase 10 — SLICE (tranche) : on FIXE UNE dimension à une valeur
-- Tranche du cube « année académique = 2024-2025 » : une année, toutes les filières.
-- =============================================================================

-- @titre Slice : l'année académique 2024-2025, recouvrement et abandon par filière
SELECT f.nom_filiere, f.niveau,
       SUM(i.nb_inscriptions) AS inscriptions,
       round(100.0 * SUM(i.est_abandon) / SUM(i.nb_inscriptions), 2) AS taux_abandon_pct,
       COALESCE(ca.ca, 0) AS ca,
       round(100 * COALESCE(ca.ca, 0) / NULLIF(SUM(i.montant_du), 0), 2) AS recouvrement_pct
FROM dw.fact_inscriptions i JOIN dw.dim_formation f USING (formation_key)
LEFT JOIN (SELECT f2.code_filiere, SUM(p.montant_ca) AS ca FROM dw.fact_paiements p
           JOIN dw.dim_formation f2 USING (formation_key) WHERE f2.annee_academique = '2024-2025' GROUP BY 1) ca
       ON ca.code_filiere = f.code_filiere
WHERE f.annee_academique = '2024-2025'
GROUP BY f.nom_filiere, f.niveau, ca.ca
ORDER BY taux_abandon_pct DESC LIMIT 10;
