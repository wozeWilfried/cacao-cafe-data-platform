# ML et NLP (M6)

Trois modèles de machine learning et deux traitements de langage naturel
alimentent les pages du tableau de bord. Chaque fonctionnalité écrit son résultat
dans les schémas `ml` ou `nlp` et ses métriques d'évaluation dans
`ml.metrique_modele`, comparées à une référence quand elle existe (guide, section 09).

Tout est calculé par `ml/run.py::calculer()` (appelé par le DAG Airflow, tâche
`calcul_ml_nlp`), journalisé dans `etl.run_log` (`source_name = 'ml_nlp'`).

```
python -m ml.run          # calcule ML1-3 + NLP1-2 et affiche un récapitulatif
```

## ML 1 · Prévision des tonnages (page 1)

- **Objectif** : anticiper les tonnages mensuels par région et produit.
- **Référence** : valeur du même mois un an plus tôt (saisonnière naïve).
- **Modèle** : lissage exponentiel saisonnier ETS (statsmodels), repli tendance
  linéaire si la série est trop courte. Par série `région × produit`.
- **Évaluation** : validation à origine glissante, **MAPE** et **WAPE**.
- **Sortie** : `ml.prevision_tonnage` (horizon 6 mois, intervalle ±1,96 σ).

Résultat (dev) : MAPE moyen ≈ **23,8 %** contre **23,5 %** pour la référence
(gain ≈ −2,5 %). Le modèle **ne bat pas** la référence saisonnière naïve : c'est
un résultat documenté et accepté, la référence étant déjà forte sur une série
saisonnière courte.

## ML 2 · Prédiction du rejet d'un lot (page 3)

- **Objectif** : estimer la probabilité qu'un lot soit refusé au contrôle qualité.
- **Cible** : `est_refuse`. **Variables** : humidité, taux de grains défectueux,
  grains comptés, produit, région, mois, délai livraison→analyse. Le grade n'est
  **jamais** utilisé (c'est une conséquence de la décision).
- **Référence** : régression logistique. **Modèle** : forêt aléatoire.
- **Rejet rare (~5 %)** : poids de classes équilibrés, seuil choisi sur la courbe
  précision-rappel.
- **Évaluation** : découpage **temporel** (entraînement sur les anciennes
  campagnes, test sur la dernière) ; précision, rappel, F1 de la classe « refusé »,
  PR-AUC, matrice de confusion.
- **Sortie** : `ml.score_rejet_lot` (proba, classe prédite, seuil, modèle).

Résultat (dev) : taux de refus **5,6 %**. F1 ≈ **0,26–0,28**, PR-AUC ≈ **0,20–0,22**
(soit ≈ 4× la prévalence de 5,6 %). La logistique et la forêt donnent des scores
proches : avec deux mesures bruitées, la frontière log-linéaire suffit, la forêt
n'apporte pas de gain net.

> **Précaution (guide)** : le rejet est **généré de façon probabiliste** à partir
> de l'humidité et des défauts (seuils physiques adoucis par une loi logistique),
> et non par une règle exacte. Une règle déterministe rendrait le score parfait
> (fuite d'information) ; le corpus source le vérifie.

## ML 3 · Prévision du prix mondial et marge (page 4)

- **Objectif** : prévoir le prix mondial à 1–3 mois, puis simuler la marge de la
  filière sous scénarios.
- **Données** : `dwh.fait_prix_marche` mensuel (Pink Sheet) ; coûts issus des
  paiements (achats), intrants et transport.
- **Référence** : dernier prix observé (marche aléatoire). **Modèle** : ETS.
- **Évaluation** : MAE, RMSE, MAPE en validation glissante.
- **Scénarios** : prix mondial ± 10 %, change ± 5 %, transport + 15 %.
  Marge = CA export − (achats + intrants + transport + frais), en % du CA,
  calculée **en unitaire (FCFA/kg livré)** pour rester cohérente entre des faits
  d'échelles différentes.
- **Sorties** : `ml.prevision_prix`, `ml.scenario_marge`.

Résultat (dev) : ETS bat la référence sur le café arabica (MAPE 16,7 % vs 17,3 %)
mais pas sur le cacao (37,5 % vs 27,6 %) ni le robusta (67,6 % vs 38,3 %). Comme
le rappelle le guide, *un prix de marché est très difficile à prévoir : un modèle
qui ne bat pas la référence est acceptable s'il est mesuré et expliqué.*

Marge unitaire de base ≈ **28,8 %** (prix export 2 910 FCFA/kg, achat producteur
1 851 FCFA/kg, intrants ≈ 23, transport ≈ 24, frais 6 %). Scénarios :
prix −10 % et change −5 % → ≈ 17,7 % ; prix +10 % → ≈ 37,5 % ;
transport +15 % → ≈ 28,7 % (effet marginal, attendu).

## NLP 1 · Classification des défauts qualité (page 3)

- **Objectif** : transformer les remarques libres des analystes en types de
  défauts comptables (7 classes : moisissure, grains ardoisés, infestation,
  humidité élevée, odeur de fumée, corps étrangers, aucun défaut).
- **Données** : champ `observation` des contrôles qualité.
- **Méthode** : nettoyage (minuscules, accents), **TF-IDF** mots + paires de mots,
  régression logistique.
- **Jeu** : 3 000 observations pour l'entraînement, le reste pour l'évaluation.
- **Évaluation** : F1 macro, précision et rappel par classe, matrice de confusion.
- **Sortie** : `nlp.defaut_observation` (une ligne par défaut prédit avec proba ≥ 0,5).

Résultat (dev) : **F1 macro ≈ 0,93** (par classe : 0,89 à 0,95 ; « aucun défaut »
≈ 1,0). Le corpus source est volontairement difficile : ~10 gabarits par défaut,
vocabulaire partagé, fautes de frappe et **10–15 % de phrases multi-défauts**.

## NLP 2 · Extraction des clauses de contrats (page 5)

- **Objectif** : lire le texte libre des clauses d'un contrat XML et en extraire
  les engagements : date limite d'expédition, volume, incoterm, port, pénalité.
- **Méthode** : règles (regex) sur le texte libre ; normalisation des dates en ISO.
  Les balises structurées du contrat servent de **vérité terrain** pour mesurer
  l'extraction.
- **Évaluation** : précision, rappel et F1 par type d'entité.
- **Sortie** : `nlp.contrat_extraction`.

Résultat (dev) : **DATE_LIMITE 100 %**, **VOLUME_T 100 %**, **INCOTERM 100 %**,
**PORT ≈ 94 %** (le port peut être cité hors contexte d'embarquement). Le volume
est comparé avec une tolérance de ±2 % (le texte arrondit la valeur).

## Récapitulatif des métriques

| Fonctionnalité | Jeu | Métrique principale | Valeur (dev) |
|---|---|---|---|
| ML 1 tonnage | test | MAPE moyen (réf. saisonnière) | 23,8 % (23,5 %) |
| ML 2 rejet | test | F1 (réf. logistique) / PR-AUC | ≈ 0,27 / ≈ 0,21 |
| ML 3 prix | test | MAPE (réf. dernier prix) | variable selon produit |
| NLP 1 défauts | test | F1 macro | ≈ 0,93 |
| NLP 2 contrats | test | F1 par entité | 0,94 – 1,0 |

Toutes ces valeurs sont persistées dans `ml.metrique_modele` et exposées par les
pages du tableau de bord (badge de modèle + métriques + date de calcul).
