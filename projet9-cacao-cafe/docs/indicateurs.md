# Les 25 indicateurs (M5)

Un indicateur = une définition formelle + une formule + la table de faits qui le
porte. Chaque définition vit **une seule fois** (ce document) et est matérialisée
par une vue `kpi.iXX_*` dans `sql/dwh/05_indicateurs.sql`, consommée telle quelle
par Metabase.

Deux règles de calcul non négociables (guide, section 08) :

1. **Jamais de moyenne de moyennes** : tout taux, prix ou humidité se calcule par
   rapport de sommes (`somme / somme`).
2. **Jamais de mélange de devises** : tout montant de marché est converti en FCFA
   à la date de l'événement avant sommation.

Toutes les vues filtrent `est_supprime = FALSE` (suppression logique).

## Page 1 · Synthèse

| N° | Indicateur | Formule | Vue | Faits |
|---|---|---|---|---|
| 1 | Tonnage collecté | `sum(poids_net_kg)/1000` par campagne et produit | `kpi.i01_tonnage` | fait_livraison |
| 2 | Prix moyen payé au producteur | `sum(montant)/sum(poids_net_kg)` par campagne | `kpi.i02_prix_producteur` | fait_paiement, fait_livraison |
| 3 | Taux de lots refusés | `100 × lots_refusés / lots_analysés` | `kpi.i03_taux_refus` | fait_qualite_lot |
| 4 | Marge de la filière | `100 × (CA − achats − intrants) / CA` | `kpi.i04_marge_filiere` | fait_export, fait_paiement, fait_intrants |
| 5 | Chiffre d'affaires export | `sum(volume_t × prix)` en FCFA | `kpi.i05_ca_export` | fait_export |

## Page 2 · Production et collecte

| N° | Indicateur | Formule | Vue |
|---|---|---|---|
| 6 | Tonnage par région | indicateur 1 ventilé par `dim_cooperative.region` | `kpi.i06_tonnage_region` |
| 7 | Tonnage par coopérative | indicateur 1 ventilé par coopérative | `kpi.i07_tonnage_cooperative` |
| 8 | Rendement par hectare | `tonnage / surface active` (t/ha) | `kpi.i08_rendement` |
| 9 | Producteurs actifs | `count(DISTINCT producteur_sk)` sur 12 mois glissants | `kpi.i09_producteurs_actifs` |
| 10 | Parcelles actives | `count(DISTINCT parcelle_sk)` sur 12 mois glissants | `kpi.i10_parcelles_actives` |

## Page 3 · Qualité

| N° | Indicateur | Formule | Vue |
|---|---|---|---|
| 11 | Taux d'humidité moyen | `avg(humidite_pct)` par campagne | `kpi.i11_humidite_moyenne` |
| 12 | Taux de grains défectueux | `avg(grains_defectueux_pct)` | `kpi.i12_grains_defectueux` |
| 13 | Part des lots de grade 1 | `100 × grade1 / lots_acceptés` | `kpi.i13_part_grade1` |
| 14 | Lots refusés par coopérative | `100 × refusés / analysés` par coopérative | `kpi.i14_refus_cooperative` |
| 15 | Délai d'analyse qualité | `avg(date_analyse − date_reception)` en jours | `kpi.i15_delai_analyse` |

## Page 4 · Prix et finances

| N° | Indicateur | Formule | Vue |
|---|---|---|---|
| 16 | Écart prix producteur / mondial | `prix_monde − prix_producteur` et `part = 100 × producteur / monde` | `kpi.i16_ecart_prix` |
| 17 | Évolution mensuelle du prix | variation `%` mois/mois (fenêtre `lag`) | `kpi.i17_evolution_prix` |
| 18 | Montant payé via Mobile Money | `sum(montant)` où `famille = mobile_money` | `kpi.i18_mobile_money` |
| 19 | Délai moyen de paiement | `avg(delai_jours)` sur paiements réussis | `kpi.i19_delai_paiement` |
| 20 | Impact du taux de change | `CA_usd × (taux_campagne − taux_référence)` | `kpi.i20_impact_change` |

## Page 5 · Logistique et export

| N° | Indicateur | Formule | Vue |
|---|---|---|---|
| 21 | Délai champ vers port | `avg(duree_min)/1440` en jours | `kpi.i21_delai_champ_port` |
| 22 | Coût de transport par tonne | `sum(distance_km) × 35 FCFA/km / (trajets × 20 t)` | `kpi.i22_cout_transport` |
| 23 | Taux de pertes en transport | `100 × sum(pertes) / sum(poids_départ)` | `kpi.i23_pertes_transport` |
| 24 | Conteneurs exportés | `sum(nb_conteneurs)` (EVP) | `kpi.i24_conteneurs` |
| 25 | Retards de chargement | `100 × escales non chargées / escales` + durée moyenne | `kpi.i25_retards_chargement` |

## Indicateur d'actualité (en-tête de chaque page)

| Indicateur | Formule | Vue |
|---|---|---|
| Date du dernier chargement | `max(fin)` de `etl.run_log` où `statut = SUCCESS` | `kpi.dernier_chargement` |

## Choix de modélisation documentés

- **Indicateur 2** : `fait_paiement` ne porte pas la livraison ; paiement et
  livraison sont agrégés par campagne (rapport de sommes, jamais moyenne de
  moyennes), ce qui reste fidèle à la définition.
- **Indicateur 11** : faute de poids au niveau du lot, l'humidité est moyennée
  uniformément sur les lots (`avg`).
- **Indicateur 20** : le taux USD/XAF est reconstruit depuis `fait_prix_marche`
  (`prix_fcfa / prix_usd`) ; la référence est la moyenne de la période.
- **Indicateur 22** : le coût facturé n'est pas dans la source ; proxy transparent
  = distance parcourue × 35 FCFA/km ÷ 20 t par camion (paramètres affichables).
- **Indicateur 16** : une `part_producteur_pct > 100 %` reflète une campagne où le
  prix producteur local dépasse le prix mondial moyen — signal à commenter en
  soutenance, pas à corriger.

## Vérification

```bash
psql -h localhost -p 5434 -U dwh -d dwh -f sql/dwh/05_indicateurs.sql
.venv/bin/python -m pytest tests/test_pipeline.py::TestIndicateurs -q
```
