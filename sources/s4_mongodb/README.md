# Source 4 — MongoDB « Journaux de l'application mobile »

Base : `edusmart_mobile` · Collection : `events` · Conteneur : `edusmart_mongo` (port Windows 27018) · MongoDB 6+

Ce document est le **document de présentation** exigé par le cadrage (Données
EduSmart.pdf, livrable 5) : structure, relations internes, contraintes,
anomalies introduites volontairement et volume généré.

---

## 1. Fichiers livrés

| Fichier | Rôle |
|---|---|
| `create_source.py` | 14 types d'événements, schéma flexible, **validateur `$jsonSchema`**, index ; `violates_schema()`, son équivalent Python exact |
| `generate_data.py` | Sessions et événements (liés à MySQL et PostgreSQL), anomalies ; écrit `events.jsonl.gz` + sessions + journal |
| `anomalies.py` | Les 11 anomalies du PDF (D01 à D11) : injection et mesure |
| `insert_data.py` | Recrée la collection, charge par lots de 10 000 (`bypass_document_validation`) |
| `verify_source.py` | Porte G1 : **30 contrôles** sur ta base (27 sans serveur) |

## 2. Exécution

```powershell
python -m common.referential                 # si pas déjà fait
python -m sources.s4_mongodb.generate_data   # ~30 s (recalcule MySQL et PostgreSQL en mémoire)
python -m sources.s4_mongodb.insert_data     # ~30 s, conteneur mongo démarré
python -m sources.s4_mongodb.verify_source   # ~30 s -> data/reports/s4_mongodb_G1.md
```

`create_source.py` est appelé automatiquement par `insert_data`. On peut aussi le lancer
seul (`python -m sources.s4_mongodb.create_source`) pour créer une collection vide.

## 3. Structure du document

18 champs, conformément au PDF (`_id` ObjectId attribué par MongoDB, `event_id` = identifiant métier) :

```json
{
  "event_id": "…uuid…", "student_code": "LMS-008085", "timestamp": ISODate("2023-10-02T19:22:10"),
  "event_type": "QUIZ_SUBMITTED",
  "module_code": "MOD-IA-38", "course_code": "COURSE-287", "quiz_code": "QUIZ-354",
  "device": "iPhone SE (2022)", "operating_system": "iOS", "app_version": "2.0.0",
  "ip_address": "210.34.176.232", "city": "Ziguinchor", "country": "Sénégal",
  "session_id": "…uuid…", "duration_seconds": 1622, "success": true,
  "metadata": { "network": "4G", "score": 5.99, "attempt": 1 }
}
```

### Schéma flexible (PDF : « les documents n'ont pas tous la même structure »)

| Type d'événement | Champs de contexte | Métadonnées spécifiques (+ `network` partout) |
|---|---|---|
| LOGIN / LOGOUT | — | `method` (LOGIN) |
| COURSE_OPENED / COURSE_COMPLETED | module_code, course_code | `progress` |
| VIDEO_STARTED | module_code, course_code | **`video_quality`, `buffer_time`** (PDF) |
| VIDEO_FINISHED | module_code, course_code | `watched_percent` |
| QUIZ_STARTED | module_code, course_code, quiz_code | `attempt` |
| QUIZ_SUBMITTED | module_code, course_code, quiz_code | **`score`, `attempt`** (PDF) |
| RESOURCE_DOWNLOADED | module_code, course_code | `resource_type`, `size_mb` |
| SEARCH | — | `query`, `results_count` |
| PROFILE_UPDATED | — | `field` |
| PAYMENT_STARTED / SUCCESS / FAILED | — | `amount`, `currency`, `method`, `reference`, `tranche` (+ `error`) |

Un LOGIN **sans** `quiz_code` est normal : c'est le schéma flexible, pas une anomalie.

### Sessions

Chaque événement appartient à une session (règle du PDF). Une session suit la forme
`LOGIN → activités → LOGOUT`, et 10 % des sessions n'ont pas de LOGOUT (application fermée).
Une session appartient à un seul étudiant.

## 4. Contraintes : le validateur, équivalent de NOT VALID

| | PostgreSQL | MySQL | **MongoDB** |
|---|---|---|---|
| Mécanisme | `CHECK … NOT VALID` | `CHECK … NOT ENFORCED` | `$jsonSchema`, `validationLevel: moderate`, `validationAction: error` |
| Chargement des anomalies | Contrainte ajoutée après insertion | Contrainte non appliquée | `bypass_document_validation=True` |
| Documents existants | Non vérifiés | Non vérifiés | Non vérifiés |
| **Nouveaux documents** | **Vérifiés** | Non vérifiés | **Vérifiés** (erreur 121) |

