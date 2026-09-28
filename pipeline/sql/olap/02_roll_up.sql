-- =============================================================================
-- Phase 10 — ROLL UP (forage vers le haut) : du détail vers la synthèse
-- On REMONTE la hiérarchie de dim_temps : mois > trimestre > année.
-- GROUP BY ROLLUP(a, b, c) produit (a,b,c), (a,b), (a) et le total général.
-- Règle : une hiérarchie se parcourt sur UNE dimension. Croiser l'année de la FORMATION avec
-- le trimestre de la date de PAIEMENT mélangerait deux axes : les acomptes de juillet à septembre
-- (avant la rentrée) apparaîtraient à la FIN d'une année qu'ils précèdent.
-- =============================================================================

-- @titre Roll up des encaissements sur le calendrier : mois > trimestre > année (2025) > total
SELECT COALESCE(t.annee::TEXT, 'TOTAL') AS annee,
       CASE WHEN GROUPING(t.trimestre) = 1 THEN 'Sous-total' ELSE 'T' || t.trimestre END AS trimestre,
       CASE WHEN GROUPING(t.mois) = 1 THEN '' ELSE max(t.libelle_mois) END AS mois,
       SUM(p.montant_ca) AS ca, COUNT(*) AS paiements
FROM dw.fact_paiements p JOIN dw.dim_temps t USING (date_key)
WHERE t.annee = 2025
GROUP BY ROLLUP (t.annee, t.trimestre, t.mois)
ORDER BY t.annee NULLS LAST, t.trimestre NULLS LAST, t.mois NULLS LAST;
