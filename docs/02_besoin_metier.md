# Phase 2 — Comprendre le besoin métier

*EduSmart Decision Platform · Lot L3 · Étape 1 du module BI*

> **Objectif du PDF :** apprendre qu'un projet BI commence toujours par le **métier**, et non par la technologie.
>
> La Phase 1 a montré que les données d'EduSmart peuvent produire des chiffres très différents selon la règle appliquée : de 12,9 à 14,2 Mds XOF de CA, de 10 500 à 26 476 « étudiants ». **Choisir la règle n'est pas une décision technique** : c'est l'objet de cette phase.

---

## Recherche

### 1. Qu'est-ce qu'un besoin métier ?

Un **besoin métier** exprime ce qu'un acteur de l'organisation doit **savoir, décider ou améliorer** pour atteindre ses objectifs, **dans son vocabulaire à lui** et indépendamment de toute solution technique.

Il comporte quatre éléments :

| Élément | Question | Exemple EduSmart |
|---|---|---|
| **Acteur** | Qui a besoin de l'information ? | Le Directeur Général |
| **Objectif** | Pour atteindre quel but ? | Réduire les abandons |
| **Question** | Que doit-il savoir ? | Quelles filières perdent le plus d'étudiants, et à quel moment de l'année ? |
| **Décision** | Qu'en fera-t-il ? | Renforcer le tutorat de la filière concernée au 1ᵉʳ trimestre |

Un besoin sans décision associée est une **curiosité**, pas un besoin. Un indicateur que personne n'utilise pour agir est du bruit dans le tableau de bord.

### 2. Pourquoi faut-il comprendre les objectifs du client avant de développer un tableau de bord ?

1. **Pour choisir les bonnes règles de calcul.** Les données EduSmart permettent au moins trois calculs du CA. Seul le métier peut dire si un paiement `EN_ATTENTE` compte, si un paiement négatif est une erreur de signe ou un remboursement, et si le CA se rattache à la date de paiement ou à l'année académique.
2. **Pour construire le bon modèle de données.** La **granularité** du Data Warehouse (Phase 7) découle des questions. Si le DG veut le CA par jour et par mode de paiement, le fait « paiement » doit garder la date et le mode. Si l'on agrège trop tôt, l'information est perdue.
3. **Pour ne pas construire l'inutile.** Un tableau de bord de 40 graphiques que personne ne regarde coûte cher et dilue le message.
4. **Pour révéler les manques.** La satisfaction et l'évaluation des enseignants n'existent dans aucune source. Sans analyse du besoin, on s'en aperçoit trop tard, le jour de la démonstration.
5. **Pour obtenir l'adhésion.** Un décideur fait confiance à un chiffre dont il a validé la définition.

### 3. Quelle différence entre une demande métier et une demande technique ?

| | Demande métier | Demande technique |
|---|---|---|
| Porte sur | Un **problème** ou une **décision** | Une **solution** ou un **outil** |
| Vocabulaire | Métier (abandon, encaissement, réussite) | Informatique (table, graphique, API) |
| Exemple EduSmart | « Je veux savoir pourquoi les étudiants abandonnent. » | « Je veux un graphique en barres Power BI des inscriptions au statut ABANDON. » |
| Exemple EduSmart | « Je veux être alerté quand les encaissements ralentissent. » | « Ajoute une jauge du CA mensuel en page 1. » |
| Risque | Rester floue | Répondre à la mauvaise question |
| Rôle de l'analyste BI | La **préciser** et la **quantifier** | **Remonter** au besoin qui l'a motivée (« pourquoi ? ») |

Une demande technique doit toujours être **ramenée à la demande métier** qui la motive.

