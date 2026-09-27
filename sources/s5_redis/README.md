# Source 5 — Redis « Plateforme temps réel »

Conteneur : `edusmart_redis` (port Windows 6380), base 0 · Redis 7

Ce document est le **document de présentation** exigé par le cadrage (Données
EduSmart.pdf, livrable 5) : structures, relations, contraintes, anomalies
introduites volontairement et volume. Le détail des clés se trouve dans
[`dictionnaire_structures.md`](dictionnaire_structures.md).

---

## 1. Fichiers livrés

| Fichier | Rôle |
|---|---|
| `create_source.py` | Définition des structures (motif de clé, type, champs, TTL), dictionnaire, vidage de la base |
| `dictionnaire_structures.md` | Description des 8 structures |
| `generate_data.py` | Déduit l'état de Redis des autres sources ; anomalies ; `snapshot.json` + journal |
| `anomalies.py` | Les 7 anomalies du PDF (E01 à E07) : injection et mesure |
| `insert_data.py` | FLUSHDB puis chargement par pipeline, avec les TTL |
| `verify_source.py` | Porte G1 : **31 contrôles**, en relisant tout Redis |

Script transversal : `python -m scripts.verify_sources` enchaîne **les 5 portes G1**.

## 2. Exécution

```powershell
python -m sources.s5_redis.create_source     # dictionnaire + base vidée
python -m sources.s5_redis.generate_data     # ~40 s (recalcule MongoDB et MySQL en mémoire)
python -m sources.s5_redis.insert_data       # < 1 s
python -m sources.s5_redis.verify_source     # porte G1 -> data/reports/s5_redis_G1.md
```

**Avant chaque extraction ETL**, relance `insert_data`. Le snapshot est figé et régénéré
à l'identique, et les TTL repartent pour 24 h.

## 3. Le snapshot figé : 15/09/2026 à 23 h 00 (convention C24)

Redis ne stocke que du temporaire (PDF). Pour obtenir des données reproductibles, la base
représente **l'état de la plateforme à un instant précis**, déduit des autres sources :

| Structure | Clé | Type | Contenu | Déduite de |
|---|---|---|---|---|
| Sessions | `session:{session_id}` | HASH | student_code, status, login_time, last_activity, device, ip | Sessions **MongoDB** non terminées, actives depuis moins de 30 min |
| Dernier cours | `last_course:{student_code}` | STRING | `COURSE-n` | Dernier `COURSE_OPENED` (MongoDB) des 30 derniers jours |
| Progression | `progress:{student_code}` | HASH | module, course, progress, last_update | Progression **MySQL** la plus récente des 30 derniers jours |
| Classement | `leaderboard:python` | SORTED SET | student_code → score /100 | Meilleures notes MySQL aux quiz des modules Python |
| Notifications | `notifications:{student_code}` | LIST | 1 à 4 messages, le plus récent en tête | Paiements, certificats, quiz et cours de la semaine |
| Connectés | `online_users` | STRING | entier | Étudiants distincts des sessions actives |
| Statistiques | `statistics:today` | HASH | active_students, active_teachers, quiz_running, videos_streaming | Événements MongoDB du jour |
| Dernier quiz *(écart validé)* | `last_quiz:{student_code}` | STRING | `QUIZ-n` | Dernier `QUIZ_SUBMITTED` (MongoDB) des 30 derniers jours |

### État réel au moment du snapshot

- **241 sessions actives** : 702 sessions MongoDB du jour ne sont pas terminées, mais seules 241 ont eu une activité dans les 30 dernières minutes.
- 241 étudiants connectés, **729 étudiants actifs dans la journée**.
- 43 vidéos en cours de lecture, **0 quiz en cours**.

## 4. Durées de vie (TTL) : le « NOT VALID » de Redis

| Clés | TTL | Justification |
|---|---|---|
| `session:*` | 24 h | Décision validée (le PDF impose un TTL aux sessions) |
| `session:*` de l'anomalie E01 | **aucun (-1)** | Sessions qui auraient dû expirer : elles ne disparaîtront jamais d'elles-mêmes |
| `progress:*` | 7 jours | « Progression conservée temporairement » (PDF) |
| `statistics:today` | jusqu'à minuit (1 h) | Statistique du jour |
| Autres | aucun | Cache permanent |

Les TTL courent à partir du **chargement réel**, pas de l'heure simulée.

## 5. Anomalies volontaires : les 7 du PDF

Journal : `data/anomalies/s5_redis_anomalies.csv`, jamais lu par l'ETL.

