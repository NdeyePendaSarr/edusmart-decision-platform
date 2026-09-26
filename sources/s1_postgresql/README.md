# Source 1 — PostgreSQL « Gestion académique »

Base : `edusmart_academic` · Conteneur : `edusmart_pg_source` (port Windows 5435)

Ce document est le **document de présentation** exigé par le cadrage (Données
EduSmart.pdf, livrable 5) : structure, relations internes, contraintes,
anomalies introduites volontairement et volume généré.

---

## 1. Fichiers livrés

| Fichier | Rôle |
|---|---|
| `create_database.sql` | Création des 5 tables : clés primaires, UNIQUE et NOT NULL non concernés par les anomalies |
| `add_constraints.sql` | CHECK et FOREIGN KEY ajoutés **après** insertion (`NOT VALID`) |
| `check_constraints.sql` | Diagnostic en lecture seule des violations, réutilisé en Phase 15 |
| `generate_data.py` | Génération des données propres, puis des anomalies ; export CSV + journal |
| `anomalies.py` | Catalogue, injection et **mesure** des 16 types d'anomalies |
| `insert_data.py` | Chargement par `COPY` en une transaction, puis ajout des contraintes |
| `verify_source.py` | Porte G1 : 39 contrôles directement en base + rapport Markdown |