Le validateur exige les 14 champs standard, avec leurs types :
- `timestamp` doit être une date ;
- `operating_system` doit valoir `Android` ou `iOS` ;
- `app_version` doit suivre le format `X.Y.Z` ;
- `duration_seconds` doit être un entier ≥ 0.

**Contrôle du validateur lui-même.** La porte G1 compare le nombre de documents rejetés
par MongoDB (`{$nor: [validateur]}`) et par `violates_schema()` en Python. S'ils diffèrent,
le validateur est mal écrit. C'est ainsi qu'il est vérifié sur ta base, puisque je n'ai pas
pu disposer d'un serveur MongoDB.

**Index :** `event_id` (**non unique** : doublons D09), `(student_code, timestamp)`,
`session_id`, `event_type`, `timestamp`.

## 5. Anomalies volontaires : les 11 du PDF

Chaque document reçoit **au plus une** anomalie : la mesure est exacte.
Journal : `data/anomalies/s4_mongodb_anomalies.csv`, jamais lu par l'ETL.

| Code | Anomalie du PDF | Mise en œuvre | Exemple | Nb | Taux | Détectée par le validateur |
|---|---|---|---|---:|---:|:-:|
| D01 | Documents incomplets | Document tronqué : seuls les identifiants et le contexte restent | 9 champs absents | 12 868 | 4,51 % | ✅ |
| D02 | Champs absents | Un champ standard supprimé | `city` absent | 13 003 | 4,56 % | ✅ |
| D03 | Valeurs nulles | Un champ standard à `null` | `"device": null` | 5 998 | 2,10 % | ✅ |
| D04 | Villes écrites différemment | | `DAKAR`, `dakarr`, `THIÈS`, `Mbour ` | 7 590 | 2,66 % | ❌ |
| D05 | Versions incohérentes | | `2.4`, `v2.4`, `2.4.1.0` | 7 349 | 2,57 % | ✅ |
| D06 | OS écrits différemment | | `ANDROID`, `android`, `IOS` | 9 322 | 3,27 % | ✅ |
| D07 | Événements sans student_code | Champ absent (50 %) ou `null` (50 %) | | 8 606 | 3,02 % | ✅ |
| D08 | Dates dans plusieurs formats | Texte ou nombre au lieu d'une date | `"12/09/2026 08:25:14"`, `1757665514000` | 6 312 | 2,21 % | ✅ |
| D09 | Événements dupliqués | Même contenu, même `event_id`, autre `_id` | | 12 164 | 4,26 % | ❌ |
| D10 | Adresses IP invalides | | `312.4.8.1`, `unknown` | 6 521 | 2,28 % | ❌ |
| D11 | Durées négatives | | `-780` | 11 849 | 4,15 % | ✅ |

**Total : 101 582 anomalies.** Les exemples exacts du PDF (`DAKAR`, `dakarr`, `2.4`, `v2.4`,
`ANDROID`, `android`) sont **garantis**.

Trois anomalies (D04, D09, D10) **ne sont pas détectables par un schéma**. Seul un contrôle
qualité métier les trouvera : c'est un argument pour la Phase 5.

## 6. Cohérence avec les autres sources

| Lien | Mécanisme | Vérifié par G1 |
|---|---|---|
| Comptes LMS | Les 9 500 comptes (dont les 500 orphelins) ; les étudiants SANS_LMS n'utilisent pas l'application | ✅ 9 500 |
| Notes MySQL | 8 % des notes (propres) sont passées sur mobile : même quiz, score, tentative et horodatage que `notes` | Par construction |
| Paiements PostgreSQL | 60 % des paiements Orange Money et Wave (VALIDE ou ECHOUE) passent par l'application ; même référence `PAY-…` et même montant | ✅ 13 783/13 783 références |
| Codes de contenus | `MOD-XXX-NN`, `COURSE-n`, `QUIZ-n` du référentiel caché ; **89 codes (5 %) absents de `mapping_courses.csv`** | ✅ |
| Fenêtre d'activité | Celle de MySQL (rentrée d'entrée → diplôme, abandon ou 15/09/2026) | ✅ |
| Redis (L2-e) | 51 711 sessions dans `data/referential/sessions_mobile.csv` (caché), dont **700 ouvertes** le 15/09/2026 à partir de 20 h, sans LOGOUT | ✅ |

**Point de vigilance pour le chiffre d'affaires :** les paiements existent **dans deux sources**
(PostgreSQL et événements `PAYMENT_SUCCESS`). La source de référence reste PostgreSQL ;
MongoDB ne sert qu'au rapprochement, pour éviter le double comptage.

