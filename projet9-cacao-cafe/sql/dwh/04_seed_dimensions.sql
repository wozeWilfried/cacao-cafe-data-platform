-- =============================================================================
-- DWH — Seed des dimensions à valeurs fixes (référentiels du domaine).
-- Idempotent : ON CONFLICT (code) DO UPDATE.
-- =============================================================================
SET search_path = dwh, public;

-- Produits : CACAO et CAFE.
INSERT INTO dwh.dim_produit (code_produit, libelle, famille, variete) VALUES
    ('CACAO', 'Cacao (fèves)',      'fève',      NULL),
    ('CAFE',  'Café vert',          'café vert', NULL)
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

-- Intrants agricoles.
INSERT INTO dwh.dim_intrant (code_intrant, nom, famille, unite) VALUES
    ('ENGRAIS_NPK', 'Engrais NPK 20-10-10', 'engrais',          'kg'),
    ('ENGRAIS_UREE','Urée 46%',             'engrais',          'kg'),
    ('FONGICIDE',   'Fongicide cuivre',     'phytosanitaire',   'L'),
    ('INSECTICIDE', 'Insecticide à base de pyrèthre', 'phytosanitaire', 'L'),
    ('SEMENCE',     'Semences sélectionnées','semence',         'kg'),
    ('SAC_JUTE',    'Sacs de jute',         'emballage',        'unite')
ON CONFLICT (code_intrant) DO UPDATE SET nom = EXCLUDED.nom;

-- Catégories de transporteurs (bk générique pour rattachement).
INSERT INTO dwh.dim_transporteur (transporteur_bk, societe, camion, capacite_t) VALUES
    ('TRP_INCONNU', 'Transporteur non identifié', NULL, NULL)
ON CONFLICT (transporteur_bk) DO UPDATE SET societe = EXCLUDED.societe;
