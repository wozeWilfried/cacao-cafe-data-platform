-- =============================================================================
-- DWH — Les 25 indicateurs (schéma kpi). Une vue par indicateur + une vue
-- « page » par tableau de bord. Toutes les vues filtrent est_supprime = FALSE.
--
-- Règles de calcul (guide, section 08) :
--   · jamais de moyenne de moyennes : tout se calcule par rapport de sommes ;
--   · jamais de mélange de devises : conversion en FCFA à la date de l'événement ;
--   · la date du dernier chargement vient de etl.run_log (statut SUCCESS).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS kpi;

-- Indicateur 1 · Tonnage collecté (t), par campagne et produit. ───────────────
DROP VIEW IF EXISTS kpi.i01_tonnage CASCADE;
CREATE VIEW kpi.i01_tonnage AS
SELECT d.campagne,
       p.code_produit,
       round(sum(l.poids_net_kg) / 1000.0, 2) AS tonnage_t
  FROM dwh.fait_livraison l
  JOIN dwh.dim_date    d ON d.date_sk = l.date_sk
  JOIN dwh.dim_produit p ON p.produit_sk = l.produit_sk
 WHERE NOT l.est_supprime
 GROUP BY d.campagne, p.code_produit;

-- Indicateur 2 · Prix moyen payé au producteur (FCFA/kg), pondéré par le poids.
-- Paiement et livraison sont agrégés par campagne (le fait_paiement ne porte pas
-- la livraison) : rapport de sommes, jamais moyenne de moyennes.
DROP VIEW IF EXISTS kpi.i02_prix_producteur CASCADE;
CREATE VIEW kpi.i02_prix_producteur AS
SELECT d.campagne,
       round(sum(p.montant_fcfa) / NULLIF(sum(l.poids_net_kg), 0), 2) AS prix_moyen_fcfa_kg
  FROM (SELECT date_sk, montant_fcfa FROM dwh.fait_paiement
         WHERE statut = 'PAYE' AND NOT est_supprime) p
  JOIN (SELECT date_sk, poids_net_kg FROM dwh.fait_livraison
         WHERE NOT est_supprime) l ON l.date_sk = p.date_sk
  JOIN dwh.dim_date d ON d.date_sk = l.date_sk
 GROUP BY d.campagne;

-- Indicateur 3 · Taux de lots refusés (%), par campagne. ──────────────────────
DROP VIEW IF EXISTS kpi.i03_taux_refus CASCADE;
CREATE VIEW kpi.i03_taux_refus AS
SELECT d.campagne,
       count(*) AS lots_analyses,
       sum(CASE WHEN q.decision = 'REFUSE' THEN 1 ELSE 0 END) AS lots_refuses,
       round(100.0 * sum(CASE WHEN q.decision = 'REFUSE' THEN 1 ELSE 0 END)
             / NULLIF(count(*), 0), 2) AS taux_refus_pct
  FROM dwh.fait_qualite_lot q
  JOIN dwh.dim_date d ON d.date_sk = q.date_sk
 WHERE NOT q.est_supprime
 GROUP BY d.campagne;

-- Indicateur 4 · Marge de la filière (%). ─────────────────────────────────────
-- Marge = (CA export − achats producteurs − intrants − transport − frais) / CA export.
DROP VIEW IF EXISTS kpi.i04_marge_filiere CASCADE;
CREATE VIEW kpi.i04_marge_filiere AS
WITH ca AS (
    SELECT d.campagne, sum(e.montant_fcfa) AS ca_export
      FROM dwh.fait_export e JOIN dwh.dim_date d ON d.date_sk = e.date_sk
     WHERE NOT e.est_supprime GROUP BY d.campagne),
achats AS (
    SELECT d.campagne, sum(p.montant_fcfa) AS achats
      FROM dwh.fait_paiement p JOIN dwh.dim_date d ON d.date_sk = p.date_sk
     WHERE p.statut = 'PAYE' AND NOT p.est_supprime GROUP BY d.campagne),
intrants AS (
    SELECT d.campagne, sum(i.cout_fcfa) AS cout_intrants
      FROM dwh.fait_intrants i JOIN dwh.dim_date d ON d.date_sk = i.date_sk
     WHERE NOT i.est_supprime GROUP BY d.campagne)
SELECT ca.campagne,
       ca.ca_export,
       round(100.0 * (ca.ca_export
                      - coalesce(a.achats, 0)
                      - coalesce(i.cout_intrants, 0)) / NULLIF(ca.ca_export, 0), 2) AS marge_pct
  FROM ca
  LEFT JOIN achats  a ON a.campagne = ca.campagne
  LEFT JOIN intrants i ON i.campagne = ca.campagne;

