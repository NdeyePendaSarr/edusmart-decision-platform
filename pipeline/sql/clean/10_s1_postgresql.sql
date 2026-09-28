-- =============================================================================
-- Couche CLEAN — Source 1 PostgreSQL (Lot L5)
-- staging.stg_pg_* -> clean.etudiants, filieres, classes, inscriptions, paiements
-- Chaque règle : un appel à quality.constater / quality.rejeter (catalogue qualite_regles.py).
-- =============================================================================
SELECT quality.reinitialiser('s1_postgresql');

-- ---------------------------------------------------------------- etudiants --
DROP TABLE IF EXISTS t_etu;
CREATE TEMP TABLE t_etu AS
SELECT s.*, clean.synonyme('sexe', s.sexe) AS sexe_c, clean.telephone(s.telephone) AS tel_c,
       clean.ville(s.ville) AS ville_c,
       CASE WHEN s.nom = upper(s.nom) OR s.nom = lower(s.nom) THEN initcap(lower(s.nom)) ELSE s.nom END AS nom_c,
       m.student_code
FROM staging.stg_pg_etudiants s LEFT JOIN clean.ref_mapping_etudiants m ON m.id_etudiant = s.id_etudiant::UUID;
ANALYZE t_etu;   -- statistiques (L6)

SELECT quality.constater('PG_SEXE', 'etudiants', 'SELECT id_etudiant, sexe, sexe_c FROM t_etu WHERE sexe_c IS NOT NULL AND sexe <> sexe_c');
SELECT quality.constater('PG_SEXE_INCONNU', 'etudiants', 'SELECT id_etudiant, sexe, NULL FROM t_etu WHERE sexe_c IS NULL');
SELECT quality.constater('PG_TEL_MANQUANT', 'etudiants', 'SELECT id_etudiant, NULL, NULL FROM t_etu WHERE telephone IS NULL');
SELECT quality.constater('PG_TEL_FORMAT', 'etudiants', 'SELECT id_etudiant, telephone, tel_c FROM t_etu WHERE tel_c IS NOT NULL AND telephone <> tel_c');
SELECT quality.constater('PG_TEL_INVALIDE', 'etudiants', 'SELECT id_etudiant, telephone, NULL FROM t_etu WHERE telephone IS NOT NULL AND tel_c IS NULL');
SELECT quality.constater('PG_ADRESSE_MANQUANTE', 'etudiants', 'SELECT id_etudiant, NULL, NULL FROM t_etu WHERE adresse IS NULL');
SELECT quality.constater('PG_VILLE', 'etudiants', 'SELECT id_etudiant, ville, ville_c FROM t_etu WHERE ville_c IS NOT NULL AND ville <> ville_c');
SELECT quality.constater('PG_VILLE_INCONNUE', 'etudiants', 'SELECT id_etudiant, ville, NULL FROM t_etu WHERE ville_c IS NULL');
SELECT quality.constater('PG_VILLE_REGION', 'etudiants', $q$
    SELECT t.id_etudiant, t.region, v.region FROM t_etu t JOIN clean.ref_villes v ON v.ville = t.ville_c
    WHERE t.region <> v.region $q$);
SELECT quality.constater('PG_NOM_CASSE', 'etudiants', 'SELECT id_etudiant, nom, nom_c FROM t_etu WHERE nom <> nom_c');
SELECT quality.constater('PG_SANS_COMPTE_LMS', 'etudiants', 'SELECT id_etudiant, NULL, NULL FROM t_etu WHERE student_code IS NULL');

ANALYZE quality.constats, quality.rejets;   -- statistiques (L6)
DROP TABLE IF EXISTS clean.etudiants CASCADE;
CREATE UNLOGGED TABLE clean.etudiants AS
SELECT t.id_etudiant::UUID AS id_etudiant, t.matricule, t.student_code, t.nom_c AS nom, t.prenom, t.sexe_c AS sexe,
       t.date_naissance::DATE AS date_naissance, t.tel_c AS telephone, t.email, t.adresse,
       COALESCE(t.ville_c, t.ville) AS ville, COALESCE(v.region, t.region) AS region, t.pays,
       t.date_creation::TIMESTAMP AS date_creation, COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_etu t
LEFT JOIN clean.ref_villes v ON v.ville = t.ville_c
LEFT JOIN quality.anomalies_par_ligne('s1_postgresql', 'etudiants') a ON a.id_ligne = t.id_etudiant;
ALTER TABLE clean.etudiants ADD PRIMARY KEY (id_etudiant);