Modules communs créés pour cette source et réutilisés ensuite :
`common/academic_catalog.py` (départements, filières, vivier d'enseignants) et
`common/anomaly_journal.py` (journal d'anomalies).

## 2. Exécution

```powershell
python -m common.referential                    # si pas déjà fait (L1)
python -m sources.s1_postgresql.generate_data   # ~2 s, aucun besoin de Docker
python -m sources.s1_postgresql.insert_data     # ~2 s, pg_source démarré
python -m sources.s1_postgresql.verify_source   # porte G1 -> data/reports/s1_postgresql_G1.md
```

Diagnostic SQL (dans Adminer, onglet « Requête SQL », ou avec psql) : `check_constraints.sql`.

Le rechargement est **idempotent** : `insert_data` supprime puis recrée les tables.

## 3. Structure et relations

```
filieres (25) 1 ──< N classes (150) 1 ──< N inscriptions (~17 600) N >── 1 etudiants (10 000)
                                                   1
                                                   │
                                                   N
                                             paiements (~40 000)
```

| Table | Clé primaire | Clés étrangères | UNIQUE |
|---|---|---|---|
| etudiants | id_etudiant (UUID) | — | matricule, email |
| filieres | id_filiere (UUID) | — | code_filiere |
| classes | id_classe (UUID) | id_filiere → filieres | code_classe |
| inscriptions | id_inscription (UUID) | id_etudiant → etudiants ; id_classe → classes | — |
| paiements | id_paiement (UUID) | id_inscription → inscriptions | reference *(documentée, non posée)* |

Toutes les colonnes, types, valeurs par défaut et commentaires suivent le PDF.
Les seuls écarts sont listés au § 6.

## 4. Contraintes : stratégie « insertion puis NOT VALID »

| Contrainte | Règle du PDF | État après chargement | Pourquoi |
|---|---|---|---|
| ck_etudiants_sexe | sexe ∈ {M, F} | **NOT VALID** | Anomalie A01 |
| ck_inscriptions_reduction | réduction entre 0 et 100 | **NOT VALID** | Anomalie A11 |
| ck_paiements_montant | montant ≥ 0 | **NOT VALID** | Anomalie A14 |
| fk_paiements_inscription | paiement → inscription | **NOT VALID** | Anomalie A16 |
| uq_paiements_reference | référence unique | **Non posée** (index simple) | Anomalie A13 ; UNIQUE ne peut pas être NOT VALID |
| ck_etudiants_date_naissance | naissance < aujourd'hui | Validée | Aucune anomalie prévue |
| ck_filieres_duree / ck_filieres_cout | durée > 0, coût ≥ 0 | Validées | Idem |
| ck_classes_capacite | capacité > 0 | Validée | Idem |
| fk_classes_filiere, fk_inscriptions_etudiant, fk_inscriptions_classe | intégrité | Validées | Idem |

`NOT VALID` signifie que les lignes existantes ne sont pas vérifiées, mais que
**toute nouvelle ligne l'est**. Ce comportement est prouvé par le test
d'intégration : insérer un montant négatif est refusé.

## 5. Anomalies volontaires

Chaque type touche entre 2 % et 5 % de sa table, sauf A07 qui est fixé par le catalogue.
Chaque anomalie est consignée dans `data/anomalies/s1_postgresql_anomalies.csv`
(code, table, colonne, identifiant, valeur avant, valeur après). Ce journal est une
vérité terrain réservée à la vérification : **le pipeline ETL ne le lit jamais**.

| Code | Table.colonne | Anomalie | Exemple | Nb (graine 2026) | Taux |
|---|---|---|---|---:|---:|
| A01 | etudiants.sexe | Sexe non standard | `Homme`, `Fille`, `1`, `0` | 487 | 4,87 % |
| A02 | etudiants.telephone | Téléphone manquant | NULL | 303 | 3,03 % |
| A03 | etudiants.telephone | Format non standard | `771234567`, `00221771234567` | 419 | 4,19 % |
| A04 | etudiants.adresse | Adresse manquante | NULL | 472 | 4,72 % |
| A05 | etudiants.ville | Erreur de saisie | `DAKAR`, `thiès`, ` Mbour `, `THIES` | 426 | 4,26 % |
| A06 | etudiants.nom | Erreur de saisie (casse) | `DIOP`, `ndiaye` | 239 | 2,39 % |
| A07 | filieres.nom_filiere | Libellés IA incohérents | `IA`, `Ingénierie IA` | 2 / 25 | fixe |
| A08 | classes.salle | Écriture de salle | `Salle A101`, `A-101` | 7 | 4,67 % |
| A09 | classes.annee_academique | Format d'année | `2023/2024`, `23-24`, `2023-24` | 6 | 4,00 % |
| A10 | inscriptions | Doublon (nouvel id, même contenu) | — | 366 | 2,13 % |
| A11 | inscriptions.reduction | Réduction > 100 % | `137.52` | 541 | 3,15 % |
| A12 | inscriptions.date_inscription | Inscription après la rentrée | 2024-11-20 pour 2024-2025 | 759 | 4,42 % |
| A13 | paiements.reference | Référence dupliquée | 2 paiements, même référence | 1 179 | 3,07 % |
| A14 | paiements.montant | Montant négatif | `-350000.00` | 1 700 | 4,43 % |
| A15 | paiements.mode_paiement | Écriture du mode | `OM`, `orange money`, `WAVE`, `Especes` | 1 595 | 4,16 % |
| A16 | paiements.id_inscription | Paiement orphelin | UUID inexistant | 1 778 | 4,63 % |

**Total : 10 279 anomalies journalisées.** Chacune est recomptée en base par
`verify_source.py`, et la mesure est égale au journal pour les 16 types.

## 6. Conventions et écarts assumés

| # | Sujet | Choix | Justification |
|---|---|---|---|
| S1-01 | `sexe` | VARCHAR(10) au lieu de CHAR(1) | Validé (Étape 1, Q7) : « Homme » ne tient pas en CHAR(1) |
| S1-02 | `reference` UNIQUE | Documentée, non posée ; index simple | PostgreSQL n'accepte pas de UNIQUE NOT VALID |
| S1-03 | Anomalies A05, A06, A09 | Ajoutées au titre des « Contraintes générales » du PDF | Erreurs de saisie et formats de dates. Les colonnes DATE ne peuvent pas porter de format : c'est le champ texte `annee_academique` qui porte l'anomalie de format |
| S1-04 | Classes | 25 filières × 3 années × 2 groupes (A, B) ; toutes les années d'un parcours dans la classe de la filière | Volume validé (150) ; simplification : pas de classe par niveau L1/L2/L3 |
| S1-05 | Capacité | 30 minimum, supérieure à l'effectif réel (+5 à +30 %) | Formation en ligne ; aucun sureffectif n'est demandé par le PDF |
| S1-06 | Responsable de classe | Nom d'un enseignant du vivier commun (même département) | Rapprochement enseignant ↔ formation possible **par le nom seulement** (Source 3) |
| S1-07 | Statuts d'inscription | INSCRIT = année intermédiaire achevée ; EN_COURS = 2025-2026 ; DIPLOME = dernière année ; ABANDON 6 %/an ; SUSPENDU 2 %/an | Liste validée ; sémantique fixée ici |
| S1-08 | Paiements | Frais annuels = coût total / nb d'années, après réduction, arrondis à 500 XOF ; 1, 2 ou 3 tranches (oct., janv., avril) ; 3 % d'échecs suivis d'une nouvelle tentative ; remboursements sur abandons | Réalisme ; bourse à 100 % = aucun paiement |
| S1-09 | Références | `PAY-AAAA-NNNNNN`, chronologiques | Format non spécifié par le PDF |
| S1-10 | Période | Inscriptions dès juin, avant la rentrée ; 1er paiement dans les 10 jours | Les paiements de juin à septembre 2023 relèvent de l'année 2023-2024 |
| S1-11 | Adresses | `Villa/Lot/Maison n° X, Quartier` (quartiers dakarois pour la région de Dakar) | Faker fr_FR produit des adresses françaises |
| S1-12 | Faker | Horodatage `date_creation` (dans le mois précédant la 1ʳᵉ inscription) | Complété par les listes sénégalaises (L1) |

## 7. Volumes obtenus (graine 2026)

| Table | Lignes | Cible validée |
|---|---:|---|
| etudiants | 10 000 | 10 000 |
| filieres | 25 | 25 |
| classes | 150 | ~150 |
| inscriptions | 17 557 (dont 366 doublons) | ~18 000 (−2,5 %) |
| paiements | 40 150 (dont 1 778 orphelins) | ~40 000 (+0,4 %) |

**Répartitions :**
- Statuts d'inscription : INSCRIT 6 818, EN_COURS 6 235, DIPLOME 3 039, ABANDON 1 097, SUSPENDU 368.
- Niveaux : Licence 50 %, Master 30 %, Certificat 20 %.
- Paiements : VALIDE 38 561, ECHOUE 1 046, REMBOURSE 311, EN_ATTENTE 232.

## 8. Porte G1

`verify_source.py` exécute **39 contrôles** directement en base :

| Groupe | Contrôles |
|---|---|
| V1 Volumes | 5 tables, exactes ou à ±5 % |
| V2 Anomalies | 16 types : mesure en base = journal, taux dans [2 %, 5 %] |
| V3 Contraintes | 4 NOT VALID + 7 validées, lues dans `pg_constraint` |
| V4 Relations | Aucun orphelin, sauf les paiements A16 ; chaque étudiant a au moins une inscription |
| V5 Référentiel | Les étudiants en base sont exactement ceux du référentiel ; les 9 000 matricules du mapping existent |

## 9. Tests

| Fichier | Portée |
|---|---|
| `tests/test_s1_postgresql.py` | 19 tests sans base : données propres, anomalies, taux, reproductibilité octet pour octet, CSV |
| `tests/test_s1_postgresql_integration.py` | 3 tests sur une vraie base : G1, rechargement idempotent, blocage des nouvelles lignes invalides |
| `tests/test_academic_catalog.py`, `tests/test_anomaly_journal.py` | Modules communs |

Le test d'intégration est désactivé par défaut, car il **recharge la base**. Pour l'activer :

```powershell
$env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s1_postgresql_integration.py
```
