# Phase 14 — Data Storytelling

*EduSmart Decision Platform · Lot L9 · Étape 6 du module BI*

> **PDF, recherche :** qu'est-ce que le Data Storytelling ? Comment raconter une histoire avec les données ? Comment convaincre un décideur ?
>
> **PDF, TP :** présenter les résultats obtenus à partir du tableau de bord.
>
> Tableau de bord : `powerbi/EduSmart.pbix` (4 pages) · export : [`powerbi/EduSmart.pdf`](../powerbi/EduSmart.pdf) · chiffres : [11_kpi.md](11_kpi.md) · graphiques : [12_visualisations.md](12_visualisations.md).

**Nature de ce document.** C'est un document de **compréhension** : il construit le récit qu'un analyste présenterait au Directeur Général, et il dit honnêtement ce que ces données permettent, ou non, d'affirmer. Tous les chiffres sont ceux du Data Warehouse au 15/09/2026 (date de référence C20), validés par trois chemins de calcul (SQL, Python, DAX : portes G5a et G5b).

---

## 1. Qu'est-ce que le Data Storytelling ?

Le Data Storytelling est l'art de transformer une analyse en **message qui déclenche une décision**. Il combine trois éléments, et aucun ne suffit seul :

| Élément | Rôle | Seul, il donne… |
|---|---|---|
| **Les données** | La preuve | un tableau de chiffres que personne ne lit |
| **Les visuels** | Rendre la preuve évidente | un joli graphique sans conclusion |
| **Le récit** | Relier les preuves à une décision | une opinion sans preuve |

Les données expliquent **ce qui se passe**, le récit explique **pourquoi cela compte**, et les visuels **le rendent visible**. Un tableau de bord répond à « où en sommes-nous ? ». Une histoire répond à « que devons-nous faire, et pourquoi maintenant ? ».

**Différence avec un tableau de bord.** Le tableau de bord EduSmart (L8) est un outil d'**exploration** : le décideur filtre, descend dans les hiérarchies et trouve ses réponses. Le storytelling est une **explication** : l'analyste a déjà exploré et choisit le chemin, les 3 ou 4 constats qui comptent, dans un ordre qui mène à une décision.

## 2. Comment raconter une histoire avec les données ?

### 2.1 Partir d'une idée maîtresse

Avant tout visuel, il faut pouvoir écrire le message en **une phrase** : un point de vue, ce qui est en jeu, la décision attendue. Si cette phrase n'existe pas, il n'y a pas encore d'histoire, seulement des chiffres.

### 2.2 Une structure en trois temps : situation, complication, résolution

| Temps | Question | Contenu |
|---|---|---|
| **Situation** | Où en sommes-nous ? | Les faits partagés, sans surprise : le décideur doit se reconnaître |
| **Complication** | Qu'est-ce qui ne va pas, ou pourrait mal tourner ? | L'écart à la cible, le risque, ce qu'on ne sait pas |
| **Résolution** | Que faire ? | Des recommandations précises, chacune liée à un constat et à un indicateur de suivi |

Pour un décideur, on peut aussi **commencer par la conclusion** (principe de la pyramide) : la recommandation d'abord, puis les arguments, puis les preuves. Le décideur pressé s'arrête à la première ligne ; le décideur sceptique descend jusqu'aux chiffres.

### 2.3 Des règles de mise en forme

Elles sont déjà appliquées dans le tableau de bord (L8, [13_powerbi.md](13_powerbi.md) § 6) :
- **une page = une question** du décideur ;
- des **titres qui énoncent la conclusion** (« Le recouvrement est stable autour de 90 % ») et non le sujet (« Recouvrement ») ;
- une **couleur d'accent** réservée à ce qui s'écarte de la cible ;
- au plus **6 visuels** par page ;
- le **bon graphique** pour la bonne question (Phase 12) : une évolution se lit sur une courbe, une comparaison entre catégories sur des barres.

## 3. Comment convaincre un décideur ?

