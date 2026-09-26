# Source 3 — CSV « Ressources humaines »

Aucun serveur : le service RH exporte des fichiers CSV (PDF Source 3).
Fichiers livrés dans `sources/s3_csv/output/`.

Ce document est le **document de présentation** exigé par le cadrage (Données
EduSmart.pdf, livrable 5) : structure, relations internes, contraintes,
anomalies introduites volontairement et volume généré. Le détail colonne par
colonne se trouve dans [`dictionnaire_donnees.md`](dictionnaire_donnees.md).

---

## 1. Fichiers livrés

| Fichier | Rôle |
|---|---|
| `create_source.py` | `SCHEMAS` : structure des 4 fichiers (colonnes, types et contraintes du PDF, encodage, séparateur). Crée `output/` et génère le dictionnaire de données |
| `dictionnaire_donnees.md` | Description des fichiers (livrable « Description des fichiers CSV et de leur structure ») |
| `generate_data.py` | Génération des données propres, puis des anomalies ; écriture des 4 fichiers + journal |
| `anomalies.py` | 19 types d'anomalies (C01 à C19) + `parse_date()` et `normalize_mois()`, réutilisables par l'ETL |
| `verify_source.py` | Porte G1 : 50 contrôles, en relisant les fichiers comme l'ETL |
| `output/*.csv` | **Les 4 fichiers générés** (versionnés : c'est un livrable) |

Pas de `insert_data.py` : le PDF précise « si nécessaire », et les fichiers **sont** la source.

## 2. Exécution

```powershell
python -m common.referential                   # si pas déjà fait (L1)
python -m sources.s3_csv.create_source         # structure + dictionnaire
python -m sources.s3_csv.generate_data         # ~2 s -> sources/s3_csv/output/
python -m sources.s3_csv.verify_source         # porte G1 -> data/reports/s3_csv_G1.md
```

Aucun conteneur Docker n'est nécessaire pour cette source.

## 3. Structure, encodages et relations

| Fichier | Lignes | Encodage | Séparateur | Clé |
|---|---:|---|:-:|---|
| enseignants.csv | 124 | UTF-8 | `,` | teacher_code (UNIQUE) |
| departements.csv | 12 | UTF-8 | `,` | id_departement |
| salaires.csv | 4 192 | **ISO-8859-1** | `;` | id_salaire ; teacher_code = FK *logique* |
| absences.csv | 2 493 | **ISO-8859-1** | `;` | id_absence ; teacher_code = FK *logique* |

```
enseignants (teacher_code) 1──< salaires     (FK logique : aucun système ne la contrôle)
                           1──< absences
departements : AUCUN lien avec enseignants dans le PDF (ni colonne département, ni affectation)
```

Tous les fichiers ont des fins de ligne **CRLF**, comme un export Excel sous Windows.

**Conventions d'écriture des valeurs propres :**
- dates `AAAA-MM-JJ` ;
- booléens `Oui` / `Non` (le PDF décrit `justifiee` comme « Oui / Non ») ;
- montants en XOF, avec un point décimal ;
- valeur absente = champ vide.

**Deux limites du PDF, signalées dès l'Étape 1 et conservées telles quelles :**
- le fichier « affectations » est mentionné, mais jamais décrit ;
- `departements.csv` n'est relié à aucun enseignant.

Rien n'a été inventé pour combler ces trous.

## 4. Cohérence avec les autres sources

| Lien | Mécanisme | Vérifié par G1 |
|---|---|---|
| Enseignants ↔ vivier commun (C18) | Les 120 enseignants `ENS-0001` à `ENS-0120` sont ceux du vivier, avec les mêmes noms | ✅ 120/120 |
| Enseignants ↔ PostgreSQL | Les 82 responsables de classe de la Source 1 existent dans `enseignants.csv`, **par le nom seulement** (texte libre dans PostgreSQL) | ✅ 82/82 |
| Dates d'embauche ↔ PostgreSQL | Un responsable de classe est en poste dès la rentrée de sa classe : seuls les enseignants qui ne sont responsables d'aucune classe peuvent être embauchés pendant la période | ✅ 0 incohérence |
| Spécialité ↔ département | La spécialité découle du département du vivier (ex. Data → « Science des Données ») | ✅ |
| Départements ↔ PostgreSQL | Les 8 noms canoniques sont ceux de `filieres.departement` | ✅ 8/8 |

## 5. Anomalies volontaires

Journal : `data/anomalies/s3_csv_anomalies.csv`, **jamais lu par l'ETL**.

| Code | Fichier.colonne | Anomalie | Exemple | Nb (graine 2026) | Taux |
|---|---|---|---|---:|---:|
| C01 | enseignants.telephone | Téléphone mal formaté | `77-123-45-67`, `77 123 45`, `221 771234567` | 6 | 5,00 % |
| C02 | enseignants.email | E-mail manquant | vide | 5 | 4,17 % |
| C03 | enseignants.specialite | Spécialité écrite différemment | `IA`, `Data Science`, `I.A.` | 3 | 2,50 % |
| C04 | enseignants.grade | Grade hors référentiel | `Prof.`, `Maître Assistant`, `MC` | 4 | 3,33 % |
| C05 | enseignants.date_naissance | Format JJ/MM/AAAA ou MM-JJ-AAAA | `15/08/1985`, `08-15-1985` | 6 | 5,00 % |
| C06 | enseignants.date_embauche | Idem | — | 3 | 2,50 % |
| C07 | enseignants | Ligne dupliquée (identique) | — | 4 | 3,33 % |
| C08 | departements.nom_departement | Même département, autre écriture | `Développement Data`, `Data Engineering` | 4 / 12 | fixe |
| C09 | departements.budget_annuel | Budget manquant | vide | 2 / 12 | fixe |
| C10 | salaires.salaire_net | Salaire négatif | `-627000.00` | 151 | 3,77 % |
| C11 | salaires.primes | Primes supérieures au salaire de base (net non recalculé) | `1850000.00` pour une base de 686 000 | 118 | 2,95 % |
| C12 | salaires | Ligne dupliquée (identique, même id) | — | 189 | 4,72 % |
| C13 | salaires.mode_paiement | Écriture variable | `Virement`, `Banque`, `bank transfer` | 97 | 2,42 % |
| C14 | salaires.mois | Mois mal orthographié ou autre format | `AOÛT`, `Fevrier`, `03`, `Sept.` | 194 | 4,85 % |
| C15 | absences | Ligne dupliquée | — | 102 | 4,27 % |
| C16 | absences.motif | Absence sans motif | vide | 75 | 3,14 % |
| C17 | absences.date_absence | Date incohérente | avant l'embauche, ou après le 15/09/2026 | 108 | 4,52 % |
| C18 | absences.duree_heures | Durée très élevée | `41`, `650` (heures, pour un jour) | 106 | 4,43 % |
| C19 | absences.date_absence | Format JJ/MM/AAAA ou MM-JJ-AAAA | `02/05/2024`, `05-02-2024` | 96 | 4,02 % |

**Total : 1 273 anomalies.** Il faut y ajouter les anomalies **de format** propres aux
fichiers, qui s'appliquent à la totalité de certains fichiers : encodage ISO-8859-1
(salaires, absences), séparateur `;`, fins de ligne CRLF.

**Choix de conception des anomalies :**
- **Doublons = lignes strictement identiques**, même identifiant (C07, C12, C15). C'est typique d'un export lancé deux fois. Chaque copie suit directement sa ligne d'origine.
- **C10 et C11 cassent la formule** `net = base + primes - retenues`. G1 vérifie qu'il y a exactement 151 + 118 = 269 écarts.
- **C08 et C09 sont fixes** : 12 lignes ne permettent pas un taux de 2 à 5 % (même principe que A07 en Source 1).
- **Ambiguïté des dates.** `03-04-2024` peut se lire 3 avril ou 4 mars. `parse_date()` s'appuie sur la convention du PDF : l'année en tête signifie ISO, le séparateur `/` signifie JJ/MM/AAAA, et le séparateur `-` avec l'année en fin signifie MM-JJ-AAAA. L'ETL devra documenter cette hypothèse.

## 6. Conventions et écarts assumés

| # | Sujet | Choix | Justification |
|---|---|---|---|
| S3-01 | Spécialités | Une canonique par département ; « IA » et « Intelligence Artificielle » → famille IA ; « Data Science » → famille Data (« Science des Données ») | Le PDF cite les trois termes ; « Data Science » n'est pas une écriture de « IA » |
| S3-02 | Booléens | `Oui` / `Non` | Description du PDF (« Oui / Non ») |
| S3-03 | Salaires | Octobre 2023 à **août 2026** (35 mois) | Le salaire de septembre n'est pas versé au 15/09/2026 (C20) |
| S3-04 | Montants | Base selon le grade (Assistant 450 à 600 k, Professeur 1,3 à 1,8 M XOF), +3 % chaque janvier ; primes 0 ou 5 à 15 % ; retenues 8 à 18 % ; vacataires 150 à 400 k, variables | Réalisme |
| S3-05 | Grades | Permanents selon l'âge ; vacataires sans grade (70 %) ou ASSISTANT | Liste validée ; le PDF autorise un grade NULL |
| S3-06 | E-mails | `prenom.nom@edusmart.sn` (adresse institutionnelle) | Format non spécifié |
| S3-07 | Départements | 8 canoniques (ids 1 à 8) + 4 variantes (ids 9 à 12) ; responsable = enseignant au grade le plus élevé du département | ~12 lignes validées |
| S3-08 | Mois | Nom français (`Février`, `Août`) | Les accents rendent l'encodage ISO-8859-1 visible |
| S3-09 | Mode de paiement | Canoniques : `Virement bancaire`, `Wave`, `Orange Money`, `Espèces` | PDF : « Banque, Wave... » |
| S3-10 | Absences | 0, 1 ou 2 par mois, un jour ouvré, 2 à 8 h | ~2 500 validées |
| S3-11 | Embauches pendant la période | Réservées aux enseignants non responsables de classe (20 % d'entre eux) | Évite une incohérence non voulue avec PostgreSQL |
| S3-12 | Encodage strict | L'écriture échoue si un caractère n'existe pas en ISO-8859-1 (jamais de `?` silencieux) | Qualité : un test le vérifie |

## 7. Porte G1

`verify_source.py` exécute **50 contrôles** :

| Groupe | Contrôles |
|---|---|
| V1 Volumes | 4 fichiers (departements exact, les autres à ±5 %) |
| V2 Anomalies | 19 types : mesure dans les fichiers = journal, taux dans [2 %, 5 %] sauf C08 et C09 |
| V3 Format | Pour chaque fichier : en-tête conforme au PDF, nombre de champs constant, CRLF, encodage réel (ISO-8859-1 illisible en UTF-8) |
| V4 Règles métier | FK logiques, un salaire par mois hors C12, formule du net (écarts = C10 + C11), mois et dates lisibles dans les 3 formats |
| V5 Inter-sources | Vivier commun, noms identiques, 82/82 responsables PostgreSQL retrouvés, responsables en poste à la rentrée, 8 départements |

## 8. Tests

`tests/test_s3_csv.py` contient **32 tests**, sans base : données propres, vivier commun,
règles des salaires et des absences, anomalies et taux, exemples du PDF, doublons
identiques, encodages et séparateurs réels, relecture des fichiers, rejet d'un
caractère hors ISO-8859-1, reproductibilité octet pour octet, `parse_date()` et
`normalize_mois()`.
