"""Collecteur des sources publiques (7) : prix, production, météo, change.

Télécharge une fois chaque jeu public et dépose un fichier exploitable par l'ETL
dans data/inbox/public/. Un cache brut est gardé dans data/cache et un fichier de
repli permet de ne jamais dépendre d'Internet le jour de la démonstration
(en cas d'échec : lecture du repli + avertissement).

Sources prises en charge :
  - prix_monde     : World Bank Pink Sheet (cacao, café arabica, café robusta) ;
  - faostat        : production / superficie cacao & café par pays (CSV) ;
  - meteo_nasa     : NASA POWER (T2M, PRECTOTCORR) par station ;
  - meteo_openmeteo: Open-Meteo archive (température, pluie) par station ;
  - change         : Frankfurter (taux BCE), USD/XAF calculé via parité 655,957.

Exemples :
    python generate/sources_publiques.py --source change --debut 2024-01-01 --fin 2024-01-31
    python generate/sources_publiques.py --source meteo_openmeteo
    python generate/sources_publiques.py --source prix_monde
    python generate/sources_publiques.py --source tout
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .common import (
        CACHE_DIR,
        PAIRES_DEVISE,
        PUBLIC_DIR,
        STATIONS,
        ensure_dir,
    )
except ImportError:
    from common import (
        CACHE_DIR,
        PAIRES_DEVISE,
        PUBLIC_DIR,
        STATIONS,
        ensure_dir,
    )

# Parité fixe du franc CFA (XAF) vis-à-vis de l'euro.
XAF_PARITE = 655.957

# URL des ressources publiques (vérifiées le 20 octobre 2026).
URLS = {
    "pink_sheet": "https://thedocs.worldbank.org/en/doc/18675f1d1639c7a34d463f59263ba0a2-0050012025/related/CMO-Historical-Data-Monthly.xlsx",
    "faostat_crops": "https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip",
    "frankfurter": "https://api.frankfurter.dev/v1/{debut}..{fin}?base=EUR&symbols={symboles}",
    "openmeteo": ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
                  "&start_date={debut}&end_date={fin}"
                  "&daily=temperature_2m_mean,precipitation_sum&timezone=UTC"),
    "nasa": ("https://power.larc.nasa.gov/api/temporal/daily/point"
             "?parameters=T2M,PRECTOTCORR&community=AG&latitude={lat}&longitude={lon}"
             "&start={debut_compact}&end={fin_compact}&format=JSON"),
}


def _telecharger(url: str, cache_nom: str) -> bytes:
    """Télécharge (avec cache disque) ; lève si le réseau échoue."""
    cache = ensure_dir(CACHE_DIR) / cache_nom
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "p9-sources/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if cache.suffix == ".json":
            cache.write_bytes(data)
        else:
            cache.write_bytes(data)
        return data
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if cache.exists():
            print(f"    ! réseau indisponible, lecture du cache {cache.name}")
            return cache.read_bytes()
        raise SystemExit(f"    ! échec et pas de cache pour {cache_nom} : {exc}")


# ---------------------------------------------------------------------------
# 1. Prix mondiaux (World Bank Pink Sheet)
# ---------------------------------------------------------------------------
MARCHES_CACAO = [
    ("International Cocoa Organization daily price, average of the first three positions on the",
     "cacao"),
]


def collecter_prix_monde(debut: str, fin: str) -> Path:
    """Extrait cacao, café arabica et robusta du Pink Sheet vers un CSV long."""
    path = ensure_dir(PUBLIC_DIR) / "prix_marches_mondiaux.csv"
    if path.exists():
        path.unlink()  # rejouabilité : repart d'un fichier vide
    try:
        data = _telecharger(URLS["pink_sheet"], "CMO-Historical-Data-Monthly.xlsx")
        tmp = ensure_dir(CACHE_DIR) / "_pink.xlsx"
        tmp.write_bytes(data)
        from openpyxl import load_workbook

        wb = load_workbook(tmp, read_only=True, data_only=True)
        ws = wb["Monthly Prices"]
        # Détecter l'en-tête : ligne contenant 'Cocoa' et 'Coffee, Arabica'
        header_row, col_cacao, col_arabica, col_robusta = None, None, None, None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            labels = [str(c) if c else "" for c in row]
            if any("Cocoa" in l for l in labels) and header_row is None:
                header_row = i
                for j, l in enumerate(labels):
                    if l.startswith("Cocoa"):
                        col_cacao = j
                    if "Arabica" in l:
                        col_arabica = j
                    if "Robusta" in l:
                        col_robusta = j
            if header_row is not None and i > header_row:
                date_cell = row[0]
                if not date_cell:
                    continue
                # Pink Sheet : date en colonne A (mois/année), parfois '2024M01'.
                label = str(date_cell)
                if "M" in label:
                    annee, mois = label.split("M")
                    date_iso = f"{annee}-{int(mois):02d}-01"
                else:
                    continue
                rows = []
                for col, produit in ((col_cacao, "CACAO"), (col_arabica, "CAFE_ARABICA"),
                                     (col_robusta, "CAFE_ROBUSTA")):
                    val = row[col] if col is not None else None
                    if val not in (None, ""):
                        # Pink Sheet : colonnes déjà exprimées en $/kg.
                        rows.append((date_iso, produit, "USD/kg", round(float(val), 4)))
                if rows:
                    with path.open("a", encoding="utf-8", newline="") as fh:
                        w = csv.writer(fh)
                        w.writerows(rows)
        wb.close()
        # Réécrit proprement avec un seul en-tête (le flux d'ajout en a pu glisser un).
        rows_ok = [r for r in path.read_text(encoding="utf-8").splitlines()
                   if r and not r.startswith("date,")]
        path.write_text("date,produit,unite,prix\n" + "\n".join(rows_ok) + "\n", encoding="utf-8")
    except Exception as exc:  # repli : série synthétique documentée
        print(f"    ! Pink Sheet indisponible ({exc}); repli synthétique documenté")
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "produit", "unite", "prix"])
            w.writerow(["2024-01-01", "CACAO", "USD/kg", "4.2"])
    return path


# ---------------------------------------------------------------------------
# 2. FAOSTAT (production cacao & café)
# ---------------------------------------------------------------------------
FAOSTAT_ITEMS = {"Cocoa beans", "Coffee, green"}
FAOSTAT_ELEMENTS = {"Production", "Area harvested", "Yield"}


def collecter_faostat(debut: str, fin: str) -> Path:
    """Extrait production / superficie / rendement cacao & café par pays (CSV long).

    Le fichier FAOSTAT normalisé est volumineux (~545 Mo) : il est lu en flux
    depuis l'archive zip, sans tout charger en mémoire.
    """
    import io
    import zipfile

    path = ensure_dir(PUBLIC_DIR) / "faostat_production.csv"
    data = _telecharger(URLS["faostat_crops"], "faostat_crops.zip")
    zip_path = ensure_dir(CACHE_DIR) / "faostat_crops.zip"
    if not zip_path.exists():
        zip_path.write_bytes(data)
    membre = "Production_Crops_Livestock_E_All_Data_(Normalized).csv"

    lignes = []
    with zipfile.ZipFile(zip_path) as z, z.open(membre) as raw:
        txt = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace")
        lecteur = csv.DictReader(txt)
        for d in lecteur:
            if d.get("Item") in FAOSTAT_ITEMS and d.get("Element") in FAOSTAT_ELEMENTS:
                lignes.append((
                    d.get("Area"), d.get("Item"), d.get("Element"),
                    int(d["Year"]), d.get("Unit"),
                    float(d["Value"]) if d.get("Value") not in (None, "") else None,
                ))

    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pays", "produit", "element", "annee", "unite", "valeur"])
        w.writerows(lignes)
    return path


# ---------------------------------------------------------------------------
# 3. Change (Frankfurter + parité XAF)
# ---------------------------------------------------------------------------
def collecter_change(debut: str, fin: str) -> Path:
    path = ensure_dir(PUBLIC_DIR) / "taux_change.csv"
    symboles = ",".join(s for s in PAIRES_DEVISE if s != "XAF")
    url = URLS["frankfurter"].format(debut=debut, fin=fin, symboles=symboles)
    data = json.loads(_telecharger(url, f"frankfurter_{debut}_{fin}.json"))
    lignes = []
    for jour, rates in sorted(data.get("rates", {}).items()):
        for devise, taux in rates.items():
            lignes.append((jour, f"EUR/{devise}", round(taux, 6)))
        # USD/XAF : XAF = EUR * parité ; USD/XAF = parité / EUR/USD
        if "USD" in rates:
            lignes.append((jour, "USD/XAF", round(XAF_PARITE / rates["USD"], 4)))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "paire", "taux"])
        w.writerows(lignes)
    return path


# ---------------------------------------------------------------------------
# 4. Météo NASA POWER
# ---------------------------------------------------------------------------
def collecter_meteo_nasa(debut: str, fin: str) -> Path:
    path = ensure_dir(PUBLIC_DIR) / "meteo_nasa.csv"
    dc, fc = debut.replace("-", ""), fin.replace("-", "")
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["site", "date", "T2M", "PRECTOTCORR"])
        for site, lat, lon in STATIONS:
            url = URLS["nasa"].format(lat=lat, lon=lon, debut_compact=dc, fin_compact=fc)
            data = json.loads(_telecharger(url, f"nasa_{site}_{dc}_{fc}.json"))
            params = data["properties"]["parameter"]
            for jour in sorted(params["T2M"]):
                w.writerow([site, f"{jour[:4]}-{jour[4:6]}-{jour[6:]}",
                            params["T2M"][jour], params["PRECTOTCORR"][jour]])
    return path


# ---------------------------------------------------------------------------
# 5. Météo Open-Meteo
# ---------------------------------------------------------------------------
def collecter_meteo_openmeteo(debut: str, fin: str) -> Path:
    path = ensure_dir(PUBLIC_DIR) / "meteo_openmeteo.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["site", "date", "temperature", "pluie"])
        for site, lat, lon in STATIONS:
            url = URLS["openmeteo"].format(lat=lat, lon=lon, debut=debut, fin=fin)
            data = json.loads(_telecharger(url, f"openmeteo_{site}_{debut}_{fin}.json"))
            daily = data["daily"]
            for d, t, p in zip(daily["time"], daily["temperature_2m_mean"],
                               daily["precipitation_sum"]):
                w.writerow([site, d, t, p])
    return path


COLLECTEURS = {
    "prix_monde": collecter_prix_monde,
    "faostat": collecter_faostat,
    "change": collecter_change,
    "meteo_nasa": collecter_meteo_nasa,
    "meteo_openmeteo": collecter_meteo_openmeteo,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collecte les sources publiques.")
    parser.add_argument("--source", default="tout",
                        help="tout | " + " | ".join(COLLECTEURS))
    parser.add_argument("--debut", default="2022-10-01")
    parser.add_argument("--fin", default="2026-09-30")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = list(COLLECTEURS) if args.source == "tout" else [args.source]
    for nom in sources:
        if nom not in COLLECTEURS:
            raise SystemExit(f"Source inconnue : {nom}")
        print(f"  [{nom}] {args.debut} → {args.fin}")
        chemin = COLLECTEURS[nom](args.debut, args.fin)
        print(f"    -> {chemin} ({chemin.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())