| Code | Anomalie du PDF | Mise en œuvre | Nb (graine 2026) | Taux |
|---|---|---|---:|---:|
| E01 | Sessions expirées mais encore présentes | Vraies sessions MongoDB **des jours précédents**, jamais terminées, sans TTL | 9 | 3,73 % des sessions |
| E02 | Utilisateurs connectés sans activité récente | Vraies sessions MongoDB du jour, `ONLINE` mais inactives depuis 31 min à 3 h | 7 | 2,90 % |
| E03 | Compteurs incohérents | `online_users` (737) supérieur à `active_students` (729), comme l'exemple du PDF (548 contre 542) ; `videos_streaming` faux | 2 / 5 compteurs | fixe |
| E04 | Notifications en double | Message répété juste après l'original | 37 | 2,05 % des messages |
| E05 | Progressions supérieures à 100 % | `progress` entre 100,5 et 150 | 69 | 4,07 % |
| E06 | Étudiants absents des autres systèmes | 137 codes `LMS-XXXXXX` jamais attribués (clés `last_course` et `progress`) | 137 | 3,99 % des étudiants |
| E07 | Sessions sans étudiant associé | Champ `student_code` absent du hash | 10 | 4,15 % |

**Total : 271 anomalies.** Sur les petites familles (257 sessions), un taux de 2 à 5 %
représente 5 à 12 clés.

## 6. Cohérence avec les autres sources

| Lien | Vérifié par G1 |
|---|---|
| Les 257 `session:{id}` sont de **vraies sessions MongoDB** (même `session_id`, même étudiant), y compris E01 et E02 | ✅ 257/257, 0 écart |
| `progress` = progression **MySQL** (module, cours, pourcentage, date) : Redis la garde avant MySQL, conformément au PDF | Par construction |
| `last_course`, `last_quiz` = derniers événements **MongoDB** ; codes du référentiel de contenus | ✅ 0 code inconnu |
| Codes étudiants = comptes LMS, sauf les 137 de E06 | ✅ |
| Aucune activité après le snapshot (15/09/2026 23 h 00, cohérent avec C20) | ✅ |

## 7. Conventions et écarts assumés

| # | Sujet | Choix | Justification |
|---|---|---|---|
| S5-01 | Instant du snapshot | 15/09/2026 à 23 h 00 (C24) | Validé en L2-d |
| S5-02 | Session active | Dernière activité il y a **moins de 30 minutes** | Délai d'inactivité web usuel ; il définit aussi E02 |
| S5-03 | `device` | Valeur de plateforme (`Android`, `iOS`), comme l'exemple du PDF | Hétérogénéité voulue : dans MongoDB, `device` est le **modèle** du téléphone |
| S5-04 | `session_id` | UUID complet de MongoDB (l'exemple du PDF `3f25c89d` est abrégé) | Permet le rapprochement avec MongoDB |
| S5-05 | `active_teachers` | Valeur plausible (30 à 45), **non vérifiable** | Aucune source ne trace l'activité des enseignants |
| S5-06 | `quiz_running` | 0 : aucune session active n'a de quiz en cours à 23 h | Valeur réelle des données, non maquillée |
| S5-07 | Volumes | Déduits des données (257 sessions et non ~600 comme prévu à l'Étape 2) | Fidélité à MongoDB plutôt qu'à une estimation |
| S5-08 | Classement | Moyenne des meilleurs scores (sur 100) aux quiz des modules « Python » et « Python pour la Data » | PDF : `leaderboard:python`, « évolue après chaque quiz » |
| S5-09 | FLUSHDB | La base 0 du conteneur Redis est **dédiée** à EduSmart | Snapshot régénéré avant chaque extraction |

## 8. Volumes (graine 2026) : 4 608 clés

| Famille | Clés |
|---|---:|
| session | 257 (241 actives + 9 E01 + 7 E02) |
| last_course | 1 113 |
| last_quiz | 545 |
| progress | 1 834 |
| notifications | 856 listes, 1 839 messages |
| leaderboard:python | 1 clé, 1 325 membres |
| online_users, statistics:today | 1 + 1 |

## 9. Porte G1 : 31 contrôles

| Groupe | Contrôles |
|---|---|
| V1 Volumes | Nombre de clés, 8 familles présentes, sessions actives = état réel (241) |
| V2 Anomalies | 7 types : mesure dans Redis = journal, taux |
| V3 Structure | Types Redis du PDF, champs des 3 HASH, TTL (sessions sans TTL = E01 ; progress ; statistics) |
| V4 Règles métier | Sessions `ONLINE`, `login_time ≤ last_activity ≤ snapshot`, scores entre 0 et 100, 4 notifications au plus |
| V5 Inter-sources | Sessions = MongoDB (même étudiant), codes inconnus = E06, codes de contenus connus |

## 10. Tests

| Fichier | Portée |
|---|---|
| `tests/test_s5_redis.py` | 11 tests sans serveur : anomalies, structure du PDF, sessions, progress, classement, codes inconnus, chargement et relecture avec **fakeredis**, reproductibilité |
| `tests/test_s5_redis_integration.py` | 4 tests sur un vrai Redis : G1, TTL réels, tri automatique du classement, rechargement |

Tous ont été exécutés sur un **vrai Redis 7** pendant le développement : G1 à 31/31 et 4/4 en intégration.
