-- =============================================================================
-- EduSmart Data Warehouse — Couche CLEAN (argent) : fonctions et référentiels
-- Fichier : 00_fonctions.sql (Lot L5)
-- -----------------------------------------------------------------------------
-- Fonctions PURES de standardisation, réutilisées par tous les scripts clean.
-- Elles ne corrigent qu'en cas de lecture SANS AMBIGUÏTÉ ; sinon elles
-- renvoient NULL, et la règle qualité appelante SIGNALE la valeur.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS clean;

-- Clé de comparaison : minuscules, sans accents, espaces normalisés.
-- 'DAKAR', ' dakar ', 'Dakar' -> 'dakar' ; 'THIES', 'thiès' -> 'thies'
CREATE OR REPLACE FUNCTION clean.cle(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE sql AS $$
    SELECT NULLIF(regexp_replace(lower(translate(trim(t),
        'ÀÂÄÁÃÅÇÉÈÊËÍÌÎÏÑÓÒÔÖÕÚÙÛÜÝŸàâäáãåçéèêëíìîïñóòôöõúùûüýÿ',
        'AAAAAACEEEEIIIINOOOOOUUUUYYaaaaaaceeeeiiiinooooouuuuyy')), '\s+', ' ', 'g'), '')
$$;

-- Texte vide -> NULL (les CSV RH représentent l'absence par une chaîne vide)
CREATE OR REPLACE FUNCTION clean.vide(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE sql AS $$
    SELECT NULLIF(trim(t), '')
$$;

-- Les 3 formats de date du PDF RH. Convention (doc 04) :
--   AAAA-MM-JJ = ISO ; JJ/MM/AAAA = FR (séparateur '/') ; MM-JJ-AAAA = US ('-', année en fin)
CREATE OR REPLACE FUNCTION clean.date_multi(t TEXT) RETURNS DATE IMMUTABLE LANGUAGE plpgsql AS $$
BEGIN
    t := trim(t);
    IF t ~ '^\d{4}-\d{2}-\d{2}$' THEN RETURN to_date(t, 'YYYY-MM-DD');
    ELSIF t ~ '^\d{2}/\d{2}/\d{4}$' THEN RETURN to_date(t, 'DD/MM/YYYY');
    ELSIF t ~ '^\d{2}-\d{2}-\d{4}$' THEN RETURN to_date(t, 'MM-DD-YYYY');
    END IF;
    RETURN NULL;
EXCEPTION WHEN OTHERS THEN RETURN NULL;           -- ex. 31/02/2024
END $$;

CREATE OR REPLACE FUNCTION clean.date_iso(t TEXT) RETURNS BOOLEAN IMMUTABLE LANGUAGE sql AS $$
    SELECT trim(t) ~ '^\d{4}-\d{2}-\d{2}$'
$$;

-- Téléphone mobile sénégalais -> '+221 7X XXX XX XX' ; NULL si illisible (tronqué, préfixe inconnu)
CREATE OR REPLACE FUNCTION clean.telephone(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE d TEXT := regexp_replace(coalesce(t, ''), '\D', '', 'g');
BEGIN
    IF d ~ '^00221' THEN d := substr(d, 6); ELSIF d ~ '^221' AND length(d) = 12 THEN d := substr(d, 4); END IF;
    IF d ~ '^7[05678]\d{7}$' THEN
        RETURN '+221 ' || substr(d, 1, 2) || ' ' || substr(d, 3, 3) || ' ' || substr(d, 6, 2) || ' ' || substr(d, 8, 2);
    END IF;
    RETURN NULL;
END $$;

-- student_code -> 'LMS-XXXXXX' : 'lms-000154', 'LMS000154', 'LMS-154', 'LMS_000154', ' LMS-000154'
CREATE OR REPLACE FUNCTION clean.student_code(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE sql AS $$
    SELECT 'LMS-' || lpad(m[1], 6, '0') FROM (SELECT regexp_match(upper(trim(t)), '^LMS[-_]?0*(\d{1,6})$') AS m) x
    WHERE m IS NOT NULL
$$;

-- Version d'application -> 'X.Y.Z' : 'v2.4' -> '2.4.0' ; '2.4.1.0' -> '2.4.1'
CREATE OR REPLACE FUNCTION clean.version(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE v TEXT := regexp_replace(trim(t), '^[vV]', '');
BEGIN
    IF v ~ '^\d+\.\d+$' THEN v := v || '.0'; END IF;
    IF v ~ '^\d+\.\d+\.\d+\.0$' THEN v := regexp_replace(v, '\.0$', ''); END IF;
    IF v ~ '^\d+\.\d+\.\d+$' THEN RETURN v; END IF;
    RETURN NULL;
END $$;

-- Année académique -> 'AAAA-AAAA' : '2023/2024', '2023-24', '23-24', '2023 - 2024'
CREATE OR REPLACE FUNCTION clean.annee_academique(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE m TEXT[] := regexp_match(trim(t), '^(\d{2}|\d{4})\s*[-/]\s*(\d{2}|\d{4})$'); a INT; b INT;
BEGIN
    IF m IS NULL THEN RETURN NULL; END IF;
    a := CASE WHEN length(m[1]) = 2 THEN 2000 + m[1]::INT ELSE m[1]::INT END;
    b := CASE WHEN length(m[2]) = 2 THEN (a / 100) * 100 + m[2]::INT ELSE m[2]::INT END;
    IF b = a + 1 THEN RETURN a || '-' || b; END IF;
    RETURN NULL;
END $$;

-- Salle -> 'A101' : 'Salle A101', 'A-101'
CREATE OR REPLACE FUNCTION clean.salle(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE sql AS $$
    SELECT m[1] || m[2] FROM (SELECT regexp_match(upper(trim(t)), '^(?:SALLE\s+)?([A-Z])-?(\d{3})$') AS m) x WHERE m IS NOT NULL
$$;

-- Mois (texte libre) -> 1..12 : 'Février', 'FEVRIER', 'févr.', '02', 'Août', 'Sept.'
CREATE OR REPLACE FUNCTION clean.mois(t TEXT) RETURNS INT IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE k TEXT := rtrim(clean.cle(t), '.');
BEGIN
    IF k ~ '^\d{1,2}$' THEN RETURN CASE WHEN k::INT BETWEEN 1 AND 12 THEN k::INT END; END IF;
    RETURN CASE
        WHEN k LIKE 'jan%' THEN 1 WHEN k LIKE 'fev%' THEN 2 WHEN k LIKE 'mar%' THEN 3 WHEN k LIKE 'avr%' THEN 4
        WHEN k LIKE 'mai%' THEN 5 WHEN k LIKE 'juin%' THEN 6 WHEN k LIKE 'juil%' THEN 7 WHEN k LIKE 'aou%' THEN 8
        WHEN k LIKE 'sep%' THEN 9 WHEN k LIKE 'oct%' THEN 10 WHEN k LIKE 'nov%' THEN 11 WHEN k LIKE 'dec%' THEN 12 END;
END $$;

-- Adresse IP valide (IPv4 stricte : 4 octets de 0 à 255 ; IPv6 via le type inet)
CREATE OR REPLACE FUNCTION clean.ip_valide(t TEXT) RETURNS BOOLEAN IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE o TEXT[];
BEGIN
    IF t IS NULL THEN RETURN NULL; END IF;
    IF t ~ '^\d{1,3}(\.\d{1,3}){3}$' THEN
        o := string_to_array(t, '.');
        RETURN o[1]::INT <= 255 AND o[2]::INT <= 255 AND o[3]::INT <= 255 AND o[4]::INT <= 255;
    ELSIF t ~ ':' THEN
        PERFORM t::INET;
        RETURN TRUE;
    END IF;
    RETURN FALSE;
EXCEPTION WHEN OTHERS THEN RETURN FALSE;
END $$;

-- Booléens des sources : PostgreSQL 'true'/'false', MySQL '1'/'0', CSV RH 'Oui'/'Non'
CREATE OR REPLACE FUNCTION clean.booleen(t TEXT) RETURNS BOOLEAN IMMUTABLE LANGUAGE sql AS $$
    SELECT CASE clean.cle(t) WHEN 'true' THEN TRUE WHEN 't' THEN TRUE WHEN '1' THEN TRUE WHEN 'oui' THEN TRUE
                             WHEN 'false' THEN FALSE WHEN 'f' THEN FALSE WHEN '0' THEN FALSE WHEN 'non' THEN FALSE END
$$;

-- Numérique tolérant : NULL si illisible
CREATE OR REPLACE FUNCTION clean.nombre(t TEXT) RETURNS NUMERIC IMMUTABLE LANGUAGE plpgsql AS $$
BEGIN
    RETURN NULLIF(trim(t), '')::NUMERIC;
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END $$;

-- Horodatage MongoDB conservé en JSONB : date ($date), texte (3 formats) ou nombre (epoch en ms)
CREATE OR REPLACE FUNCTION clean.horodatage_json(j JSONB) RETURNS TIMESTAMP IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE s TEXT;
BEGIN
    IF j IS NULL THEN RETURN NULL; END IF;
    CASE jsonb_typeof(j)
        WHEN 'object' THEN RETURN ((j->>'$date')::TIMESTAMPTZ AT TIME ZONE 'UTC');
        WHEN 'number' THEN RETURN (to_timestamp((j::TEXT)::NUMERIC / 1000) AT TIME ZONE 'UTC');
        WHEN 'string' THEN
            s := j #>> '{}';
            IF s ~ '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}$' THEN RETURN replace(s, 'T', ' ')::TIMESTAMP;
            ELSIF s ~ '^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$' THEN RETURN to_timestamp(s, 'DD/MM/YYYY HH24:MI:SS')::TIMESTAMP;
            END IF;
        ELSE NULL;
    END CASE;
    RETURN NULL;
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END $$;

-- -----------------------------------------------------------------------------
-- Référentiels (remplis par pipeline/referentiels.py)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clean.ref_villes (
    cle TEXT PRIMARY KEY, ville TEXT NOT NULL, region TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clean.ref_synonymes (
    domaine TEXT NOT NULL, cle TEXT NOT NULL, valeur TEXT NOT NULL, variante TEXT NOT NULL,
    PRIMARY KEY (domaine, cle)
);
CREATE TABLE IF NOT EXISTS clean.ref_mapping_etudiants (
    id_etudiant UUID PRIMARY KEY, matricule TEXT NOT NULL, student_code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS clean.ref_mapping_contenus (
    code_externe TEXT PRIMARY KEY, type_objet TEXT NOT NULL, id_mysql TEXT NOT NULL, code_module TEXT NOT NULL
);

-- Ville -> (ville canonique, région). Si inconnue : dernière lettre doublée ('dakarr', 'Thièss').
CREATE OR REPLACE FUNCTION clean.ville(t TEXT) RETURNS TEXT STABLE LANGUAGE sql AS $$
    SELECT COALESCE(
        (SELECT ville FROM clean.ref_villes WHERE cle = clean.cle(t)),
        (SELECT ville FROM clean.ref_villes WHERE clean.cle(t) ~ '(.)\1$' AND cle = left(clean.cle(t), -1)))
$$;

CREATE OR REPLACE FUNCTION clean.synonyme(p_domaine TEXT, t TEXT) RETURNS TEXT STABLE LANGUAGE sql AS $$
    SELECT valeur FROM clean.ref_synonymes WHERE domaine = p_domaine AND cle = clean.cle(t)
$$;