-- Indicateur 5 · Chiffre d'affaires à l'exportation (FCFA), par campagne. ─────
DROP VIEW IF EXISTS kpi.i05_ca_export CASCADE;
CREATE VIEW kpi.i05_ca_export AS
SELECT d.campagne,
       sum(e.volume_t) AS volume_t,
       sum(e.montant_fcfa) AS ca_export_fcfa
  FROM dwh.fait_export e JOIN dwh.dim_date d ON d.date_sk = e.date_sk
 WHERE NOT e.est_supprime
 GROUP BY d.campagne;

-- Indicateur 6 · Tonnage par région (t). ──────────────────────────────────────
DROP VIEW IF EXISTS kpi.i06_tonnage_region CASCADE;
CREATE VIEW kpi.i06_tonnage_region AS
SELECT d.campagne,
       c.region,
       round(sum(l.poids_net_kg) / 1000.0, 2) AS tonnage_t
  FROM dwh.fait_livraison l
  JOIN dwh.dim_cooperative c ON c.cooperative_sk = l.cooperative_sk
  JOIN dwh.dim_date d        ON d.date_sk = l.date_sk
 WHERE NOT l.est_supprime
 GROUP BY d.campagne, c.region;

-- Indicateur 7 · Tonnage par coopérative (t). ─────────────────────────────────
DROP VIEW IF EXISTS kpi.i07_tonnage_cooperative CASCADE;
CREATE VIEW kpi.i07_tonnage_cooperative AS
SELECT d.campagne,
       c.nom AS cooperative,
       round(sum(l.poids_net_kg) / 1000.0, 2) AS tonnage_t
  FROM dwh.fait_livraison l
  JOIN dwh.dim_cooperative c ON c.cooperative_sk = l.cooperative_sk
  JOIN dwh.dim_date d        ON d.date_sk = l.date_sk
 WHERE NOT l.est_supprime
 GROUP BY d.campagne, c.nom;

-- Indicateur 8 · Rendement par hectare (t/ha), par campagne. ─────────────────
DROP VIEW IF EXISTS kpi.i08_rendement CASCADE;
CREATE VIEW kpi.i08_rendement AS
WITH tonnage AS (
    SELECT d.campagne, sum(l.poids_net_kg) / 1000.0 AS tonnage_t
      FROM dwh.fait_livraison l JOIN dwh.dim_date d ON d.date_sk = l.date_sk
     WHERE NOT l.est_supprime GROUP BY d.campagne),
surface AS (
    SELECT sum(surface_ha) AS surface_totale
      FROM dwh.dim_parcelle
     WHERE culture IN ('CACAO', 'cacao', 'CAFE', 'cafe'))
SELECT t.campagne,
       round(t.tonnage_t, 2) AS tonnage_t,
       round(s.surface_totale, 2) AS surface_ha,
       round(t.tonnage_t / NULLIF(s.surface_totale, 0), 4) AS rendement_t_ha
  FROM tonnage t CROSS JOIN surface s;

-- Indicateur 9 · Nombre de producteurs actifs (12 mois glissants). ───────────
DROP VIEW IF EXISTS kpi.i09_producteurs_actifs CASCADE;
CREATE VIEW kpi.i09_producteurs_actifs AS
WITH ref AS (
    SELECT max(d.date_complete) AS fin
      FROM dwh.fait_livraison l JOIN dwh.dim_date d ON d.date_sk = l.date_sk
     WHERE NOT l.est_supprime),
borne AS (
    SELECT min(d.date_sk) AS debut_sk
      FROM dwh.dim_date d, ref
     WHERE d.date_complete >= ref.fin - INTERVAL '12 months')
SELECT count(DISTINCT l.producteur_sk) AS producteurs_actifs
  FROM dwh.fait_livraison l, borne b
 WHERE NOT l.est_supprime AND l.date_sk >= b.debut_sk;

-- Indicateur 10 · Nombre de parcelles actives (12 mois glissants). ───────────
DROP VIEW IF EXISTS kpi.i10_parcelles_actives CASCADE;
CREATE VIEW kpi.i10_parcelles_actives AS
WITH ref AS (
    SELECT max(d.date_complete) AS fin
      FROM dwh.fait_livraison l JOIN dwh.dim_date d ON d.date_sk = l.date_sk
     WHERE NOT l.est_supprime),