| Principe | Application à EduSmart |
|---|---|
| **Répondre à SES questions**, pas aux nôtres | Le récit suit les 7 questions du DG (Phase 1), § 4 |
| **Chiffre + comparaison + décision** | « 6,24 % d'abandon » ne dit rien seul ; « 6,24 % pour une cible de 5 %, stable sur 3 ans : le problème est structurel » appelle une décision |
| **Mériter la confiance dans les chiffres** | Chaque KPI est calculé par 3 chemins (SQL = Python = DAX), et le pipeline est testé de bout en bout (porte G6, [15_tests_pipeline.md](15_tests_pipeline.md)) |
| **Dire ce qu'on ne sait pas** | Satisfaction et évaluation des enseignants : aucune donnée. Le dire renforce la crédibilité de tout le reste |
| **Ne jamais affirmer une cause sans preuve** | Une corrélation n'est pas une cause ; ici, la plupart des relations testées sont nulles ou faibles (§ 8) |
| **Anticiper les objections** | § 9 : les questions qu'un DG posera, avec leurs réponses |
| **Proposer une action mesurable** | Chaque recommandation a un responsable et un KPI de suivi (§ 7) |

## 4. Le public : le Directeur Général et ses 7 questions

Le cas pratique de la Phase 1 liste ce que le DG veut savoir. Le récit doit y répondre, y compris quand la réponse est « on ne peut pas savoir ».

| Question du DG (PDF, Phase 1) | Réponse au 15/09/2026 | Page Power BI | Statut |
|---|---|---|---|
| Le nombre réel d'étudiants | **10 500** personnes distinctes (la somme naïve des sources donnait **26 476**) | Vue Direction | ✅ |
| Le chiffre d'affaires | **13,554 Mds XOF** encaissés | Vue Direction, Finance | ✅ |
| Le taux de réussite | **93,13 %** de réussite aux quiz en ligne | Vue Direction, Pédagogie | ✅ (≠ réussite au diplôme, § 8.3) |
| La satisfaction des étudiants | Aucune source ne la contient | Vue Direction (carte « Non mesurée ») | ❌ |
| Les formations les plus suivies | Matrice catégorie × niveau, hiérarchies Offre | Pédagogie | ✅ |
| Le temps moyen de connexion | Médiane de **29 min** (1 740 s) | Engagement | ✅ (médiane plutôt que moyenne, § 8.4) |
| Les enseignants les mieux évalués | Aucune évaluation dans les sources | — | ❌ |

**5 questions sur 7 ont une réponse.** Les 2 autres sont des **manques de données**, documentés depuis L3 ([02_besoin_metier.md](02_besoin_metier.md)) : ils deviennent des recommandations.

## 5. L'idée maîtresse

> **EduSmart encaisse 90 % de ce qu'elle attend et ses apprenants réussissent leurs quiz (93 %), mais seulement 3 sur 10 sont actifs sur 30 jours. La priorité n'est plus de recruter, c'est d'engager et d'écouter.**

« Écouter » renvoie aux **deux** angles morts : l'entreprise ne mesure ni la satisfaction de ses étudiants, ni la qualité perçue de ses enseignants.

*Précision :* 3 003 actifs sur 10 500 étudiants, soit **28,6 %**. « 3 sur 10 » est un arrondi un peu favorable ; la cible proposée en L7 est de 30 %.

## 6. Le récit en trois actes

### Acte 1 — Situation : une plateforme qui fonctionne *(page Vue Direction)*

| Constat | Chiffre | Lecture |
|---|---|---|
| Une base d'étudiants enfin connue | **10 500** personnes (9 000 rapprochées entre PostgreSQL et MySQL, 1 000 inscrits sans compte LMS, 500 comptes LMS sans inscription) | Sans plateforme décisionnelle, la direction aurait additionné les sources : **26 476**, soit 2,5 fois trop |
| Un chiffre d'affaires en croissance | 2 868 M → 5 101 M → 5 585 M XOF (années académiques 2023-2024 à 2025-2026) | Le volume d'inscriptions a doublé : 3 617 → 7 383 |
| Les étudiants réussissent leurs quiz | **93,13 %** des couples (étudiant, quiz) validés | Au-dessus de la cible proposée (85 %) |
| Les sessions sont longues | Médiane de **29 min** | Au-dessus de la cible proposée (20 min) |

