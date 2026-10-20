-- =============================================================================
-- DWH — Seed des dimensions à valeurs fixes (référentiels du domaine).
-- Idempotent : ON CONFLICT (code) DO UPDATE.
-- =============================================================================
SET search_path = dwh, public;

-- Produits : cacao + cafés (dont séries Pink Sheet Arabica/Robusta).
INSERT INTO dwh.dim_produit (code_produit, libelle, famille, variete) VALUES
    ('CACAO',        'Cacao (fèves)', 'fève',      NULL),
    ('CAFE',         'Café vert',     'café vert', NULL),
    ('CAFE_ARABICA', 'Café Arabica',  'café vert', 'arabica'),
    ('CAFE_ROBUSTA', 'Café Robusta',  'café vert', 'robusta')
ON CONFLICT (code_produit) DO UPDATE SET libelle = EXCLUDED.libelle;

-- Canaux de paiement.
INSERT INTO dwh.dim_canal (code_canal, libelle, famille) VALUES
    ('MTN_MOMO',     'MTN Mobile Money', 'mobile_money'),
    ('ORANGE_MONEY', 'Orange Money',     'mobile_money'),
    ('VIREMENT',     'Virement bancaire','banque'),
    ('ESPECES',      'Espèces',          'especes')
ON CONFLICT (code_canal) DO UPDATE SET libelle = EXCLUDED.libelle;

-- Ports.
INSERT INTO dwh.dim_port (code_port, nom, terminal, pays) VALUES
    ('DOUALA', 'Port autonome de Douala', 'Terminal à conteneurs', 'Cameroun'),
    ('KRIBI',  'Port de Kribi',           'Terminal polyvalent',   'Cameroun')
ON CONFLICT (code_port) DO UPDATE SET nom = EXCLUDED.nom;

-- Défauts qualité.
INSERT INTO dwh.dim_defaut (code_defaut, libelle, famille, gravite) VALUES
    ('MOISISSURE',      'Présence de moisissure',   'champignon',     'MAJEUR'),
    ('GRAINS_ARDOISES', 'Grains ardoisés',          'fermentation',   'MAJEUR'),
    ('INFESTATION',     'Infestation d''insectes',  'insecte',        'MAJEUR'),
    ('HUMIDITE_ELEVEE', 'Humidité trop élevée',     'sechage',        'MAJEUR'),
    ('ODEUR_FUMEE',     'Odeur de fumée',           'traitement',     'MINEUR'),
    ('CORPS_ETRANGERS', 'Corps étrangers',          'matiere',        'MAJEUR')
ON CONFLICT (code_defaut) DO UPDATE SET libelle = EXCLUDED.libelle;

-- Intrants agricoles (codes alignés sur generate/intrants.py).
INSERT INTO dwh.dim_intrant (code_intrant, nom, famille, unite) VALUES
    ('INT-001', 'Engrais NPK 20-10-10 (sac 50 kg)', 'engrais', 'sac'),
    ('INT-002', 'Urée 46% (sac 50 kg)',             'engrais', 'sac'),
    ('INT-003', 'Sulfate de potasse (sac 50 kg)',   'engrais', 'sac'),
    ('INT-004', 'Fongicide cuprique (L)',           'phytosanitaire', 'litre'),
    ('INT-005', 'Insecticide (L)',                  'phytosanitaire', 'litre'),
    ('INT-006', 'Machette',                         'materiel', 'unité'),
    ('INT-007', 'Sécateur',                         'materiel', 'unité'),
    ('INT-008', 'Sac de jute (60 kg)',              'emballage', 'unité'),
    ('INT-009', 'Semence améliorée cacao (kg)',     'semence', 'kg'),
    ('INT-010', 'Semence améliorée café (kg)',      'semence', 'kg')
ON CONFLICT (code_intrant) DO UPDATE SET nom = EXCLUDED.nom;

-- Catégories de transporteurs (bk générique pour rattachement).
INSERT INTO dwh.dim_transporteur (transporteur_bk, societe, camion, capacite_t) VALUES
    ('TRP_INCONNU', 'Transporteur non identifié', NULL, NULL)
ON CONFLICT (transporteur_bk) DO UPDATE SET societe = EXCLUDED.societe;
