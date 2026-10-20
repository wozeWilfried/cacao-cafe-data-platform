# Modèle dimensionnel — constellation cacao & café

Entrepôt `dwh` : **12 dimensions conformes** partagées par **9 tables de faits**.
Campagne commerciale : **1er octobre → 30 septembre**, portée par `dim_date`.

## Grains (un enregistrement = …)

| Fait | Grain | Justification |
|---|---|---|
| `fait_livraison` | Une livraison producteur → coopérative | Plus fin que le lot : tonnage par producteur, parcelle et jour ; cumulable à tout niveau |
| `fait_paiement` | Un paiement unitaire (rattaché à une livraison) | Délai et canal ne se calculent qu'à ce niveau ; statut conservé |
| `fait_qualite_lot` | Une analyse de lot | Humidité et défauts sont des mesures du lot ; observation conservée pour le NLP |
| `fait_transport` | Un trajet camion coopérative → port | ~600 000 pings GPS agrégés en ~15 000 trajets : durée, distance, pertes |
| `fait_export` | Une ligne de contrat expédiée | Volume/prix/montant par ligne ; conteneurs dérivés |
| `fait_prix_marche` | Un prix par jour, produit et source | Le jour est le plus petit dénominateur commun aux sources |
| `fait_meteo` | Un jour et un site climatique | Alimente les prévisions ; relié à la région via `dim_geographie` |
| `fait_intrants` | Une distribution d'intrant à un producteur | Relie intrants, rendement et coûts de la marge |
| `fait_trafic_port` | Un mouvement de conteneur / une escale | Mesure l'attente à quai et les retards de chargement |

## Dimensions et historisation

| Dimension | Clé naturelle | Type | Attributs |
|---|---|---|---|
| `dim_date` | date | générée | année, mois, trimestre, jour, campagne |
| `dim_produit` | code_produit | Type 1 | CACAO/CAFE, variété, famille |
| `dim_geographie` | code_localite | Type 1 | localité, département, région, lat/lon, station |
| `dim_cooperative` | cooperative_bk | **SCD2** | nom, région, capacité, responsable, certification |
| `dim_producteur` | producteur_bk | **SCD2** | nom, sexe, naissance, coopérative, certification, statut |
| `dim_parcelle` | parcelle_bk | Type 1 | producteur, culture, surface, géométrie |
| `dim_canal` | code_canal | Type 1 | MTN MoMo, Orange Money, virement, espèces |
| `dim_acheteur` | acheteur_bk | Type 1 | raison sociale, pays, type |
| `dim_transporteur` | transporteur_bk | Type 1 | société, camion, capacité |
| `dim_port` | code_port | Type 1 | Douala, Kribi, terminal |
| `dim_defaut` | code_defaut | Type 1 | moisissure, grains ardoisés, infestation… |
| `dim_intrant` | code_intrant | Type 1 | famille, nom, unité |

## Matrice processus × dimensions

| Fait ↓ / Dim → | date | produit | géo | coop | producteur | parcelle | canal | acheteur | transp. | port | défaut | intrant |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `fait_livraison`    | ● | ● | ○ | ● | ● | ● |   |   |   |   |   |   |
| `fait_paiement`     | ● |   |   | ● | ● |   | ● |   |   |   |   |   |
| `fait_qualite_lot`  | ● | ● |   | ● |   |   |   |   |   |   | ● |   |
| `fait_transport`    | ● |   |   | ● |   |   |   |   | ● | ● |   |   |
| `fait_export`       | ● | ● |   |   |   |   |   | ● |   | ● |   |   |
| `fait_prix_marche`  | ● | ● |   |   |   |   |   |   |   |   |   |   |
| `fait_meteo`        | ● |   | ● |   |   |   |   |   |   |   |   |   |
| `fait_intrants`     | ● |   |   | ● | ● |   |   |   |   |   |   | ● |
| `fait_trafic_port`  | ● |   |   |   |   |   |   |   |   | ● |   |   |

● clé étrangère obligatoire · ○ clé étrangère optionnelle

## Pourquoi le SCD2 sur producteur et coopérative ?

Un producteur qui change de coopérative ou obtient une certification ne doit pas
réécrire son historique : le tonnage d'avant reste attribué à l'ancienne
coopérative. Chaque fait pointe vers la **version valide à sa date** grâce à la
jointure `date_debut ≤ date ≤ date_fin`. Démontrable au run 2.