-- ----------------------------------------------------------------- filieres --
DROP TABLE IF EXISTS t_fil;
CREATE TEMP TABLE t_fil AS
SELECT s.*, COALESCE(clean.synonyme('libelle_filiere', s.nom_filiere), s.nom_filiere) AS nom_c FROM staging.stg_pg_filieres s;
ANALYZE t_fil;   -- statistiques (L6)
SELECT quality.constater('PG_LIBELLE_FILIERE', 'filieres', 'SELECT id_filiere, nom_filiere, nom_c FROM t_fil WHERE nom_filiere <> nom_c');

ANALYZE quality.constats, quality.rejets;   -- statistiques (L6)
DROP TABLE IF EXISTS clean.filieres CASCADE;
CREATE UNLOGGED TABLE clean.filieres AS
SELECT t.id_filiere::UUID AS id_filiere, t.code_filiere, t.nom_c AS nom_filiere, t.nom_filiere AS nom_filiere_source,
       t.departement, t.niveau, t.duree_mois::INT AS duree_mois, t.cout_total::NUMERIC(12,2) AS cout_total, t.statut,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_fil t LEFT JOIN quality.anomalies_par_ligne('s1_postgresql', 'filieres') a ON a.id_ligne = t.id_filiere;
ALTER TABLE clean.filieres ADD PRIMARY KEY (id_filiere);

-- ------------------------------------------------------------------ classes --
DROP TABLE IF EXISTS t_cls;
CREATE TEMP TABLE t_cls AS
SELECT s.*, COALESCE(clean.salle(s.salle), s.salle) AS salle_c,
       COALESCE(clean.annee_academique(s.annee_academique), s.annee_academique) AS annee_c
FROM staging.stg_pg_classes s;
ANALYZE t_cls;   -- statistiques (L6)
SELECT quality.constater('PG_SALLE', 'classes', 'SELECT id_classe, salle, salle_c FROM t_cls WHERE salle <> salle_c');
SELECT quality.constater('PG_ANNEE', 'classes', 'SELECT id_classe, annee_academique, annee_c FROM t_cls WHERE annee_academique <> annee_c');

ANALYZE quality.constats, quality.rejets;   -- statistiques (L6)
DROP TABLE IF EXISTS clean.classes CASCADE;
CREATE UNLOGGED TABLE clean.classes AS
SELECT t.id_classe::UUID AS id_classe, t.code_classe, t.nom_classe, t.id_filiere::UUID AS id_filiere,
       t.annee_c AS annee_academique, left(t.annee_c, 4)::INT AS annee_debut, t.capacite::INT AS capacite,
       t.salle_c AS salle, t.responsable, COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_cls t LEFT JOIN quality.anomalies_par_ligne('s1_postgresql', 'classes') a ON a.id_ligne = t.id_classe;
ALTER TABLE clean.classes ADD PRIMARY KEY (id_classe);

-- ------------------------------------------------------------- inscriptions --
DROP TABLE IF EXISTS t_ins;
CREATE TEMP TABLE t_ins AS
WITH payees AS (SELECT DISTINCT id_inscription FROM staging.stg_pg_paiements)
SELECT s.*, clean.nombre(s.reduction) AS reduction_n,
       row_number() OVER w AS rn, first_value(s.id_inscription) OVER w AS conservee
FROM staging.stg_pg_inscriptions s LEFT JOIN payees p ON p.id_inscription = s.id_inscription
WINDOW w AS (PARTITION BY s.id_etudiant, s.id_classe ORDER BY (p.id_inscription IS NOT NULL) DESC, s.id_inscription);
ANALYZE t_ins;   -- statistiques (L6)

-- Doublon : on garde l'inscription qui porte des paiements (sinon la plus petite)
SELECT quality.rejeter('PG_INSCRIPTION_DOUBLON', 'inscriptions', $q$
    SELECT t.id_inscription, t._row_number, 'Doublon de ' || t.conservee, to_jsonb(s)
    FROM t_ins t JOIN staging.stg_pg_inscriptions s USING (_row_number) WHERE t.rn > 1 $q$);
SELECT quality.rejeter('PG_INSCRIPTION_ORPHELINE', 'inscriptions', $q$
    SELECT t.id_inscription, t._row_number, 'Étudiant ou classe inexistant', to_jsonb(s)
    FROM t_ins t JOIN staging.stg_pg_inscriptions s USING (_row_number)
    WHERE t.rn = 1 AND (NOT EXISTS (SELECT 1 FROM clean.etudiants e WHERE e.id_etudiant = t.id_etudiant::UUID)
                     OR NOT EXISTS (SELECT 1 FROM clean.classes c WHERE c.id_classe = t.id_classe::UUID)) $q$);
