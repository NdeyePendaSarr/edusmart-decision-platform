-- =============================================================================
-- EduSmart Data Warehouse — Création des schémas (Lot L0)
-- Exécuté automatiquement au PREMIER démarrage du conteneur pg_dw.
-- Les tables seront créées dans les lots L4 à L6.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS staging;
COMMENT ON SCHEMA staging IS 'Couche bronze : données brutes des 5 sources, chargées sans transformation (ELT)';

CREATE SCHEMA IF NOT EXISTS clean;
COMMENT ON SCHEMA clean IS 'Couche argent : données typées, standardisées, dédoublonnées';

CREATE SCHEMA IF NOT EXISTS dw;
COMMENT ON SCHEMA dw IS 'Couche or : dimensions et faits (constellation de faits)';

CREATE SCHEMA IF NOT EXISTS meta;
COMMENT ON SCHEMA meta IS 'Métadonnées et traçabilité : metadata_sources, etl_execution_log (Phase 6)';

CREATE SCHEMA IF NOT EXISTS quality;
COMMENT ON SCHEMA quality IS 'Contrôle qualité : rejets et rapport qualité (Phase 5)';