Message de l'acte 1 : *les fondamentaux sont sains, et pour la première fois, on peut le prouver avec des chiffres fiables.*

### Acte 2 — Complication : trois signaux d'alerte et deux angles morts *(pages Finance, Engagement, Pédagogie)*

**Signal 1 — L'argent qui ne rentre pas grossit avec l'activité.**

| Année académique | Montant dû | Encaissé | Non encaissé | Recouvrement |
|---|---:|---:|---:|---:|
| 2023-2024 | 3 179 M | 2 868 M | **311 M** | 90,19 % |
| 2024-2025 | 5 624 M | 5 101 M | **523 M** | 90,70 % |
| 2025-2026 | 6 240 M | 5 585 M | **655 M** | 89,51 % |
| **Total** | **15 043 M** | **13 554 M** | **≈ 1 489 M** | **90,10 %** |

Le **taux** est stable, autour de 90 % ; le **montant** non encaissé, lui, a doublé en deux ans (311 M → 655 M), parce que l'activité a doublé. À taux constant, chaque nouvelle cohorte ajoute des impayés. *Nuance :* l'année 2025-2026 n'est pas close au 15/09/2026 ; une partie des 655 M peut encore être encaissée. *(Montants en millions de XOF, arrondis : écart d'arrondi possible de ±1 M sur le total.)*

**Signal 2 — 7 étudiants sur 10 ne se sont pas manifestés depuis 30 jours.**
**3 003** actifs sur 10 500 (28,6 %), sous la cible proposée de 30 %. *Nuance importante :* ce KPI ne compte que les connexions, les notes et l'activité de quiz. Les vidéos et les téléchargements MongoDB ne sont pas dans le DW ([11_kpi.md](11_kpi.md), limites du KPI). Le chiffre est donc un **minimum** : l'engagement réel est au moins de 28,6 %.

**Signal 3 — Ils commencent, mais ne finissent pas.**
- Progression moyenne : **65,59 %**, sous la cible proposée de 70 %.
- Abandon : **6,24 %**, au-dessus de la cible proposée de 5 %, et **stable** sur trois ans (6,25 % ; 6,33 % ; 6,16 %). Un taux stable n'est pas un accident : c'est une caractéristique du fonctionnement actuel.

**Angle mort 1 — La satisfaction n'est pas mesurée.** Aucune des 5 sources ne contient d'avis ni d'enquête. Le tableau de bord le montre explicitement (carte « Non mesurée ») plutôt que de le cacher.

**Angle mort 2 — La qualité des enseignants n'est pas mesurée.** Il n'existe aucune évaluation, et le lien enseignant ↔ cours n'existe que par le **nom** du responsable de classe (convention C18).

Message de l'acte 2 : *l'entreprise recrute bien et encaisse bien, mais elle ne retient pas assez, et elle ne sait pas pourquoi, faute d'écouter ses étudiants.*

### Acte 3 — Résolution : engager et écouter *(§ 7)*

## 7. Recommandations

Chaque recommandation est rattachée à un constat, à un indicateur de suivi et à un niveau de confiance. **Les cibles chiffrées ne figurent dans aucune source** : celles qui sont citées sont les propositions de L7, à valider par la direction.

