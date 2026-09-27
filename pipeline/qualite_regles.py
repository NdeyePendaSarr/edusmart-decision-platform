"""
pipeline/qualite_regles.py — Catalogue des règles qualité (Phase 5, Lot L5)
==========================================================================

Chaque règle a :
    - une DIMENSION de la Phase 5 : complétude, unicité, cohérence, exactitude, fraîcheur ;
    - une ACTION : CORRIGE (valeur déduite sans ambiguïté), REJETE (ligne écartée
      de la couche clean, conservée dans quality.rejets), SIGNALE (ligne gardée,
      marquée ; valeur invalide neutralisée à NULL lorsque la bonne valeur est inconnaissable) ;
    - les codes d'ANOMALIES du volet A qu'elle couvre (lien utilisé par la porte G3).
      Une règle sans anomalie est un contrôle supplémentaire (intégration, référentiel).

Le code SQL (pipeline/sql/clean/*.sql) utilise ces codes ; transform.py
charge ce catalogue dans quality.regles avant chaque exécution.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Regle:
    code: str
    dimension: str
    source: str
    table: str
    colonne: str | None
    action: str
    anomalies: tuple[str, ...]
    description: str


def _r(code, dim, src, table, col, action, anomalies, desc):
    return Regle(code, dim, src, table, col, action, tuple(anomalies), desc)


PG, MY, CSV, MG, RD = "s1_postgresql", "s2_mysql", "s3_csv", "s4_mongodb", "s5_redis"
C, R, S = "CORRIGE", "REJETE", "SIGNALE"

REGLES: tuple[Regle, ...] = (
    # --- Source 1 : PostgreSQL -------------------------------------------------------------------
    _r("PG_SEXE", "COHERENCE", PG, "etudiants", "sexe", C, ["A01"], "Sexe standardisé en M / F (Homme, Garçon, 1 -> M ; Femme, Fille, 0 -> F)"),
    _r("PG_SEXE_INCONNU", "COHERENCE", PG, "etudiants", "sexe", S, [], "Sexe hors référentiel : neutralisé"),
    _r("PG_TEL_MANQUANT", "COMPLETUDE", PG, "etudiants", "telephone", S, ["A02"], "Téléphone manquant"),
    _r("PG_TEL_FORMAT", "EXACTITUDE", PG, "etudiants", "telephone", C, ["A03"], "Téléphone reformaté en +221 7X XXX XX XX"),
    _r("PG_TEL_INVALIDE", "EXACTITUDE", PG, "etudiants", "telephone", S, ["A03"], "Téléphone illisible : neutralisé"),
    _r("PG_ADRESSE_MANQUANTE", "COMPLETUDE", PG, "etudiants", "adresse", S, ["A04"], "Adresse manquante"),
    _r("PG_VILLE", "COHERENCE", PG, "etudiants", "ville", C, ["A05"], "Ville ramenée au référentiel (casse, espaces, accents)"),
    _r("PG_VILLE_INCONNUE", "COHERENCE", PG, "etudiants", "ville", S, ["A05"], "Ville absente du référentiel"),
    _r("PG_VILLE_REGION", "COHERENCE", PG, "etudiants", "region", S, [], "Région incohérente avec la ville"),
    _r("PG_NOM_CASSE", "EXACTITUDE", PG, "etudiants", "nom", C, ["A06"], "Nom tout en majuscules ou minuscules : casse de titre"),
    _r("PG_SANS_COMPTE_LMS", "COHERENCE", PG, "etudiants", "student_code", S, [], "Étudiant inscrit sans compte LMS (non rapprochable)"),
    _r("PG_LIBELLE_FILIERE", "COHERENCE", PG, "filieres", "nom_filiere", C, ["A07"], "Libellé de filière standardisé (IA, Ingénierie IA -> Intelligence Artificielle)"),
    _r("PG_SALLE", "COHERENCE", PG, "classes", "salle", C, ["A08"], "Salle standardisée (Salle A101, A-101 -> A101)"),
    _r("PG_ANNEE", "COHERENCE", PG, "classes", "annee_academique", C, ["A09"], "Année académique standardisée en AAAA-AAAA"),
    _r("PG_INSCRIPTION_DOUBLON", "UNICITE", PG, "inscriptions", None, R, ["A10"], "Inscription en double (même étudiant, même classe) : une seule conservée"),
    _r("PG_INSCRIPTION_ORPHELINE", "COHERENCE", PG, "inscriptions", "id_etudiant", R, [], "Inscription d'un étudiant ou d'une classe inexistant"),
    _r("PG_REDUCTION", "EXACTITUDE", PG, "inscriptions", "reduction", S, ["A11"], "Réduction hors [0, 100] : neutralisée"),
    _r("PG_INSCRIPTION_TARDIVE", "COHERENCE", PG, "inscriptions", "date_inscription", S, ["A12"], "Inscription postérieure à la rentrée (1er octobre)"),
    _r("PG_PAIEMENT_ORPHELIN", "COHERENCE", PG, "paiements", "id_inscription", R, ["A16"], "Paiement rattaché à une inscription inexistante"),
    _r("PG_REFERENCE_DOUBLON", "UNICITE", PG, "paiements", "reference", S, ["A13"], "Référence de paiement partagée par plusieurs paiements"),
    _r("PG_MONTANT_NEGATIF", "EXACTITUDE", PG, "paiements", "montant", S, ["A14"], "Montant négatif : conservé, exclu du CA (définition validée en L3)"),
    _r("PG_MODE_PAIEMENT", "COHERENCE", PG, "paiements", "mode_paiement", C, ["A15"], "Mode de paiement standardisé (OM, orange money -> Orange Money...)"),
    _r("PG_MODE_INCONNU", "COHERENCE", PG, "paiements", "mode_paiement", S, [], "Mode de paiement hors référentiel"),
    # --- Source 2 : MySQL ------------------------------------------------------------------------
    _r("MY_CATEGORIE", "COHERENCE", MY, "modules", "categorie", C, ["B01"], "Catégorie standardisée (DATA, data science -> Data...)"),
    _r("MY_CATEGORIE_INCONNUE", "COHERENCE", MY, "modules", "categorie", S, [], "Catégorie hors référentiel"),
    _r("MY_MODULE_INACTIF", "COHERENCE", MY, "modules", "actif", S, ["B02"], "Module inactif (encore suivi par des étudiants)"),
    _r("MY_TITRE_DOUBLON", "UNICITE", MY, "cours", "titre", S, ["B03"], "Titre de cours partagé par plusieurs cours"),
    _r("MY_QUIZ_DUREE", "EXACTITUDE", MY, "quiz", "duree_minutes", S, ["B04"], "Durée de quiz incohérente : neutralisée"),
    _r("MY_NOTE_DOUBLON", "UNICITE", MY, "notes", None, R, ["B12"], "Résultat en double : un seul conservé"),
    _r("MY_STUDENT_CODE", "EXACTITUDE", MY, "notes", "student_code", C, ["B13"], "student_code normalisé en LMS-XXXXXX"),
    _r("MY_STUDENT_CODE_INVALIDE", "EXACTITUDE", MY, "notes", "student_code", S, ["B13"], "student_code illisible"),
    _r("MY_SCORE_SUP_MAX", "EXACTITUDE", MY, "notes", "score", S, ["B14"], "Score supérieur au score maximal : neutralisé"),
    _r("MY_PROGRESSION_DOUBLON", "UNICITE", MY, "progression", None, R, ["B15"], "Deux progressions pour un même étudiant et un même module"),
    _r("MY_PROGRESSION_MODULE_INCONNU", "COHERENCE", MY, "progression", "id_module", R, ["B07"], "Progression sur un module inexistant"),
    _r("MY_PROGRESSION_HORS_BORNES", "EXACTITUDE", MY, "progression", "pourcentage", S, ["B05", "B06"], "Progression hors [0, 100] : neutralisée"),
    _r("MY_CONNEXION_SANS_FIN", "COMPLETUDE", MY, "temps_connexion", "date_deconnexion", S, ["B08"], "Connexion sans déconnexion"),
    _r("MY_DUREE_NEGATIVE", "EXACTITUDE", MY, "temps_connexion", "duree_minutes", C, ["B09"], "Durée négative recalculée à partir des horodatages"),
    _r("MY_IP_INVALIDE", "EXACTITUDE", MY, "temps_connexion", "adresse_ip", S, ["B10"], "Adresse IP invalide : neutralisée"),
    _r("MY_APPAREIL", "COHERENCE", MY, "temps_connexion", "appareil", C, ["B11"], "Appareil standardisé (mobile, Téléphone -> Mobile...)"),
    _r("MY_APPAREIL_INCONNU", "COHERENCE", MY, "temps_connexion", "appareil", S, [], "Appareil hors référentiel"),
    _r("MY_NAVIGATEUR_MANQUANT", "COMPLETUDE", MY, "temps_connexion", "navigateur", S, ["B16"], "Navigateur manquant"),
    _r("MY_LMS_SANS_INSCRIPTION", "COHERENCE", MY, "comptes_lms", "student_code", S, [], "Compte LMS sans inscription PostgreSQL (non rapprochable)"),
    # --- Source 3 : CSV RH -----------------------------------------------------------------------
    _r("CSV_ENSEIGNANT_DOUBLON", "UNICITE", CSV, "enseignants", None, R, ["C07"], "Ligne dupliquée"),
    _r("CSV_TELEPHONE", "EXACTITUDE", CSV, "enseignants", "telephone", C, ["C01"], "Téléphone reformaté"),
    _r("CSV_TELEPHONE_INVALIDE", "EXACTITUDE", CSV, "enseignants", "telephone", S, ["C01"], "Téléphone illisible (tronqué) : neutralisé"),
    _r("CSV_EMAIL_MANQUANT", "COMPLETUDE", CSV, "enseignants", "email", S, ["C02"], "E-mail manquant"),
    _r("CSV_SPECIALITE", "COHERENCE", CSV, "enseignants", "specialite", C, ["C03"], "Spécialité standardisée (IA -> Intelligence Artificielle...)"),
    _r("CSV_SPECIALITE_INCONNUE", "COHERENCE", CSV, "enseignants", "specialite", S, [], "Spécialité hors référentiel"),
    _r("CSV_GRADE", "COHERENCE", CSV, "enseignants", "grade", C, ["C04"], "Grade standardisé (Prof. -> PROFESSEUR...)"),
    _r("CSV_GRADE_INCONNU", "COHERENCE", CSV, "enseignants", "grade", S, [], "Grade hors référentiel"),
    _r("CSV_DATE_NAISSANCE", "EXACTITUDE", CSV, "enseignants", "date_naissance", C, ["C05"], "Date de naissance lue au format JJ/MM/AAAA ou MM-JJ-AAAA"),
    _r("CSV_DATE_EMBAUCHE", "EXACTITUDE", CSV, "enseignants", "date_embauche", C, ["C06"], "Date d'embauche lue au format JJ/MM/AAAA ou MM-JJ-AAAA"),
    _r("CSV_DEPARTEMENT_VARIANTE", "UNICITE", CSV, "departements", "nom_departement", R, ["C08"], "Même département sous un autre nom : fusionné dans le département canonique"),
    _r("CSV_BUDGET_MANQUANT", "COMPLETUDE", CSV, "departements", "budget_annuel", S, ["C09"], "Budget manquant"),
    _r("CSV_SALAIRE_DOUBLON", "UNICITE", CSV, "salaires", None, R, ["C12"], "Ligne dupliquée"),
    _r("CSV_SALAIRE_NEGATIF", "EXACTITUDE", CSV, "salaires", "salaire_net", C, ["C10"], "Salaire net négatif recalculé (base + primes - retenues)"),
    _r("CSV_PRIMES_INCOHERENTES", "COHERENCE", CSV, "salaires", "primes", S, ["C11"], "Primes supérieures au salaire de base : neutralisées"),
    _r("CSV_MODE_PAIEMENT", "COHERENCE", CSV, "salaires", "mode_paiement", C, ["C13"], "Mode de paiement standardisé (Banque, bank transfer -> Virement bancaire)"),
    _r("CSV_MOIS", "EXACTITUDE", CSV, "salaires", "mois", C, ["C14"], "Mois standardisé (Fevrier, 03, Sept. -> numéro et nom)"),
    _r("CSV_ABSENCE_DOUBLON", "UNICITE", CSV, "absences", None, R, ["C15"], "Ligne dupliquée"),
    _r("CSV_MOTIF_MANQUANT", "COMPLETUDE", CSV, "absences", "motif", S, ["C16"], "Absence sans motif"),
    _r("CSV_DATE_ABSENCE", "EXACTITUDE", CSV, "absences", "date_absence", C, ["C19"], "Date d'absence lue au format JJ/MM/AAAA ou MM-JJ-AAAA"),
    _r("CSV_DATE_ABSENCE_INCOHERENTE", "COHERENCE", CSV, "absences", "date_absence", R, ["C17"], "Absence avant l'embauche ou après la date de référence"),
    _r("CSV_DUREE_ABSENCE", "EXACTITUDE", CSV, "absences", "duree_heures", S, ["C18"], "Durée d'absence supérieure à 24 h : neutralisée"),
    # --- Source 4 : MongoDB ----------------------------------------------------------------------
    _r("MG_DOUBLON", "UNICITE", MG, "events", None, R, ["D09"], "Événement dupliqué (même event_id)"),
    _r("MG_DOCUMENT_INCOMPLET", "COMPLETUDE", MG, "events", None, S, ["D01"], "Document tronqué (5 champs standard ou plus absents)"),
    _r("MG_CHAMP_ABSENT", "COMPLETUDE", MG, "events", None, S, ["D02"], "Un champ standard absent"),
    _r("MG_VALEUR_NULLE", "COMPLETUDE", MG, "events", None, S, ["D03"], "Champ standard à null"),
    _r("MG_VILLE", "COHERENCE", MG, "events", "city", C, ["D04"], "Ville ramenée au référentiel (DAKAR, dakarr -> Dakar)"),
    _r("MG_VILLE_INCONNUE", "COHERENCE", MG, "events", "city", S, ["D04"], "Ville absente du référentiel"),
    _r("MG_VERSION", "COHERENCE", MG, "events", "app_version", C, ["D05"], "Version normalisée en X.Y.Z (2.4, v2.4 -> 2.4.0)"),
    _r("MG_VERSION_INVALIDE", "COHERENCE", MG, "events", "app_version", S, [], "Version illisible"),
    _r("MG_OS", "COHERENCE", MG, "events", "operating_system", C, ["D06"], "Système standardisé (ANDROID, android -> Android)"),
    _r("MG_ETUDIANT_RECUPERE", "COMPLETUDE", MG, "events", "student_code", C, ["D07"], "student_code absent retrouvé par la session"),
    _r("MG_SANS_ETUDIANT", "COMPLETUDE", MG, "events", "student_code", S, ["D07"], "student_code absent et non retrouvable"),
    _r("MG_HORODATAGE", "EXACTITUDE", MG, "events", "timestamp", C, ["D08"], "Horodatage texte ou nombre converti en date"),
    _r("MG_HORODATAGE_INVALIDE", "EXACTITUDE", MG, "events", "timestamp", S, ["D08"], "Horodatage illisible"),
    _r("MG_IP_INVALIDE", "EXACTITUDE", MG, "events", "ip_address", S, ["D10"], "Adresse IP invalide : neutralisée"),
    _r("MG_DUREE_NEGATIVE", "EXACTITUDE", MG, "events", "duration_seconds", S, ["D11"], "Durée négative : neutralisée"),
    _r("MG_CONTENU_HORS_MAPPING", "COHERENCE", MG, "events", "course_code", S, [], "Code de cours ou de quiz absent de mapping_courses (non résoluble)"),
    # --- Source 5 : Redis ------------------------------------------------------------------------
    _r("RD_SESSION_EXPIREE", "COHERENCE", RD, "sessions", "status", C, ["E01"], "Session sans activité depuis plus de 24 h : statut EXPIREE"),
    _r("RD_SESSION_INACTIVE", "COHERENCE", RD, "sessions", "status", C, ["E02"], "Session sans activité depuis plus de 30 min : statut INACTIVE"),
    _r("RD_SESSION_ETUDIANT_RECUPERE", "COMPLETUDE", RD, "sessions", "student_code", C, ["E07"], "Étudiant de la session retrouvé dans MongoDB"),
    _r("RD_SESSION_SANS_ETUDIANT", "COMPLETUDE", RD, "sessions", "student_code", S, ["E07"], "Session sans étudiant, non retrouvable"),
    _r("RD_COMPTEUR", "COHERENCE", RD, "compteurs", "valeur", C, ["E03"], "Compteur recalculé à partir des sessions et des événements"),
    _r("RD_COMPTEUR_NON_VERIFIABLE", "COHERENCE", RD, "compteurs", "valeur", S, [], "Compteur sans source de vérification (active_teachers)"),
    _r("RD_NOTIFICATION_DOUBLON", "UNICITE", RD, "notifications", "message", R, ["E04"], "Notification en double dans la liste"),
    _r("RD_PROGRESSION_HORS_BORNES", "EXACTITUDE", RD, "progress", "progress", S, ["E05"], "Progression hors [0, 100] : neutralisée"),
    _r("RD_ETUDIANT_INCONNU", "COHERENCE", RD, "*", "student_code", R, ["E06"], "Étudiant inconnu des autres systèmes"),
)

REGLES_PAR_CODE = {r.code: r for r in REGLES}
DIMENSIONS = ("COMPLETUDE", "UNICITE", "COHERENCE", "EXACTITUDE", "FRAICHEUR")
# Anomalies de doublon dont la copie porte un NOUVEL identifiant : la preuve est « le groupe est dédoublonné »
DOUBLONS_NOUVEL_ID = {"A10", "B12", "B15"}


def anomalies_couvertes() -> set[str]:
    return {a for r in REGLES for a in r.anomalies}
