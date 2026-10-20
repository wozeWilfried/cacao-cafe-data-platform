# Outil de pilotage GitHub — jalons et issues

`sync_github.py` crée et met à jour **labels, jalons (milestones) et issues** du
dépôt à partir du fichier déclaratif `project/roadmap.yml`.

## Pourquoi

- Une **source de vérité** versionnée (`roadmap.yml`) plutôt que des clics manuels.
- **Idempotent** : relancer ne crée pas de doublons (détection par titre).
- **Sans `gh`** : uniquement l'API REST GitHub et la bibliothèque standard Python.
- Fonctionne en `--dry-run` pour valider avant toute écriture.

## Prérequis

```bash
pip install -r scripts/requirements.txt        # PyYAML
```

Créer un **jeton d'accès personnel** GitHub :

- Classique : https://github.com/settings/tokens → scope `repo` (ou `public_repo` si dépôt public).
- Ou fin-grained : permissions `Issues: Read and write` + `Metadata: Read`.

Puis exporter le jeton (jamais commité) :

```bash
export GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

## Utilisation

```bash
# 1. Simuler, sans écrire (aucun jeton requis)
python scripts/sync_github.py --dry-run

# 2. Créer réellement labels, jalons et issues
export GH_TOKEN=...
python scripts/sync_github.py

# 3. Se limiter à certains jalons
python scripts/sync_github.py --only m0,m1

# 4. Mettre à jour le corps des issues déjà créées
python scripts/sync_github.py --update

# 5. Forcer un autre dépôt cible
python scripts/sync_github.py --repo wozeWilfried/cacao-cafe-data-platform
```

Le dépôt est détecté automatiquement depuis `git remote origin`.

## Après la synchronisation (optionnel)

Pour obtenir un **tableau de bord de suivi** (Projects v2), créez un projet puis
ajoutez les issues par glisser-déposer. Le rattachement aux jalous est déjà fait
par le script, la vue « par jalon » est donc immédiate.

## Modifier la roadmap

Éditez `project/roadmap.yml` (labels, jalons, issues), puis relancez la commande.
Les entrées dont le titre existe déjà sont laissées telles quelles (sauf `--update`).