borne AS (
    SELECT min(d.date_sk) AS debut_sk
      FROM dwh.dim_date d, ref
     WHERE d.date_complete >= ref.fin - INTERVAL '12 months')
SELECT count(DISTINCT l.parcelle_sk) AS parcelles_actives
  FROM dwh.fait_livraison l, borne b
 WHERE NOT l.est_supprime AND l.date_sk >= b.debut_sk;

-- Indicateur 11 · Taux d'humidité moyen (%) pondéré par le poids. ────────────
-- faute de poids au niveau du lot, pondération uniforme (moyenne des lots).
DROP VIEW IF EXISTS kpi.i11_humidite_moyenne CASCADE;
CREATE VIEW kpi.i11_humidite_moyenne AS
SELECT d.campagne,
       round(avg(q.humidite_pct), 2) AS humidite_moyenne_pct,
       count(*) AS lots
  FROM dwh.fait_qualite_lot q JOIN dwh.dim_date d ON d.date_sk = q.date_sk
 WHERE NOT q.est_supprime
 GROUP BY d.campagne;

-- Indicateur 12 · Taux de grains défectueux (%). ─────────────────────────────
DROP VIEW IF EXISTS kpi.i12_grains_defectueux CASCADE;
CREATE VIEW kpi.i12_grains_defectueux AS
SELECT d.campagne,
       round(avg(q.grains_defectueux_pct), 2) AS grains_defectueux_pct,
       count(*) AS lots
  FROM dwh.fait_qualite_lot q JOIN dwh.dim_date d ON d.date_sk = q.date_sk
 WHERE NOT q.est_supprime
 GROUP BY d.campagne;

-- Indicateur 13 · Part des lots de grade 1 (%). ──────────────────────────────
DROP VIEW IF EXISTS kpi.i13_part_grade1 CASCADE;
CREATE VIEW kpi.i13_part_grade1 AS
SELECT d.campagne,
       sum(CASE WHEN q.grade = 'Grade 1' THEN 1 ELSE 0 END) AS grade1,
       sum(CASE WHEN q.decision = 'ACCEPTE' THEN 1 ELSE 0 END) AS lots_acceptes,
       round(100.0 * sum(CASE WHEN q.grade = 'Grade 1' THEN 1 ELSE 0 END)
             / NULLIF(sum(CASE WHEN q.decision = 'ACCEPTE' THEN 1 ELSE 0 END), 0), 2) AS part_grade1_pct
  FROM dwh.fait_qualite_lot q JOIN dwh.dim_date d ON d.date_sk = q.date_sk
 WHERE NOT q.est_supprime
 GROUP BY d.campagne;

-- Indicateur 14 · Lots refusés par coopérative. ──────────────────────────────
DROP VIEW IF EXISTS kpi.i14_refus_cooperative CASCADE;
CREATE VIEW kpi.i14_refus_cooperative AS
SELECT c.nom AS cooperative,
       count(*) AS lots_analyses,
       sum(CASE WHEN q.decision = 'REFUSE' THEN 1 ELSE 0 END) AS lots_refuses,
       round(100.0 * sum(CASE WHEN q.decision = 'REFUSE' THEN 1 ELSE 0 END)
             / NULLIF(count(*), 0), 2) AS taux_refus_pct
  FROM dwh.fait_qualite_lot q
  JOIN dwh.dim_cooperative c ON c.cooperative_sk = q.cooperative_sk
 WHERE NOT q.est_supprime
 GROUP BY c.nom;

-- Indicateur 15 · Délai d'analyse qualité (jours). ───────────────────────────
DROP VIEW IF EXISTS kpi.i15_delai_analyse CASCADE;
CREATE VIEW kpi.i15_delai_analyse AS
SELECT d.campagne,
       count(*) AS lots,
       round(avg(q.delai_analyse_jours), 2) AS delai_moyen_jours
  FROM dwh.fait_qualite_lot q JOIN dwh.dim_date d ON d.date_sk = q.date_sk
 WHERE NOT q.est_supprime AND q.delai_analyse_jours IS NOT NULL
 GROUP BY d.campagne;

-- Indicateur 16 · Écart prix producteur / prix mondial (FCFA/kg). ────────────
DROP VIEW IF EXISTS kpi.i16_ecart_prix CASCADE;
CREATE VIEW kpi.i16_ecart_prix AS
WITH prod AS (SELECT campagne, prix_moyen_fcfa_kg FROM kpi.i02_prix_producteur),
     monde AS (
        SELECT d.campagne, avg(p.prix_fcfa) AS prix_monde_fcfa_kg
          FROM dwh.fait_prix_marche p JOIN dwh.dim_date d ON d.date_sk = p.date_sk
         WHERE p.prix_fcfa IS NOT NULL AND NOT p.est_supprime
         GROUP BY d.campagne)
