"""
sources/s5_redis/create_source.py — Structure de la Source 5 (Lot L2-e)
======================================================================

Redis n'a pas de schéma : la « création » consiste à DÉFINIR précisément les
structures (motif de clé, type Redis, champs, durée de vie) et à préparer une
base vide. Ce module :
    1. décrit les 7 structures du PDF + last_quiz (écart validé) dans STRUCTURES ;
    2. génère sources/s5_redis/dictionnaire_structures.md ;
    3. vide la base Redis d'EduSmart (FLUSHDB) avant chaque chargement : le
       snapshot est régénéré par graine avant chaque extraction (décision validée).

Snapshot figé : l'état de la plateforme le 15/09/2026 à 23 h 00 (convention C24).

Exécution : python -m sources.s5_redis.create_source   (conteneur redis démarré)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common.config import ConfigError, get_settings
from common.logger import get_logger

logger = get_logger("s5_create")

SOURCE = "s5_redis"
SNAPSHOT = datetime(2026, 9, 15, 23, 0, 0)         # C24 : 15/09/2026 23 h 00 (date de référence C20)
INACTIVITE_MAX_MIN = 30                             # au-delà, une session est considérée inactive
TTL_SESSION = 24 * 3600                             # décision validée : 24 h
TTL_PROGRESS = 7 * 24 * 3600                        # « progression conservée temporairement » (PDF)
TTL_STATISTICS = 3600                               # statistics:today expire à minuit
DATE_FMT = "%Y-%m-%d %H:%M:%S"                      # format de l'exemple du PDF
DICTIONNAIRE_PATH = Path(__file__).resolve().parent / "dictionnaire_structures.md"

SESSION_FIELDS = ("student_code", "status", "login_time", "last_activity", "device", "ip")   # PDF
PROGRESS_FIELDS = ("module", "course", "progress", "last_update")                             # PDF
STATISTICS_FIELDS = ("active_students", "active_teachers", "quiz_running", "videos_streaming")  # PDF


@dataclass(frozen=True)
class Structure:
    numero: str
    nom: str
    motif: str
    type_redis: str
    contenu: str
    ttl: str
    regles: str


STRUCTURES: tuple[Structure, ...] = (
    Structure("1", "Sessions utilisateurs", "session:{session_id}", "hash",
              "student_code, status, login_time, last_activity, device, ip", "24 h",
              "Une session appartient à un seul étudiant ; TTL ; une session inactive expire."),
    Structure("2", "Dernier cours consulté", "last_course:{student_code}", "string", "COURSE-n", "aucun",
              "Une seule valeur par étudiant ; mise à jour à chaque ouverture de cours."),
    Structure("3", "Progression rapide", "progress:{student_code}", "hash",
              "module, course, progress, last_update", "7 jours",
              "Conservée temporairement, puis enregistrée dans MySQL."),
    Structure("4", "Classement des étudiants", "leaderboard:python", "zset", "student_code -> score", "aucun",
              "Tri automatique ; évolue après chaque quiz."),
    Structure("5", "Notifications", "notifications:{student_code}", "list", "messages (le plus récent en tête)",
              "aucun", "Consommées puis supprimées."),
    Structure("6", "Nombre d'utilisateurs connectés", "online_users", "string", "entier", "aucun", "—"),
    Structure("7", "Statistiques temps réel", "statistics:today", "hash",
              "active_students, active_teachers, quiz_running, videos_streaming", "jusqu'à minuit", "—"),
    Structure("+", "Dernier quiz réalisé (écart validé)", "last_quiz:{student_code}", "string", "QUIZ-n", "aucun",
              "Mentionné par le cadrage (« derniers quiz réalisés »), absent du PDF Source 5."),
)

PREFIXES_ETUDIANT = ("last_course:", "last_quiz:", "progress:", "notifications:")


def build_dictionnaire() -> str:
    lines = [
        "# Dictionnaire des structures — Source 5 : Redis", "",
        "*Généré par `python -m sources.s5_redis.create_source`. Ne pas modifier à la main.*", "",
        f"Snapshot figé : **{SNAPSHOT:%d/%m/%Y à %H h %M}** (convention C24). "
        f"Une session est active si sa dernière activité date de moins de {INACTIVITE_MAX_MIN} minutes.", "",
        "| # | Structure | Clé | Type | Contenu | TTL | Règles (PDF) |", "|---|---|---|---|---|---|---|",
        *[f"| {s.numero} | {s.nom} | `{s.motif}` | {s.type_redis.upper()} | {s.contenu} | {s.ttl} | {s.regles} |"
          for s in STRUCTURES],
        "", f"Dates au format `{DATE_FMT}` (exemple du PDF : `2026-09-15 08:15:21`).",
        "Toutes les valeurs Redis sont des chaînes de caractères.", "",
    ]
    return "\n".join(lines)


def flush(client) -> int:
    """Vide la base Redis d'EduSmart (db dédiée). Retourne le nombre de clés supprimées."""
    n = client.dbsize()
    client.flushdb()
    return n


def main() -> int:
    try:
        DICTIONNAIRE_PATH.write_text(build_dictionnaire(), encoding="utf-8")
        logger.info("Dictionnaire des structures : %s", DICTIONNAIRE_PATH)
        import redis
        client = redis.Redis(**get_settings().redis.connect_kwargs())
        try:
            logger.info("Base Redis vidée (%d clés supprimées) : prête pour insert_data", flush(client))
        finally:
            client.close()
        return 0
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Préparation de Redis impossible")
        return 2


if __name__ == "__main__":
    sys.exit(main())