## 7. Conventions et écarts assumés

| # | Sujet | Choix | Justification |
|---|---|---|---|
| S4-01 | Timestamp | Type date BSON (PDF : « DateTime ») ; l'exemple JSON du PDF n'en est que la représentation texte | D08 = timestamp en texte ou en nombre |
| S4-02 | Codes | `QUIZ-354` et non `QUIZ-03` : l'exemple du PDF est zéro-paddé ; la convention validée C21 est `QUIZ-n` | Un seul format canonique |
| S4-03 | Appareils | Modèles répandus au Sénégal (Tecno, Infinix, Itel, Samsung, iPhone…) ; OS Android 78 % / iOS 22 % ; 10 % des sessions sur un second appareil | Réalisme |
| S4-04 | Versions | 8 versions, de 2.0.0 (sept. 2023) à 2.4.1 (mars 2026) ; 25 % des sessions sur la version précédente | L'exemple du PDF est 2.4.1 |
| S4-05 | Ville | Ville de l'étudiant (référentiel), 8 % d'une autre ville (déplacement) | Cohérence avec PostgreSQL |
| S4-06 | IP | Faker `ipv4_public`, une par session | |
| S4-07 | Réseau | `metadata.network` : 4G 60 %, WiFi 25 %, 3G 15 % | Exemple du PDF |
| S4-08 | Volume | 8 % des notes, 60 % des paiements via l'application, 1 à 2 sessions de consultation par compte | Calibré sur ~300 000 |
| S4-09 | Sessions ouvertes | 700 sessions le 15/09/2026 au soir, sans LOGOUT | **Préparation de Redis (L2-e)** : `session:{session_id}` pointera vers ces sessions |
| S4-10 | Fichier | JSON étendu MongoDB (dates `$date`), compressé gzip (16 Mo), octet pour octet reproductible | 300 000 documents |

## 8. Volumes obtenus (graine 2026)

**297 601 événements** (cible ~300 000, −0,8 % ; PDF : 200 000 à 500 000), répartis en
**51 711 sessions** : 46 022 fermées, 4 989 sans LOGOUT, 700 ouvertes.

| Type | Nb | Type | Nb |
|---|---:|---|---:|
| LOGIN | 55 995 | QUIZ_SUBMITTED | 23 999 |
| LOGOUT | 47 916 | RESOURCE_DOWNLOADED | 10 963 |
| COURSE_OPENED | 36 615 | SEARCH | 14 799 |
| COURSE_COMPLETED | 5 396 | PROFILE_UPDATED | 1 826 |
| VIDEO_STARTED | 27 776 | PAYMENT_STARTED | 14 387 |
| VIDEO_FINISHED | 19 526 | PAYMENT_SUCCESS | 14 028 |
| QUIZ_STARTED | 23 994 | PAYMENT_FAILED | 381 |

## 9. Porte G1 : 30 contrôles

| Groupe | Contrôles |
|---|---|
| V1 Volume | ±5 % de 300 000 et dans l'intervalle du PDF |
| V2 Anomalies | 11 types : mesure en base = journal, taux dans [2 %, 5 %] |
| V3 Structure | Validateur (moderate / error), index, **MongoDB = Python** sur les documents invalides, 14 types, schéma flexible (3 règles du PDF) |
| V4 Règles métier | Session pour chaque événement, un étudiant par session, un LOGIN par session, rien après le 15/09/2026 |
| V5 Inter-sources | 9 500 comptes, codes connus, codes hors mapping, références PostgreSQL, payeurs inscrits, sessions = fichier caché, 700 sessions ouvertes |

## 10. Tests

| Fichier | Portée |
|---|---|
| `tests/test_s4_mongodb.py` | 14 tests sans serveur : anomalies et taux, exemples du PDF, validateur (documents propres valides, anomalies détectées), schéma flexible, sessions, fichier reproductible, insertion avec **mongomock**, reproductibilité |
| `tests/test_s4_mongodb_integration.py` | 8 tests sur **ta** base : G1, document valide accepté, **5 documents invalides refusés** (erreur 121), rechargement idempotent |

```powershell
$env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s4_mongodb_integration.py -v
```

> ⚠️ **Limite des tests effectués.** Aucun serveur MongoDB n'était disponible dans
> l'environnement de développement (téléchargement bloqué). Génération, anomalies, fichier,
> logique d'insertion (mongomock) et 27 des 30 contrôles G1 ont été testés. Le validateur
> `$jsonSchema`, les index réels et le refus des documents invalides seront validés **par le
> test d'intégration, sur ta machine**.