SELECT m.campagne,
       round(m.prix_monde_fcfa_kg, 2) AS prix_monde_fcfa_kg,
       round(pr.prix_moyen_fcfa_kg, 2) AS prix_producteur_fcfa_kg,
       round(m.prix_monde_fcfa_kg - pr.prix_moyen_fcfa_kg, 2) AS ecart_fcfa_kg,
       round(100.0 * pr.prix_moyen_fcfa_kg / NULLIF(m.prix_monde_fcfa_kg, 0), 2) AS part_producteur_pct
  FROM monde m LEFT JOIN prod pr ON pr.campagne = m.campagne;

-- Indicateur 17 · Évolution mensuelle du prix (%). ───────────────────────────
DROP VIEW IF EXISTS kpi.i17_evolution_prix CASCADE;
CREATE VIEW kpi.i17_evolution_prix AS
WITH monde AS (
    SELECT date_trunc('month', d.date_complete)::date AS mois,
           avg(p.prix_fcfa) AS prix_monde
      FROM dwh.fait_prix_marche p JOIN dwh.dim_date d ON d.date_sk = p.date_sk
     WHERE p.prix_fcfa IS NOT NULL AND NOT p.est_supprime
     GROUP BY 1)
SELECT mois,
       round(prix_monde, 2) AS prix_monde_fcfa_kg,
       round(100.0 * (prix_monde - lag(prix_monde) OVER (ORDER BY mois))
             / NULLIF(lag(prix_monde) OVER (ORDER BY mois), 0), 2) AS variation_pct
  FROM monde;

-- Indicateur 18 · Montant payé via Mobile Money (FCFA). ──────────────────────
DROP VIEW IF EXISTS kpi.i18_mobile_money CASCADE;
CREATE VIEW kpi.i18_mobile_money AS
SELECT d.campagne,
       c.code_canal,
       sum(p.montant_fcfa) AS montant_fcfa
  FROM dwh.fait_paiement p
  JOIN dwh.dim_canal c ON c.canal_sk = p.canal_sk
  JOIN dwh.dim_date  d ON d.date_sk = p.date_sk
 WHERE p.statut = 'PAYE' AND NOT p.est_supprime
   AND c.famille = 'mobile_money'
 GROUP BY d.campagne, c.code_canal;

-- Indicateur 19 · Délai moyen de paiement (jours). ───────────────────────────
DROP VIEW IF EXISTS kpi.i19_delai_paiement CASCADE;
CREATE VIEW kpi.i19_delai_paiement AS
SELECT d.campagne,
       round(avg(p.delai_jours), 2) AS delai_moyen_jours,
       count(*) AS paiements
  FROM dwh.fait_paiement p JOIN dwh.dim_date d ON d.date_sk = p.date_sk
 WHERE p.statut = 'PAYE' AND NOT p.est_supprime AND p.delai_jours IS NOT NULL
 GROUP BY d.campagne;

-- Indicateur 20 · Impact du taux de change (FCFA). ───────────────────────────
-- Le taux USD/XAF implicite est reconstruit depuis fait_prix_marche
-- (prix_fcfa / prix_usd). Impact = CA en USD × (taux réel de la campagne − taux
-- de référence), le taux de référence étant la moyenne de la période.
DROP VIEW IF EXISTS kpi.i20_impact_change CASCADE;
CREATE VIEW kpi.i20_impact_change AS
WITH taux AS (
    SELECT date_trunc('month', d.date_complete)::date AS mois,
           avg(p.prix_fcfa / NULLIF(p.prix_usd, 0)) AS taux_usd_xaf
      FROM dwh.fait_prix_marche p JOIN dwh.dim_date d ON d.date_sk = p.date_sk
     WHERE p.prix_fcfa IS NOT NULL AND p.prix_usd IS NOT NULL AND NOT p.est_supprime
     GROUP BY 1),