| # | Recommandation | Constat d'appui | KPI de suivi | Responsable | Confiance |
|---|---|---|---|---|---|
| **R1** | Collecter un **score de satisfaction** (échelle de 1 à 5) à la fin de chaque module, dans la plateforme pédagogique ; il alimenterait un nouveau fait `fact_evaluations` | Satisfaction : aucune donnée | Satisfaction (enfin mesurable) | DG | **Haute** : manque factuel |
| **R2** | Créer une **évaluation des enseignements** et une table d'**affectation** enseignant ↔ cours (le PDF RH évoque les affectations sans les décrire) | Évaluation des enseignants : aucune donnée | Note moyenne par enseignant | Direction pédagogique, RH | **Haute** : manque factuel |
| **R3** | Un **plan de relance des impayés** dès la 2ᵉ tranche, piloté par le Top 10 des impayés (page Finance) | ≈ 1 489 M XOF non encaissés, montant en hausse | Taux de recouvrement ; impayés (XOF) | Direction financière | **Moyenne** : l'année en cours n'est pas close |
| **R4** | Un **programme de réactivation** des inactifs (relance après 15 jours sans activité, tutorat) | 71,4 % d'étudiants sans activité mesurée sur 30 jours ; progression 65,59 % ; abandon 6,24 % | Étudiants actifs (30 j) ; progression ; abandon | Direction pédagogique | **Moyenne** : KPI sous-estimé (vidéos non comptées), cause de l'inactivité inconnue tant que R1 n'existe pas |
| **R5** | Intégrer les **vidéos et téléchargements** MongoDB dans le DW, pour un KPI d'activité complet | Le KPI actuel est un minimum | Étudiants actifs (30 j) | Équipe data | **Haute** : limite technique documentée |
| **R6** | **Normaliser la saisie à la source** : listes fermées pour les modes de paiement (« OM », « Orange Money », « orange money »), les villes (« Dakar », « DAKAR », « dakarr »), les catégories | 159 946 anomalies traitées en L5 (55 853 corrigées, 25 932 rejetées, 78 161 signalées) | Taux de conformité qualité ([05_qualite.md](05_qualite.md)) | DSI, chaque service | **Haute** |

**Ce qui n'est PAS recommandé, et pourquoi :**
- *« Développer une application tablette pour allonger les sessions »* : la durée des sessions est identique sur mobile, PC et tablette (§ 8.1). Rien ne justifie cet investissement.
- *« Pousser les étudiants à se connecter plus longtemps pour progresser »* : aucune relation entre heures connectées et progression (r = −0,01, § 8.1).
- *« Remplacer la satisfaction par le taux de réussite »* : un indicateur de substitution tromperait le décideur ([11_kpi.md](11_kpi.md), § 5).

## 8. Ce que les données ne permettent PAS d'affirmer

### 8.1 Des données simulées : certains « constats » sont des paramètres du générateur

Les 5 sources ont été **générées** (Python, Faker, graine 2026). Plusieurs résultats du tableau de bord ne décrivent donc pas un comportement réel : ils **restituent un paramètre du générateur**. Je l'ai vérifié dans le code.

| Constat du tableau de bord | Paramètre du générateur | Fichier |
|---|---|---|
| Pic d'activité entre 20 h et 22 h, rien avant 6 h | Poids horaires de 6 h à 23 h, maximum à 20 h et 21 h | `sources/s2_mysql/generate_data.py` |
| Dakar porte 29 % du CA, Thiès 13 % | Poids régionaux : Dakar 30, Thiès 13 (C10) | `common/senegalese_data.py` |
| Abandon de 6,24 % | `P_ABANDON = 0.06` (6 % par an) | `sources/s1_postgresql/generate_data.py` |
| Réussite de 93 % | Seuil de validation à 10/20 ; jusqu'à 5 tentatives par quiz, le score progressant de 7 points de pourcentage à chaque essai | `sources/s2_mysql/generate_data.py` |
| Durée de connexion identique sur les 3 appareils | Durée tirée d'une loi log-normale, **indépendamment** de l'appareil | idem |
| Aucune relation heures connectées / progression (r = −0,01) | Variables tirées indépendamment ([12_visualisations.md](12_visualisations.md), § 2.3) | idem |
| Recouvrement quasi uniforme entre filières (89 à 91 %) | Mêmes probabilités de paiement pour toutes les filières (aucun paramètre de filière) | `sources/s1_postgresql/generate_data.py` |
| Pic du CA en octobre | Rentrée au 1er octobre (C7) et 1ʳᵉ tranche payée dans les 10 jours suivant l'inscription | idem |

