# Cacao & Café Data Platform

Dépôt GitHub : **`cacao-cafe-data-platform`**

Plateforme décisionnelle pour suivre la filière cacao et café, du producteur au port.

Chaîne de bout en bout : 15 sources hétérogènes → ETL Python/SQL →
entrepôt PostgreSQL → 3 ML + 2 NLP → tableau de bord Metabase (5 pages).

## Démarrage rapide

```bash
# 1. Configuration
cp .env.example .env          # puis changez les mots de passe

# 2. Bases + Metabase
docker compose up -d

# 3. Vérifier
docker compose ps
#   pg_source  -> localhost:5433  (coop_source)
#   pg_dwh     -> localhost:5434  (dwh)
#   metabase   -> http://localhost:3000

# 4. Environnement Python (3.11/3.12 conseillé)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 5. Générer les référentiels (coopératives, producteurs, parcelles)
python3.12 generate/referentiels.py --scale 0.01 --snapshot 2022-10-01
```

## Génération des données

Les générateurs vivent dans `generate/` et sont **reproductibles** : graine fixe
(`RANDOM_SEED`, défaut 42) et facteur d'échelle (`SCALE`, 0.01 en développement,
1.0 pour la volumétrie cible ~1,7 M de lignes). Ils ne dépendent que de la
bibliothèque standard.

- `generate/referentiels.py` — coopératives (`cooperatives_<date>.csv`),
  producteurs et parcelles (GeoJSON `producteurs_parcelles_<date>.geojson`),
  déposés dans `data/inbox/referentiels/` ; un manifeste `_manifest.json` trace
  graine, échelle et comptages. Le millésime (`--snapshot`) permet de produire
  plusieurs instantanés, base du SCD2 côté entrepôt.
- `generate/livraisons.py` — insère dans `coop.livraison` (Postgres source)
  environ 304 200 livraisons (× l'échelle) sur 4 campagnes, avec saisonnalité
  par culture et poids par sac de 60 kg. Rejouable (table vidée avant insertion).
- `generate/qualite.py` — contrôles qualité des lots (~150 000) en JSON
  mensuels (`data/inbox/qualite/`), décision/grade, et observations libres
  **étiquetées** (`defaut_principal`) d'où sortira le modèle NLP1.
- `generate/charger_referentiels.py` — **relecture SQL** : charge les fichiers
  (CSV/GeoJSON/JSON/logs/XML/Excel) dans des tables de consultation
  `coop.cooperative`, `coop.producteur`, `coop.parcelle`, `coop.lot_qualite`,
  `coop.paiement`, `coop.transport_ping`, `coop.contrat`, `coop.trafic_port`,
  `coop.intrant_distribution`. La source officielle de l'ETL reste les fichiers ;
  ces tables permettent seulement de tout voir et contrôler dans PostgreSQL.
- `generate/transport.py` — logs GPS de transport (logs texte, un fichier par
  trajet, ~600 000 pings).
- `generate/contrats.py` — contrats d'achat au format **XML** + schéma
  `contrat.xsd` (base du NLP2).
- `generate/intrants.py` — distributions d'intrants en **Excel** (.xlsx).
- `generate/trafic.py` — trafic portuaire en **CSV** mensuel (Douala/Kribi).
- `generate/sources_publiques.py` — collecte des **7 sources publiques** avec
  cache disque (`data/cache/`) et fichier exploitable dans `data/inbox/public/` :
  prix mondiaux (World Bank Pink Sheet, cacao + cafés depuis 1960), production
  FAOSTAT (cacao/café, 112 pays), météo NASA POWER et Open-Meteo (7 stations),
  taux de change Frankfurter + parité XAF. Un **fichier de repli** permet de
  démontrer sans Internet.

### Sources publiques (7)

| Source | Format | Fraîcheur |
|---|---|---|
| World Bank Pink Sheet (cacao, cafés) | CSV (depuis Excel) | mensuelle, 1960→ |
| FAOSTAT (cacao, café) | CSV | annuelle, 112 pays |
| NASA POWER (T2M, pluie) | CSV | quotidienne, 7 stations |
| Open-Meteo archive | CSV | quotidienne, 7 stations |
| Frankfurter / BCE (USD, GBP, XAF) | CSV | quotidienne |

### Volumétrie complète (SCALE=1.0)

| Source générée | Format | Lignes |
|---|---|---|
| Livraisons | Postgres | 304 200 |
| Paiements | JSON / jour | 280 026 |
| Pings GPS | Logs texte | 608 543 |
| Contrôles qualité | JSON / mois | 150 000 |
| Intrants | Excel | 40 000 |
| Trafic portuaire | CSV / mois | 4 000 |
| Parcelles / Producteurs / Coops | GeoJSON + CSV | 15 000 / 9 000 / 48 |
| Contrats | XML | 600 |

## Arborescence

```
docker-compose.yml      bases source + entrepôt + Metabase
generate/               générateurs de données (graine fixe, --scale)
data/inbox|archive|quarantaine|reference   dépôt de fichiers et replis d'API
sql/source/             schéma coop + déclencheurs CDC
sql/dwh/                schémas + DDL dimensions/faits
sql/indicateurs/        25 requêtes (une par indicateur)
etl/                    extract / quality / transform / load / common
dags/                   DAGs Airflow (planification, capteur de fichier)
ml/                     3 modèles ML + 2 traitements NLP
dashboards/             export Metabase / captures
tests/                  règles de qualité, SCD2, idempotence
docs/                   dossier de conception
```

## Avancement

- [x] Étape 1 — Squelette du dépôt + bases Docker + user lecture seule
- [~] Étape 2 — Schéma source `coop` (livraison + CDC) ✓, générateurs : référentiels ✓, à venir : livraisons, paiements, qualité, GPS, contrats, intrants
- [ ] Étape 3 — Modèle de l'entrepôt (dimensions, faits, dim_date)
- [ ] Étape 4 — Pipeline ETL + règles de qualité + journal
- [ ] Étape 5 — Incrémental (filigrane, hachage, suppressions, SCD2)
- [ ] Étape 6 — Déclenchement Airflow (planification + capteur de fichier)
- [ ] Étape 7 — 25 indicateurs + ML + NLP
- [ ] Étape 8 — Tableau de bord 5 pages