SELECT quality.constater('PG_REDUCTION', 'inscriptions', 'SELECT id_inscription, reduction, NULL FROM t_ins WHERE reduction_n NOT BETWEEN 0 AND 100');
SELECT quality.constater('PG_INSCRIPTION_TARDIVE', 'inscriptions', $q$
    SELECT t.id_inscription, t.date_inscription, NULL FROM t_ins t JOIN clean.classes c ON c.id_classe = t.id_classe::UUID
    WHERE t.date_inscription::DATE >= make_date(c.annee_debut, 10, 1) $q$);

ANALYZE quality.constats, quality.rejets;   -- statistiques (L6)
DROP TABLE IF EXISTS clean.inscriptions CASCADE;
CREATE UNLOGGED TABLE clean.inscriptions AS
SELECT t.id_inscription::UUID AS id_inscription, t.id_etudiant::UUID AS id_etudiant, t.id_classe::UUID AS id_classe,
       t.date_inscription::DATE AS date_inscription, t.statut, t.type_inscription, clean.booleen(t.bourse) AS bourse,
       CASE WHEN t.reduction_n BETWEEN 0 AND 100 THEN t.reduction_n END::NUMERIC(5,2) AS reduction,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_ins t LEFT JOIN quality.anomalies_par_ligne('s1_postgresql', 'inscriptions') a ON a.id_ligne = t.id_inscription
WHERE NOT EXISTS (SELECT 1 FROM quality.rejets r WHERE r.batch_id = current_setting('edusmart.batch_id')
                  AND r.code_source = 's1_postgresql' AND r.table_source = 'inscriptions' AND r.rang = t._row_number);
ALTER TABLE clean.inscriptions ADD PRIMARY KEY (id_inscription);

-- ---------------------------------------------------------------- paiements --
DROP TABLE IF EXISTS t_pay;
CREATE TEMP TABLE t_pay AS
SELECT s.*, clean.synonyme('mode_paiement', s.mode_paiement) AS mode_c, clean.nombre(s.montant) AS montant_n,
       COUNT(*) OVER (PARTITION BY s.reference) AS nb_reference
FROM staging.stg_pg_paiements s;
ANALYZE t_pay;   -- statistiques (L6)

SELECT quality.rejeter('PG_PAIEMENT_ORPHELIN', 'paiements', $q$
    SELECT t.id_paiement, t._row_number, 'Inscription ' || t.id_inscription || ' inexistante', to_jsonb(s)
    FROM t_pay t JOIN staging.stg_pg_paiements s USING (_row_number)
    WHERE NOT EXISTS (SELECT 1 FROM clean.inscriptions i WHERE i.id_inscription = t.id_inscription::UUID) $q$);
SELECT quality.constater('PG_REFERENCE_DOUBLON', 'paiements', 'SELECT id_paiement, reference, NULL FROM t_pay WHERE nb_reference > 1');
SELECT quality.constater('PG_MONTANT_NEGATIF', 'paiements', 'SELECT id_paiement, montant, montant FROM t_pay WHERE montant_n < 0');
SELECT quality.constater('PG_MODE_PAIEMENT', 'paiements', 'SELECT id_paiement, mode_paiement, mode_c FROM t_pay WHERE mode_c IS NOT NULL AND mode_paiement <> mode_c');
SELECT quality.constater('PG_MODE_INCONNU', 'paiements', 'SELECT id_paiement, mode_paiement, NULL FROM t_pay WHERE mode_c IS NULL');

ANALYZE quality.constats, quality.rejets;   -- statistiques (L6)
DROP TABLE IF EXISTS clean.paiements CASCADE;
CREATE UNLOGGED TABLE clean.paiements AS
SELECT t.id_paiement::UUID AS id_paiement, t.id_inscription::UUID AS id_inscription, t.reference,
       t.date_paiement::DATE AS date_paiement, t.montant_n::NUMERIC(12,2) AS montant, t.mode_c AS mode_paiement,
       t.statut, t.tranche, (t.montant_n < 0) AS montant_negatif, (t.nb_reference > 1) AS reference_partagee,
       COALESCE(a.codes, '{}') AS _anomalies, t._batch_id
FROM t_pay t LEFT JOIN quality.anomalies_par_ligne('s1_postgresql', 'paiements') a ON a.id_ligne = t.id_paiement
WHERE NOT EXISTS (SELECT 1 FROM quality.rejets r WHERE r.batch_id = current_setting('edusmart.batch_id')
                  AND r.code_source = 's1_postgresql' AND r.table_source = 'paiements' AND r.rang = t._row_number);
ALTER TABLE clean.paiements ADD PRIMARY KEY (id_paiement);

-- Statistiques à jour pour le planificateur (tables recréées)
ANALYZE clean.etudiants, clean.filieres, clean.classes, clean.inscriptions, clean.paiements;
