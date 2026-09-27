# Dictionnaire des structures — Source 5 : Redis

*Généré par `python -m sources.s5_redis.create_source`. Ne pas modifier à la main.*

Snapshot figé : **15/09/2026 à 23 h 00** (convention C24). Une session est active si sa dernière activité date de moins de 30 minutes.

| # | Structure | Clé | Type | Contenu | TTL | Règles (PDF) |
|---|---|---|---|---|---|---|
| 1 | Sessions utilisateurs | `session:{session_id}` | HASH | student_code, status, login_time, last_activity, device, ip | 24 h | Une session appartient à un seul étudiant ; TTL ; une session inactive expire. |
| 2 | Dernier cours consulté | `last_course:{student_code}` | STRING | COURSE-n | aucun | Une seule valeur par étudiant ; mise à jour à chaque ouverture de cours. |
| 3 | Progression rapide | `progress:{student_code}` | HASH | module, course, progress, last_update | 7 jours | Conservée temporairement, puis enregistrée dans MySQL. |
| 4 | Classement des étudiants | `leaderboard:python` | ZSET | student_code -> score | aucun | Tri automatique ; évolue après chaque quiz. |
| 5 | Notifications | `notifications:{student_code}` | LIST | messages (le plus récent en tête) | aucun | Consommées puis supprimées. |
| 6 | Nombre d'utilisateurs connectés | `online_users` | STRING | entier | aucun | — |
| 7 | Statistiques temps réel | `statistics:today` | HASH | active_students, active_teachers, quiz_running, videos_streaming | jusqu'à minuit | — |
| + | Dernier quiz réalisé (écart validé) | `last_quiz:{student_code}` | STRING | QUIZ-n | aucun | Mentionné par le cadrage (« derniers quiz réalisés »), absent du PDF Source 5. |

Dates au format `%Y-%m-%d %H:%M:%S` (exemple du PDF : `2026-09-15 08:15:21`).
Toutes les valeurs Redis sont des chaînes de caractères.