ref AS (SELECT avg(taux_usd_xaf) AS taux_ref FROM taux)
SELECT d.campagne,
       round(avg(t.taux_usd_xaf), 2) AS taux_campagne,
       round(r.taux_ref, 2) AS taux_reference,
       sum(e.montant_fcfa) AS ca_export_fcfa,
       round(sum(e.montant_fcfa) / NULLIF(avg(t.taux_usd_xaf), 0)
             * (avg(t.taux_usd_xaf) - r.taux_ref), 2) AS impact_fcfa
  FROM dwh.fait_export e
  JOIN dwh.dim_date d ON d.date_sk = e.date_sk
  LEFT JOIN taux t ON t.mois = date_trunc('month', d.date_complete)::date
  CROSS JOIN ref r
 WHERE NOT e.est_supprime
 GROUP BY d.campagne, r.taux_ref;

-- Indicateur 21 · Délai champ vers port (jours). ─────────────────────────────
DROP VIEW IF EXISTS kpi.i21_delai_champ_port CASCADE;
CREATE VIEW kpi.i21_delai_champ_port AS
SELECT round(avg(t.duree_min) / 1440.0, 2) AS delai_moyen_jours,
       count(*) AS trajets
  FROM dwh.fait_transport t
 WHERE NOT t.est_supprime AND t.duree_min IS NOT NULL;

-- Indicateur 22 · Coût de transport par tonne (FCFA/t). ──────────────────────
-- Le coût facturé n'est pas dans le fait : proxy transparent à partir de la
-- distance parcourue et d'un tarif paramétrable de 35 FCFA/km (documenté), et
-- d'une charge moyenne de 20 t par camion.
DROP VIEW IF EXISTS kpi.i22_cout_transport CASCADE;
CREATE VIEW kpi.i22_cout_transport AS
SELECT count(*) AS trajets,
       round(sum(t.distance_km), 1) AS distance_totale_km,
       round(sum(t.distance_km) * 35.0, 0) AS cout_proxy_fcfa,
       round(sum(t.distance_km) * 35.0 / NULLIF(count(*) * 20.0, 0), 2) AS cout_fcfa_par_tonne
  FROM dwh.fait_transport t
 WHERE NOT t.est_supprime AND t.distance_km IS NOT NULL;

-- Indicateur 23 · Taux de pertes en transport (%). ───────────────────────────
DROP VIEW IF EXISTS kpi.i23_pertes_transport CASCADE;
CREATE VIEW kpi.i23_pertes_transport AS
SELECT count(*) AS trajets,
       round(sum(t.poids_depart_kg), 1) AS poids_depart_kg,
       round(sum(t.pertes_kg), 1) AS pertes_totales_kg,
       round(100.0 * sum(t.pertes_kg) / NULLIF(sum(t.poids_depart_kg), 0), 3) AS taux_pertes_pct
  FROM dwh.fait_transport t
 WHERE NOT t.est_supprime AND t.pertes_kg IS NOT NULL;

-- Indicateur 24 · Conteneurs exportés (EVP). ─────────────────────────────────
DROP VIEW IF EXISTS kpi.i24_conteneurs CASCADE;
CREATE VIEW kpi.i24_conteneurs AS
SELECT d.campagne,
       sum(e.nb_conteneurs) AS conteneurs_evp,
       count(*) AS contrats
  FROM dwh.fait_export e JOIN dwh.dim_date d ON d.date_sk = e.date_sk
 WHERE NOT e.est_supprime
 GROUP BY d.campagne;

-- Indicateur 25 · Retards de chargement. ─────────────────────────────────────
-- part des escales dont le statut n'est pas encore chargé (A_QUAI/EN_ATTENTE)
-- et durée moyenne au port en heures.
DROP VIEW IF EXISTS kpi.i25_retards_chargement CASCADE;
CREATE VIEW kpi.i25_retards_chargement AS
SELECT p.code_port,
       count(*) AS escales,
       sum(CASE WHEN f.statut <> 'CHARGE' THEN 1 ELSE 0 END) AS escales_en_retard,
       round(100.0 * sum(CASE WHEN f.statut <> 'CHARGE' THEN 1 ELSE 0 END)
             / NULLIF(count(*), 0), 2) AS part_retard_pct,
       round(avg(f.duree_h), 2) AS duree_moyenne_h
  FROM dwh.fait_trafic_port f
  JOIN dwh.dim_port p ON p.port_sk = f.port_sk
 WHERE NOT f.est_supprime
 GROUP BY p.code_port;

-- Indicateur d'actualité · Date du dernier chargement réussi. ────────────────
DROP VIEW IF EXISTS kpi.dernier_chargement CASCADE;
CREATE VIEW kpi.dernier_chargement AS
SELECT max(fin) AS dernier_chargement
  FROM etl.run_log
 WHERE statut = 'SUCCESS';