Exemple : on demande « un graphique des connexions ». En cherchant le besoin, on découvre que le DG veut savoir si la plateforme mobile est utilisée. La bonne réponse mobilise alors MongoDB (sessions de l'application), et pas seulement MySQL (temps de connexion).

### 4. Comment identifier les indicateurs réellement utiles ?

**Méthode : partir des objectifs, pas des données disponibles.**

```
Objectif stratégique → Questions de pilotage → Indicateurs → Données nécessaires → Sources disponibles ?
```

C'est l'approche GQM (*Goal – Question – Metric*). Chaque indicateur retenu doit passer ces critères :

| Critère | Question à se poser |
|---|---|
| **Lié à un objectif** | Quel objectif mesure-t-il ? |
| **Actionnable** | Quelle décision prendra-t-on s'il monte ou descend ? |
| **Défini sans ambiguïté** | Deux personnes le calculeraient-elles pareil ? |
| **Mesurable** | Les données existent-elles, et sont-elles assez fiables ? |
| **Comparable** | Peut-on le suivre dans le temps et le comparer à une cible ? |
| **Compréhensible** | Le DG le comprend-il sans explication ? |

Ces critères seront approfondis en Phase 11 (KPI et critères SMART).

**Outils de recueil :**
- entretiens avec les acteurs, guidés par des questions ouvertes (voir ci-dessous) ;
- analyse des rapports existants (s'il y en a) ;
- ateliers de priorisation (méthode MoSCoW) ;
- **confrontation aux données réelles** : le profilage du volet A révèle ce qui est faisable.

---

## Application à EduSmart

### Les acteurs et leurs objectifs

Le PDF ne nomme que le Directeur Général. Les autres acteurs sont **déduits des sources** (chaque source correspond à un service) : ce sont des hypothèses de travail à confirmer.

| Acteur | Objectifs | Sources concernées |
|---|---|---|
| **Directeur Général** (commanditaire) | Croissance, rentabilité, réputation, réduction des abandons | Toutes |
| Direction des études / scolarité | Effectifs, réussite, abandons, remplissage des classes | PostgreSQL, MySQL |
| Direction financière | Encaissements, impayés, modes de paiement | PostgreSQL, (MongoDB) |
| Direction pédagogique / plateforme | Engagement, progression, contenus les plus utiles | MySQL, MongoDB |
| Ressources humaines | Masse salariale, absentéisme, remplacements | CSV RH |
| Direction technique | Usage mobile, versions de l'application, qualité de service | MongoDB, Redis |

### Matrice « besoin → indicateur → données »

| # | Objectif | Question de pilotage | Indicateur candidat | Sources | Faisabilité |
|---|---|---|---|---|---|
| 1 | Croissance | Combien d'étudiants avons-nous réellement ? | Nombre d'étudiants distincts (inscrits, avec ou sans compte LMS) | PG + MySQL + correspondance | ✅ Avec la table de correspondance |
| 2 | Rentabilité | Combien encaissons-nous ? | Chiffre d'affaires encaissé | PostgreSQL | ✅ Après nettoyage (règles à valider) |
| 3 | Rentabilité | Les étudiants paient-ils à temps ? | Taux de recouvrement (encaissé / dû) | PostgreSQL (`cout_total`, `reduction`, paiements) | ✅ |
| 4 | Qualité pédagogique | Les étudiants réussissent-ils ? | Taux de réussite aux quiz | MySQL | ⚠️ Niveau quiz uniquement |
| 5 | Réduction des abandons | Combien abandonnent, où, quand ? | Taux d'abandon | PostgreSQL (`statut = ABANDON`) | ✅ |
| 6 | Engagement | Les étudiants progressent-ils ? | Progression moyenne | MySQL (+ Redis) | ✅ |
| 7 | Engagement | Combien d'étudiants utilisent la plateforme ? | Étudiants actifs | MySQL, MongoDB, Redis | ✅ Définition à valider |
| 8 | Offre de formation | Quelles formations attirent ? | Inscriptions par filière ; suivis par module | PostgreSQL, MySQL | ✅ Après standardisation des libellés |
| 9 | Engagement | Combien de temps passent-ils connectés ? | Durée moyenne de connexion | MySQL, MongoDB | ⚠️ Deux mesures, deux unités |
| 10 | Réputation | Les étudiants sont-ils satisfaits ? | Satisfaction | — | ❌ **Aucune donnée** |
| 11 | Qualité d'enseignement | Quels enseignants sont les mieux évalués ? | Note moyenne des enseignants | — | ❌ **Aucune donnée** |
| 12 | Maîtrise des coûts | Que coûtent les enseignants ? | Masse salariale mensuelle | CSV RH | ✅ Après nettoyage (formule du net, doublons) |
| 13 | Continuité pédagogique | Les absences sont-elles remplacées ? | Taux d'absentéisme, taux de remplacement | CSV RH | ✅ |
| 14 | Usage mobile | L'application est-elle utilisée, et à jour ? | Sessions mobiles, part de la dernière version | MongoDB | ✅ |

Les indicateurs 1, 2, 4, 8, 9, 10 et 11 correspondent exactement aux 7 demandes du DG (Phase 1). Les indicateurs 5, 6 et 7 correspondent aux exemples de KPI de la Phase 11.

### Définitions à faire valider par le métier

Pour chacune de ces définitions, **les données ne tranchent pas** : c'est une décision métier. Les propositions ci-dessous seront reprises en Phase 11.

| Notion | Options possibles | Proposition | Impact chiffré (Phase 1) |
|---|---|---|---|
| **Étudiant** | inscrit (PG) ; compte LMS (MySQL) ; les deux | Personne distincte inscrite **ou** ayant un compte LMS, avec ventilation | 10 500 (10 000 inscrits + 500 comptes LMS seuls) |
| **Chiffre d'affaires** | toutes les lignes ; paiements VALIDE ; VALIDE rattachés ; négatifs en valeur absolue | Paiements **VALIDE**, rattachés à une inscription, **négatifs signalés et exclus** en attendant une décision | de 12,91 à 14,20 Mds XOF |
| **Réussite** | quiz validé à la 1ʳᵉ tentative ; quiz validé au moins une fois ; diplôme | Part des couples (étudiant, quiz) validés au moins une fois | 74,1 % par tentative contre 91,5 % par (étudiant, quiz) |
| **Abandon** | statut ABANDON ; plus d'activité LMS depuis 60 jours | Statut ABANDON (PostgreSQL), rapproché de l'inactivité LMS | — |
| **Étudiant actif** | connecté dans la journée ; dans les 30 derniers jours ; en ce moment | Au moins une activité (MySQL ou MongoDB) dans les **30 derniers jours** | 241 connectés à 23 h, 729 actifs le 15/09 |
| **Temps de connexion** | durée MySQL ; durée des sessions mobiles | Durée MySQL (minutes), **médiane** plutôt que moyenne | médiane 28 min ; moyenne de 34,6 à 37,7 min selon la règle |
| **Formation** | filière (PG) ; module (MySQL) | Deux axes distincts : l'offre diplômante (filière) et les contenus (module) | L'IA passe de 5ᵉ à 1ʳᵉ après unification des libellés |

L'exemple de la **réussite** est parlant : 74 % et 91 % sont deux réponses exactes à deux questions différentes. Sans définition partagée, deux rapports donneront deux chiffres « vrais » et contradictoires.

### Besoins non couverts par les données (gaps)

| Besoin | Pourquoi il n'est pas couvert | Recommandation (Phase 18) |
|---|---|---|
| Satisfaction des étudiants | Aucune enquête, aucune note de cours dans les 5 sources | Mettre en place une enquête de fin de module (application mobile) |
| Enseignants les mieux évalués | Aucune évaluation ; le lien enseignant ↔ cours n'existe que par le **nom** du responsable de classe | Créer une table d'affectation (le fichier « affectations » est mentionné par le PDF RH, jamais décrit) et une évaluation des enseignements |
| Activité des enseignants sur la plateforme | Aucun journal de connexion des enseignants (`active_teachers` de Redis n'est pas vérifiable) | Journaliser les connexions des enseignants |
| Réussite diplômante | Pas de notes d'examen ni de délibération ; le statut DIPLOME est la seule trace | Intégrer les résultats d'examens |

Remonter ces gaps fait partie du livrable : **dire au DG ce que ses données ne permettent pas de savoir** est aussi utile que de lui montrer ce qu'elles savent.

### Guide d'entretien avec le Directeur Général

1. Quelles sont vos trois priorités pour l'année ?
2. Quelles décisions prenez-vous chaque semaine ? Sur quelles informations ?
3. Quel chiffre regardez-vous en premier le lundi matin ?
4. Pour vous, qu'est-ce qu'un « étudiant actif » ? Et un « abandon » ?
5. Le chiffre d'affaires doit-il suivre la date de paiement ou l'année académique ?
6. Un paiement en attente ou remboursé compte-t-il dans le CA ?
7. Qu'attendez-vous d'un « taux de réussite » : la réussite aux quiz ou l'obtention du diplôme ?
8. Quels seuils vous alerteraient ? (Exemple : un taux d'abandon supérieur à 8 %.)
9. À quel niveau de détail descendez-vous : région, filière, classe, étudiant ?
10. Qui d'autre doit voir ces indicateurs ? Avec quelles restrictions (salaires) ?

### Priorisation (MoSCoW, proposition)

| Priorité | Indicateurs |
|---|---|
| **Must** (indispensable) | Étudiants distincts, CA encaissé, taux de réussite, taux d'abandon, étudiants actifs |
| **Should** (important) | Progression moyenne, formations les plus suivies, recouvrement, durée de connexion |
| **Could** (souhaitable) | Masse salariale, absentéisme, usage mobile |
| **Won't** (pas maintenant, faute de données) | Satisfaction, évaluation des enseignants → recommandations |

---

## Synthèse

| Idée clé | Illustration |
|---|---|
| Le besoin métier précède la technique | Le choix de la règle du CA fait varier le chiffre de 10 % |
| Toute demande technique se ramène à un besoin | « Un graphique des connexions » → « la plateforme mobile est-elle utilisée ? » |
| Un indicateur utile est lié à une décision | L'abandon mène au renforcement du tutorat ; la satisfaction ne peut pas être mesurée |
| Les définitions doivent être validées | Réussite : 74 % ou 91 % selon la définition |
| L'analyse du besoin révèle les gaps | 4 besoins sans données, à remonter au DG |

## Références

- PDF « BI Recherche P8 », Phase 2 (questions 1 à 4) ; Phase 1 (cas pratique) ; Phase 11 (exemples de KPI).
- V. Basili, G. Caldiera et H. D. Rombach, *The Goal Question Metric Approach* (1994).
- Chiffres : `python -m scripts.constats_sources` et `docs/01_operationnel_vers_decision.md`.
