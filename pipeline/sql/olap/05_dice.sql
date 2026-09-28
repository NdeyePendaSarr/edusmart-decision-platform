-- =============================================================================
-- Phase 10 — DICE (dé) : on restreint PLUSIEURS dimensions à la fois -> un sous-cube
-- Sous-cube : 2 années x 2 régions x niveau MASTER.
-- =============================================================================

-- @titre Dice : années 2024-2025 et 2025-2026, régions Dakar et Thiès, niveau Master
SELECT f.annee_academique, r.region, SUM(p.montant_ca) AS ca, COUNT(*) AS paiements,
       round(AVG(p.montant_ca) FILTER (WHERE p.montant_ca > 0), 0) AS paiement_moyen
FROM dw.fact_paiements p
JOIN dw.dim_formation f USING (formation_key)
JOIN dw.dim_region r ON r.region_key = p.region_key
WHERE f.annee_academique IN ('2024-2025', '2025-2026') AND r.region IN ('Dakar', 'Thiès') AND f.niveau = 'MASTER'
GROUP BY f.annee_academique, r.region
ORDER BY 1, 2;
