"""
common/learning_catalog.py — Catalogue pédagogique partagé (Lot L2-b)
====================================================================

Rôle
    Définir le contenu de la plateforme d'apprentissage (PDF Source 2) et les
    conventions de codes que MongoDB (Source 4) et Redis (Source 5) réutiliseront :
    - 8 catégories de modules canoniques (PDF : « Développement, Data, IA... ») ;
    - 13 thèmes par catégorie, déclinés en 3 niveaux (DEBUTANT, INTERMEDIAIRE,
      AVANCE, liste validée) ;
    - le format des codes : MOD-<CAT>-NN (exemple du PDF MongoDB : MOD-IA-01),
      COURSE-n et QUIZ-n (décision validée) ;
    - la correspondance département (PostgreSQL) -> catégorie (MySQL), qui
      permet de relier la filière d'un étudiant aux modules qu'il suit.
"""

from __future__ import annotations

CATEGORIES: tuple[str, ...] = (
    "Développement", "Data", "IA", "Réseaux", "Cybersécurité", "Management", "Finance", "Marketing",
)

CATEGORIE_CODE: dict[str, str] = {
    "Développement": "DEV", "Data": "DATA", "IA": "IA", "Réseaux": "RES",
    "Cybersécurité": "CYB", "Management": "MGT", "Finance": "FIN", "Marketing": "MKT",
}

# Nombre de modules par catégorie (total = 300, volume validé)
MODULES_PAR_CATEGORIE: dict[str, int] = {
    "Développement": 39, "Data": 39, "IA": 39, "Cybersécurité": 39,
    "Réseaux": 36, "Management": 36, "Finance": 36, "Marketing": 36,
}

NIVEAUX_MODULE: tuple[str, ...] = ("DEBUTANT", "INTERMEDIAIRE", "AVANCE")
NIVEAU_LABEL: dict[str, str] = {"DEBUTANT": "Débutant", "INTERMEDIAIRE": "Intermédiaire", "AVANCE": "Avancé"}

THEMES: dict[str, tuple[str, ...]] = {
    "Développement": ("Algorithmique", "Python", "Java", "JavaScript", "HTML et CSS", "React", "Node.js",
                      "PHP et Laravel", "Git et GitHub", "Programmation orientée objet", "Tests logiciels",
                      "API REST", "Développement mobile Flutter"),
    "Data": ("SQL", "Python pour la Data", "Pandas", "Statistiques descriptives", "Data Visualisation",
             "Power BI", "Excel avancé", "Modélisation de données", "ETL et intégration", "Data Warehouse",
             "NoSQL et MongoDB", "Big Data avec Spark", "Qualité des données"),
    "IA": ("Machine Learning", "Deep Learning", "Traitement du langage naturel", "Vision par ordinateur",
           "Réseaux de neurones", "Scikit-learn", "TensorFlow", "IA générative", "Prompt engineering",
           "Apprentissage par renforcement", "Éthique de l'IA", "MLOps", "Séries temporelles"),
    "Réseaux": ("Fondamentaux des réseaux", "TCP/IP", "Routage et commutation", "Administration Linux",
                "Windows Server", "Virtualisation", "Cloud AWS", "Docker", "Kubernetes", "Téléphonie IP",
                "Réseaux sans fil", "Supervision réseau", "DevOps et CI/CD"),
    "Cybersécurité": ("Sécurité des réseaux", "Cryptographie", "Pentest", "Sécurité web", "Analyse de malware",
                      "Forensique", "Gestion des identités", "SOC et SIEM", "Sécurité du cloud",
                      "Normes ISO 27001", "Hacking éthique", "Sécurité mobile", "Réponse aux incidents"),
    "Management": ("Gestion de projet", "Méthodes agiles Scrum", "Leadership", "Communication professionnelle",
                   "Management d'équipe", "Entrepreneuriat", "Stratégie d'entreprise", "Gestion du changement",
                   "Négociation", "Management de la qualité", "Gestion des risques", "Prise de parole en public",
                   "Business model"),
    "Finance": ("Comptabilité générale", "SYSCOHADA", "Analyse financière", "Contrôle de gestion",
                "Fiscalité sénégalaise", "Finance d'entreprise", "Mathématiques financières", "Audit",
                "Gestion de trésorerie", "Microfinance", "Mobile money et fintech", "Budget et prévisions",
                "Excel pour la finance"),
    "Marketing": ("Marketing digital", "Réseaux sociaux", "SEO", "Publicité en ligne", "E-commerce",
                  "Content marketing", "Email marketing", "Branding", "Analyse du comportement client",
                  "Growth hacking", "Google Analytics", "Community management", "Stratégie marketing"),
}

LECONS: tuple[str, ...] = ("Introduction", "Concepts clés", "Mise en pratique", "Étude de cas",
                           "Approfondissement", "Projet guidé", "Synthèse")

TYPES_COURS: tuple[str, ...] = ("Vidéo", "PDF", "TP", "Projet")  # valeurs du PDF

# Département PostgreSQL (common/academic_catalog.py) -> catégorie de module
DEPARTEMENT_VERS_CATEGORIE: dict[str, str] = {
    "Informatique": "Développement",
    "Data": "Data",
    "Intelligence Artificielle": "IA",
    "Réseaux et Télécommunications": "Réseaux",
    "Cybersécurité": "Cybersécurité",
    "Management": "Management",
    "Finance et Comptabilité": "Finance",
    "Marketing Digital": "Marketing",
}

# Appareils et navigateurs canoniques (PDF temps_connexion : Mobile, PC, Tablette)
APPAREILS: tuple[str, ...] = ("Mobile", "PC", "Tablette")
NAVIGATEURS_PC: tuple[str, ...] = ("Chrome", "Firefox", "Edge", "Safari", "Opera")
NAVIGATEURS_MOBILE: tuple[str, ...] = ("Chrome", "Safari", "Opera")


def module_code(categorie: str, numero: int) -> str:
    """MOD-IA-01 (format de l'exemple du PDF MongoDB)."""
    return f"MOD-{CATEGORIE_CODE[categorie]}-{numero:02d}"


def course_code(n: int) -> str:
    return f"COURSE-{n}"


def quiz_code(n: int) -> str:
    return f"QUIZ-{n}"


def validate_learning_catalog() -> list[str]:
    problems: list[str] = []
    if sum(MODULES_PAR_CATEGORIE.values()) != 300:
        problems.append("le total des modules doit valoir 300")
    for cat in CATEGORIES:
        themes = THEMES.get(cat, ())
        if len(set(themes)) != len(themes):
            problems.append(f"{cat} : thèmes en double")
        if MODULES_PAR_CATEGORIE[cat] > len(themes) * len(NIVEAUX_MODULE):
            problems.append(f"{cat} : pas assez de thèmes pour {MODULES_PAR_CATEGORIE[cat]} modules uniques")
        if MODULES_PAR_CATEGORIE[cat] > 99:
            problems.append(f"{cat} : le code MOD-XX-NN limite à 99 modules")
    if set(DEPARTEMENT_VERS_CATEGORIE.values()) != set(CATEGORIES):
        problems.append("chaque catégorie doit correspondre à un département")
    return problems