**Comment les présenter :** comme des **capacités** de la plateforme, pas comme des découvertes. Exemple : « Sur des données réelles, cette carte de chaleur dirait au DG quand programmer les classes virtuelles et la maintenance. »

**Ce que cela prouve quand même, et c'est important.** Retrouver en sortie les paramètres injectés en entrée est une **validation de bout en bout** du pipeline : 6 % d'abandon par an injectés → 6,24 % mesurés ; 10 500 personnes dans le référentiel (L1) → 10 500 comptées ; Dakar pondérée à 30 % → 29 % du CA. Un pipeline qui perdrait, dupliquerait ou rattacherait mal des lignes ne retrouverait pas ces valeurs. C'est le lien entre cette phase et la Phase 15.

**Correction par rapport aux notes de synthèse de L8.** La relation entre **tentatives et score** n'est pas nulle : elle est **négative et faible** (r = −0,20, [12_visualisations.md](12_visualisations.md) § 2.3) ; ceux qui ont besoin de plus de tentatives ont un score moyen plus bas. C'est le croisement **heures connectées × progression** qui ne montre aucune relation (r = −0,01).

### 8.2 Aucune affirmation causale

Le tableau de bord montre des **associations**, jamais des **causes**. Même la relation tentatives / score (r = −0,20) ne dit pas que retenter fait baisser le score : les étudiants en difficulté retentent plus **et** ont de moins bons scores. Une cause se démontre par une expérimentation (deux groupes, une seule différence), pas par un graphique.

### 8.3 « Taux de réussite » : de quoi parle-t-on ?

93,13 % est la part des couples (étudiant, quiz) **validés au moins une fois**, toutes tentatives confondues. Cela explique l'écart apparent avec une distribution des scores centrée vers 10-12/20 : un étudiant qui échoue deux fois puis valide compte comme une réussite. Ce n'est **pas** le taux de réussite au diplôme, qu'aucune source ne contient (gap L3).

### 8.4 Médiane plutôt que moyenne

Le DG demande un temps « moyen » de connexion. La **médiane** (29 min) est retenue, car environ 1 % des connexions dépasse 150 min, jusqu'à 480 min : une moyenne serait tirée vers le haut par ces sessions anormales. 1 658 connexions sans déconnexion (B08) sont exclues, faute de durée.

### 8.5 Le piège du taux de recouvrement filtré sur une petite région

Sans filtre, le recouvrement par filière va de 89 % à 91 %. Avec un filtre sur **Kaffrine**, Power BI affiche **2 821 %** (constat L8).

L'explication « Kaffrine a peu d'étudiants » est **incomplète**. Un petit effectif rend un taux **instable**, il ne le multiplie pas par 30 : si le numérateur et le dénominateur portaient sur les **mêmes** inscriptions, le taux resterait proche de 90 %. Un taux de 2 821 % signifie que, dans ce contexte de filtre, **le CA retenu porte sur beaucoup plus d'inscriptions que le montant dû**.

Ce que l'on sait du modèle : le CA vient de `fact_paiements`, le montant dû de `fact_inscriptions`, et chacun porte **sa propre** `region_key` (la région de l'étudiant à la date de l'événement). J'ai écarté une cause : les déménagements de la démonstration SCD 2 prennent effet à la date d'extraction (octobre 2026), **après** tous les paiements, donc ils ne séparent pas les deux régions. **La cause exacte reste à confirmer**, avec cette requête sur le DW :

