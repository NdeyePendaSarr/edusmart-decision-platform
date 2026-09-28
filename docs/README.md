# Documentation de recherche — EduSmart Decision Platform

Réponses aux questions de recherche du PDF « BI Recherche P8 » (phases 1 à 11), **appuyées sur les 5 sources réellement construites** (volet A).

| Document | Phase | Étape | Contenu |
|---|---|---|---|
| [01_operationnel_vers_decision.md](01_operationnel_vers_decision.md) | 1 | 1 | Données opérationnelles, OLTP, limites des systèmes dispersés, besoins du DG, BI ; cas pratique EduSmart |
| [02_besoin_metier.md](02_besoin_metier.md) | 2 | 1 | Besoin métier, demande métier ou technique, choix des indicateurs ; matrice des besoins, définitions à valider, gaps |
| [03_architectures.md](03_architectures.md) | 3 | 1-2 | Data Warehouse, Data Mart, Data Lake, Lakehouse ; architecture retenue pour EduSmart |
| [04_etl_vs_elt.md](04_etl_vs_elt.md) | 4 | 2 | ETL ou ELT ; décision ELT (EtLT) ; conception du pipeline et pièges d'intégration |
| [05_qualite.md](05_qualite.md) | 5 | 3 | Qualité des données, 5 dimensions, méthode (corriger, rejeter, signaler), rapport qualité, porte G3 |
| [06_metadonnees.md](06_metadonnees.md) | 6 | 3 | Métadonnées, `metadata_sources`, `etl_execution_log`, lignage de bout en bout |
| [07_conception_dw.md](07_conception_dw.md) | 7, 8, 9 | 4 | Faits, dimensions, mesures, grain ; étoile, flocon, constellation ; SCD 1, 2, 3 et démonstration |
| [10_olap.md](10_olap.md) | 10 | 5 | Cube OLAP ; roll up, drill down, slice, dice, pivot sur le cube EduSmart |
| [11_kpi.md](11_kpi.md) | 11 | 5 | KPI ou métrique, critères de choix, 8 fiches KPI, satisfaction non calculable, porte G5 |

Tous les chiffres cités se recalculent avec :

```powershell
python -m scripts.constats_sources
```

Prérequis : les 5 sources générées. Les calculs sont exploratoires ; les valeurs officielles viendront du Data Warehouse.

Version PDF (livrable final) : à produire en fin de projet à partir de ces fichiers Markdown.
