-- =============================================================================
-- EduSmart — Source 1 : PostgreSQL « Gestion académique »
-- Fichier : check_constraints.sql  (3/3 : diagnostic, réutilisé en Phase 15)
-- -----------------------------------------------------------------------------
-- Lecture seule (aucune donnée n'est modifiée).
--   Partie 1 : état des contraintes (validées ou non) dans le catalogue.
--   Partie 2 : nombre de lignes violant chaque règle du PDF.
--   Partie 3 : tentative de VALIDATE CONSTRAINT sur les contraintes non
--              validées : l'échec est ATTENDU et prouve la présence des
--              anomalies. Chaque tentative est isolée (bloc EXCEPTION).
-- Exécution : psql -f check_constraints.sql  (ou via Adminer)
-- =============================================================================

-- Partie 1 — État des contraintes CHECK et FOREIGN KEY
SELECT conrelid::regclass AS table_name,
       conname            AS contrainte,
       CASE contype WHEN 'c' THEN 'CHECK' WHEN 'f' THEN 'FOREIGN KEY' END AS type,
       convalidated       AS validee
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
  AND contype IN ('c', 'f')
ORDER BY convalidated, conrelid::regclass::text, conname;

-- Partie 2 — Violations par règle métier du PDF
SELECT 'etudiants.sexe hors (M,F)'           AS regle, COUNT(*) AS violations
  FROM etudiants WHERE sexe NOT IN ('M', 'F') OR sexe IS NULL
UNION ALL
SELECT 'inscriptions.reduction hors [0,100]', COUNT(*)
  FROM inscriptions WHERE reduction NOT BETWEEN 0 AND 100
UNION ALL
SELECT 'paiements.montant < 0', COUNT(*)
  FROM paiements WHERE montant < 0
UNION ALL
SELECT 'paiements orphelins (inscription inexistante)', COUNT(*)
  FROM paiements p
  WHERE p.id_inscription IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM inscriptions i WHERE i.id_inscription = p.id_inscription)
UNION ALL
SELECT 'paiements.reference en double (lignes concernées)', COALESCE(SUM(n), 0)
  FROM (SELECT COUNT(*) AS n FROM paiements GROUP BY reference HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'etudiants.date_naissance >= aujourd''hui', COUNT(*)
  FROM etudiants WHERE date_naissance >= CURRENT_DATE;

-- Partie 3 — Tentatives de validation (échecs attendus)
DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT conrelid::regclass::text AS tbl, conname
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
          AND contype IN ('c', 'f')
          AND NOT convalidated
        ORDER BY 1, 2
    LOOP
        BEGIN
            EXECUTE format('ALTER TABLE %I VALIDATE CONSTRAINT %I', c.tbl, c.conname);
            -- Si la validation réussit, on lève une erreur volontaire pour
            -- ANNULER ce sous-bloc : le script reste en lecture seule.
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'validation réussie';
        EXCEPTION
            WHEN check_violation OR foreign_key_violation THEN
                RAISE NOTICE '[ATTENDU]   % . % : échec de validation -> %', c.tbl, c.conname, SQLERRM;
            WHEN raise_exception THEN
                RAISE NOTICE '[INATTENDU] % . % : aucune violation (anomalies absentes ?)', c.tbl, c.conname;
        END;
    END LOOP;
END $$;
