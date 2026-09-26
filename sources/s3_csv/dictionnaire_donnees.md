# Dictionnaire de données — Source 3 : CSV Ressources humaines

*Généré par `python -m sources.s3_csv.create_source` à partir de `SCHEMAS`. Ne pas modifier à la main.*

Le service RH ne possède pas de base de données : il exporte des fichiers CSV (PDF Source 3). Les fichiers sont **indépendants** : les liens `teacher_code` sont des clés étrangères *logiques*, qu'aucun système ne contrôle.

| Fichier | Encodage | Séparateur | Colonnes |
|---|---|:-:|---:|
| `enseignants.csv` | UTF-8 | `,` | 11 |
| `departements.csv` | UTF-8 | `,` | 5 |
| `salaires.csv` | ISO-8859-1 | `;` | 9 |
| `absences.csv` | ISO-8859-1 | `;` | 7 |

**Conventions d'écriture des valeurs (fichiers propres) :**
- dates au format `AAAA-MM-JJ` ;
- booléens `Oui` / `Non` ;
- montants en XOF avec deux décimales et un point décimal ;
- valeur absente = champ vide ;
- fins de ligne Windows (CRLF), comme un export Excel.

## enseignants.csv

Informations générales des enseignants.

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `teacher_code` | VARCHAR(20) | UNIQUE | Identifiant RH |
| `nom` | VARCHAR(100) | NOT NULL | Nom |
| `prenom` | VARCHAR(100) | NOT NULL | Prénom |
| `sexe` | CHAR(1) | CHECK (M,F) | Sexe |
| `date_naissance` | DATE | NOT NULL | Date de naissance |
| `telephone` | VARCHAR(20) | NULL | Téléphone |
| `email` | VARCHAR(150) | NULL | Adresse e-mail |
| `specialite` | VARCHAR(100) | NOT NULL | Domaine |
| `grade` | VARCHAR(50) | NULL | Assistant, Maître Assistant... |
| `date_embauche` | DATE | NOT NULL | Date d'embauche |
| `statut` | VARCHAR(30) | NOT NULL | Permanent, Vacataire |

**Règles métier :** Un enseignant possède un code unique. Deux enseignants peuvent avoir le même nom. L'adresse e-mail peut être absente.

## departements.csv

Liste des départements auxquels appartiennent les enseignants.

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id_departement` | INTEGER | PRIMARY KEY | Identifiant |
| `nom_departement` | VARCHAR(100) | UNIQUE | Département |
| `responsable` | VARCHAR(150) | NULL | Responsable |
| `budget_annuel` | DECIMAL(12,2) | >= 0 | Budget |
| `batiment` | VARCHAR(50) | NULL | Localisation |

**Règles métier :** Un département possède un nom unique. Le budget doit être positif.

## salaires.csv

Historique des paiements des enseignants.

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id_salaire` | INTEGER | PRIMARY KEY | Identifiant |
| `teacher_code` | VARCHAR(20) | FOREIGN KEY logique | Enseignant |
| `mois` | VARCHAR(20) | NOT NULL | Mois |
| `annee` | INTEGER | NOT NULL | Année |
| `salaire_base` | DECIMAL(12,2) | >= 0 | Salaire |
| `primes` | DECIMAL(12,2) | >= 0 | Primes |
| `retenues` | DECIMAL(12,2) | >= 0 | Retenues |
| `salaire_net` | DECIMAL(12,2) | >= 0 | Salaire final |
| `mode_paiement` | VARCHAR(30) | NULL | Banque, Wave... |

**Règles métier :** Un enseignant reçoit un salaire par mois. Le salaire net est calculé.

## absences.csv

Historique des absences des enseignants.

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id_absence` | INTEGER | PRIMARY KEY | Identifiant |
| `teacher_code` | VARCHAR(20) | FOREIGN KEY logique | Enseignant |
| `date_absence` | DATE | NOT NULL | Date |
| `motif` | VARCHAR(100) | NULL | Motif |
| `justifiee` | BOOLEAN | NULL | Oui / Non |
| `duree_heures` | INTEGER | >= 0 | Durée |
| `remplace` | BOOLEAN | NULL | Remplacement effectué |

**Règles métier :** Une absence appartient à un enseignant. La durée est positive.