```sql
-- Recouvrement par région, côté SQL : chaque fait rattaché à SA région
WITH ca AS (SELECT r.region, SUM(p.montant_ca) AS ca
            FROM dw.fact_paiements p JOIN dw.dim_region r USING (region_key) GROUP BY 1),
     du AS (SELECT r.region, SUM(i.montant_du) AS du, COUNT(*) AS inscriptions
            FROM dw.fact_inscriptions i JOIN dw.dim_region r USING (region_key) GROUP BY 1)
SELECT COALESCE(ca.region, du.region) AS region, du.inscriptions, ca.ca, du.du,
       round(100 * ca.ca / NULLIF(du.du, 0), 2) AS recouvrement_pct
FROM ca FULL JOIN du USING (region)
ORDER BY recouvrement_pct DESC NULLS FIRST;
```

- Si Kaffrine est proche de 90 % en SQL, le problème vient du **contexte de filtre de Power BI** (segment posé sur une colonne qui ne filtre qu'un des deux faits, interaction entre visuels…).
- Si Kaffrine est aberrante en SQL aussi, le problème vient du **rattachement des régions** dans le DW, et il faut comparer, pour les étudiants concernés, la région de l'inscription et celle des paiements.

**Résultat (lot L10, requêtes K1 à K4 de `diagnostics_L10.sql`, 12/10/2026) :**

| Requête | Résultat | Conclusion |
|---|---|---|
| K1 : recouvrement par région | Kaffrine **89,68 %** ; les 14 régions entre 88,57 % (Matam) et 93,29 % (Kédougou) | Kaffrine est normale |
| K2 : par filière à Kaffrine, chaque fait agrégé séparément | De 79,84 % à 100 % | Aucun taux au-dessus de 100 % |
| K3 : paiements rattachés à une autre région que leur inscription | **0** sur 38 372 | Hypothèse « déménagements SCD 2 » réfutée |
| K4 : versions SCD 2 dans `dim_etudiant` | **0** | Réfutée une seconde fois : aucun étudiant n'a déménagé dans le DW actuel |

**Le Data Warehouse est juste ; le 2 821 % venait du modèle Power BI.**

**Cause identifiée et corrigée (21/10/2026).** La relation `fact_paiements[region_key] → dim_region[region_key]` était **inactive**. Un filtre sur Kaffrine filtrait donc le montant dû (les inscriptions de Kaffrine) mais **pas** le CA (les paiements de toutes les régions) : 13,55 Mds XOF rapportés au seul dû de Kaffrine. Le même défaut rendait égales les 14 barres du graphique « CA par région » de la page Vue Direction. La relation a été rendue active : dans l'export du 21/10/2026, le CA par région suit désormais l'entrepôt (Dakar ≈ 3,9 Mds XOF, soit 29 % ; Thiès ≈ 1,8 Md, soit 13 %). Le numérateur du taux est donc filtré comme le dénominateur.

**Point resté ouvert :** la lecture directe du taux de Kaffrine dans Power BI n'a pas pu être faite, car la matrice du recouvrement (page Finance) ne réagit pas au segment région. La valeur de référence reste celle de l'entrepôt, **89,68 %** (requête K1). Ce comportement de la matrice est un défaut d'interaction du tableau de bord, à corriger ([13_powerbi.md](13_powerbi.md)).

Pourquoi la porte G5b ne l'avait pas vu : elle compare les mesures **sans filtre**, et une relation inactive ne change aucun total ([13_powerbi.md](13_powerbi.md), § 7).

**Un second piège, rencontré pendant le diagnostic.** Une première requête de vérification donnait 32 à 47 % pour toutes les filières de Kaffrine. Elle joignait `fact_paiements` et `fact_inscriptions` **ligne à ligne** (sur l'étudiant et la formation) : le montant dû de chaque inscription était compté **une fois par paiement**. Avec 2,29 paiements par inscription en moyenne, 90,10 % ÷ 2,29 ≈ 39,4 %. C'est le « chasm trap » de la modélisation dimensionnelle : dans une constellation, on **agrège chaque fait séparément** sur les dimensions partagées, puis on joint les résultats.

**Règles de lecture retenues :**
- un taux se lit sur une population suffisante et cohérente, avec son effectif ;
- numérateur et dénominateur issus de deux faits s'agrègent **séparément** ;
- au-delà de 100 %, ou loin de la moyenne, on vérifie le calcul avant de conclure.

## 9. Objections probables du décideur, et réponses

| Objection | Réponse |
|---|---|
| « Ces chiffres sont-ils fiables ? » | Chaque KPI est calculé trois fois (SQL sur le DW, Python sur la couche clean, DAX dans Power BI) avec le même résultat ; le pipeline est testé de bout en bout (101 contrôles, porte G6), y compris par des tests qui introduisent volontairement des erreurs pour vérifier qu'elles sont détectées |
| « Pourquoi 10 500 étudiants et pas 26 476 ? » | Les mêmes personnes apparaissent dans plusieurs systèmes, sous des identifiants différents (UUID dans PostgreSQL, `LMS-XXXXXX` dans MySQL). Le rapprochement compte chaque personne une seule fois |
| « 93 % de réussite, c'est excellent, non ? » | C'est la réussite aux quiz en ligne, en acceptant plusieurs tentatives. Ce n'est ni la réussite au diplôme ni une mesure de la qualité de l'apprentissage (§ 8.3) |
| « Pourquoi ne pas mesurer la satisfaction avec les données existantes ? » | Tout indicateur de substitution (temps passé, réussite) mesurerait autre chose. Il faut la demander aux étudiants (R1) |
| « Le recouvrement est à 90 %, où est le problème ? » | Le taux est stable, mais le montant non encaissé a doublé en deux ans (311 M → 655 M XOF) parce que l'activité a doublé |
| « Faut-il investir dans une application tablette ? » | Rien ne le justifie : la durée des sessions est la même sur tous les appareils (§ 7). Sur ces données simulées, c'est un paramètre du générateur ; sur données réelles, le même graphique trancherait |
| « Pourquoi l'abandon dépasse-t-il la cible ? » | Les données ne le disent pas : la source ne date pas l'abandon et n'en donne pas le motif. C'est précisément ce que R1 et R4 doivent éclairer |

## 10. L'histoire en une minute

> Pour la première fois, EduSmart connaît son nombre réel d'étudiants : **10 500**, et non 26 476. Ses fondamentaux sont sains : **13,55 milliards de XOF** encaissés, **90 %** de recouvrement, **93 %** de réussite aux quiz.
>
> Mais trois signaux doivent alerter : l'argent non encaissé a **doublé en deux ans** (655 M XOF sur la dernière année) ; **7 étudiants sur 10** n'ont aucune activité mesurée sur 30 jours ; l'abandon reste au-dessus de la cible, **à 6,24 %**, depuis trois ans.
>
> Et l'entreprise ne sait pas pourquoi : elle ne mesure **ni la satisfaction de ses étudiants, ni la qualité de ses enseignants**.
>
> La priorité n'est plus de recruter, c'est **d'engager et d'écouter** : mesurer la satisfaction et l'enseignement, relancer les impayés, réactiver les inactifs, et fiabiliser la saisie à la source.

## Références

- PDF « BI Recherche P8 », Phase 14 (Étape 6) ; Phase 1 (questions du DG).
- C. Nussbaumer Knaflic, *Storytelling with Data* (2015) : contexte, idée maîtresse, choix du visuel, élimination du superflu.
- B. Dykes, *Effective Data Storytelling* (2019) : données, récit et visuels.
- B. Minto, *The Pyramid Principle* (1987) : commencer par la conclusion ; situation, complication, résolution.
- Documents du projet : [02_besoin_metier.md](02_besoin_metier.md), [11_kpi.md](11_kpi.md), [12_visualisations.md](12_visualisations.md), [13_powerbi.md](13_powerbi.md), [15_tests_pipeline.md](15_tests_pipeline.md).
