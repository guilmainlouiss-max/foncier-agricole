"""
Foncier Agricole Urbain — Backend FastAPI v2
Lance avec : python -m uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
import math
import json
import io
import urllib.parse
from pathlib import Path
from datetime import date as date_cls

app = FastAPI(title="Foncier Agricole Urbain API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fanciful-peony-47e4e2.netlify.app",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════════
#  TYPES DE PROJETS
# ════════════════════════════════════════════════════════

TYPES_PROJETS = {
    "plein_sol": {"label": "Culture en plein sol", "icone": "🌱", "description": "Cultures directement dans le sol en place"},
    "bac": {"label": "Culture en bac / hors-sol", "icone": "📦", "description": "Cultures sur substrat isolé du sol (bacs, containers, tables de culture)"},
    "toiture": {"label": "Toiture / rooftop", "icone": "🏗️", "description": "Agriculture sur toit-terrasse ou toiture accessible"},
    "serre": {"label": "Serre chauffée", "icone": "🌿", "description": "Production sous serre avec apport de chaleur"},
    "facade": {"label": "Mur végétal / façade", "icone": "🧱", "description": "Végétalisation de façade ou mur végétal productif"},
}

# ════════════════════════════════════════════════════════
#  LOGIQUE POLLUTION
# ════════════════════════════════════════════════════════

def analyser_pollution(sites: list) -> dict:
    if not sites:
        return {
            "resume": "Aucun site pollué détecté dans un rayon de 2 km",
            "niveau_global": "ok",
            "impact_par_projet": {k: {"niveau": "ok", "texte": "Aucune contrainte pollution"} for k in TYPES_PROJETS},
            "distance_m": None, "site_proche": None,
        }
    site = sites[0]["properties"]
    dist = site["distance_m"]
    rayon = site["rayon_m"]
    famille = (site.get("famille") or "").lower()
    statut = (site.get("statut") or "").lower()
    nom = site.get("nom", "Site inconnu")

    est_metaux = any(m in famille for m in ["métal", "metal", "plomb", "zinc", "arsenic", "chrome", "cadmium", "revêtement"])
    est_hydrocarbure = any(m in famille for m in ["hydrocarbure", "carburant", "station service", "pétrole", "btex"])
    est_amiante = "amiante" in famille
    est_traite = "libre" in statut and ("traité" in statut or "validé" in statut)
    dans_zone = dist < rayon

    impacts = {}
    if est_traite:
        impacts["plein_sol"] = {"niveau": "warn", "texte": f"Site traité à {dist} m — Étude pédologique conseillée"}
        for k in ["bac", "toiture", "serre", "facade"]:
            impacts[k] = {"niveau": "ok", "texte": f"Site traité à {dist} m — Pas de contrainte pour ce type"}
        niveau_global, resume = "warn", f"Site traité à {dist} m — Étude pédologique conseillée pour culture en sol"
    elif est_amiante and dans_zone:
        impacts["plein_sol"] = {"niveau": "danger", "texte": f"⛔ Amiante détecté à {dist} m — Culture en sol INTERDITE"}
        impacts["bac"] = {"niveau": "danger", "texte": f"⛔ Amiante à {dist} m — Risque poussières, culture en bac DÉCONSEILLÉE"}
        for k in ["toiture", "serre", "facade"]:
            impacts[k] = {"niveau": "warn", "texte": f"Amiante à {dist} m — Vérifier contamination aérienne"}
        niveau_global, resume = "danger", f"⛔ Site amianté « {nom} » à {dist} m — Contraintes majeures"
    elif est_metaux and dans_zone:
        impacts["plein_sol"] = {"niveau": "danger", "texte": f"⛔ Métaux lourds à {dist} m — Culture en sol INTERDITE"}
        impacts["bac"] = {"niveau": "warn", "texte": f"Métaux lourds à {dist} m — Bac étanche possible, substrat certifié requis"}
        for k in ["toiture", "serre", "facade"]:
            impacts[k] = {"niveau": "ok", "texte": "Pollution au sol sans impact pour ce type de projet"}
        niveau_global, resume = "danger", f"⛔ Métaux lourds « {nom} » à {dist} m — Culture en sol interdite"
    elif est_hydrocarbure and dans_zone:
        impacts["plein_sol"] = {"niveau": "danger", "texte": f"⛔ Hydrocarbures à {dist} m — Culture en sol INTERDITE"}
        impacts["bac"] = {"niveau": "warn", "texte": f"Hydrocarbures à {dist} m — Vérifier absence de vapeurs"}
        impacts["serre"] = {"niveau": "warn", "texte": f"Hydrocarbures à {dist} m — Vérifier ventilation serre"}
        for k in ["toiture", "facade"]:
            impacts[k] = {"niveau": "ok", "texte": "Pollution au sol sans impact pour ce type de projet"}
        niveau_global, resume = "danger", f"⛔ Hydrocarbures « {nom} » à {dist} m — Culture en sol interdite"
    elif dans_zone:
        impacts["plein_sol"] = {"niveau": "danger", "texte": f"⛔ Site pollué « {nom} » à {dist} m — Culture en sol DÉCONSEILLÉE"}
        impacts["bac"] = {"niveau": "warn", "texte": f"Site pollué à {dist} m — Étude de risque recommandée"}
        for k in ["toiture", "serre", "facade"]:
            impacts[k] = {"niveau": "ok", "texte": "Pollution au sol sans impact direct pour ce type"}
        niveau_global, resume = "warn", f"Site pollué « {nom} » à {dist} m — Précautions requises"
    else:
        msg = f"Site pollué « {nom} » à {dist} m (hors zone d'exclusion)"
        impacts = {k: {"niveau": "ok", "texte": msg} for k in TYPES_PROJETS}
        impacts["plein_sol"] = {"niveau": "warn", "texte": f"{msg} — Étude pédologique conseillée"}
        niveau_global, resume = "warn", msg

    return {"resume": resume, "niveau_global": niveau_global, "impact_par_projet": impacts,
            "distance_m": dist, "site_proche": {"nom": nom, "statut": site.get("statut"), "famille": site.get("famille")}}


# ════════════════════════════════════════════════════════
#  LOGIQUE ENSOLEILLEMENT
# ════════════════════════════════════════════════════════

def analyser_ensoleillement(kwh: int) -> dict:
    impacts = {}
    if kwh >= 1200:
        impacts["plein_sol"] = {"niveau": "ok", "texte": f"Bon ensoleillement ({kwh} kWh/m²/an) — Cultures en plein air viables"}
    elif kwh >= 900:
        impacts["plein_sol"] = {"niveau": "warn", "texte": f"Ensoleillement moyen ({kwh} kWh/m²/an) — Espèces peu exigeantes uniquement"}
    else:
        impacts["plein_sol"] = {"niveau": "danger", "texte": f"Ensoleillement insuffisant ({kwh} kWh/m²/an) — Plein sol déconseillé"}
    impacts["bac"] = impacts["plein_sol"].copy()
    if kwh >= 1100:
        impacts["toiture"] = {"niveau": "ok", "texte": f"Ensoleillement favorable ({kwh} kWh/m²/an) — À confirmer par étude LiDAR"}
    elif kwh >= 900:
        impacts["toiture"] = {"niveau": "warn", "texte": f"Ensoleillement à vérifier ({kwh} kWh/m²/an) — Étude LiDAR recommandée"}
    else:
        impacts["toiture"] = {"niveau": "warn", "texte": f"Ensoleillement faible ({kwh} kWh/m²/an) — Masques importants probables"}
    if kwh >= 1000:
        impacts["serre"] = {"niveau": "ok", "texte": f"Ensoleillement suffisant ({kwh} kWh/m²/an) — Éclairage d'appoint limité"}
    else:
        impacts["serre"] = {"niveau": "warn", "texte": f"Ensoleillement faible ({kwh} kWh/m²/an) — Éclairage artificiel à prévoir"}
    impacts["facade"] = {"niveau": "warn", "texte": "Ensoleillement façade dépend de l'orientation — Étude spécifique requise"}
    return impacts


# ════════════════════════════════════════════════════════
#  LOGIQUE CHALEUR
# ════════════════════════════════════════════════════════

def analyser_chaleur(features_ch: list) -> dict:
    impacts = {}
    if not features_ch:
        impacts["serre"] = {"niveau": "warn", "texte": "Aucun réseau de chaleur dans un rayon de 2 km — Chauffage autonome à prévoir"}
        for k in ["plein_sol", "bac", "toiture", "facade"]:
            impacts[k] = {"niveau": "ok", "texte": "Réseau de chaleur non nécessaire pour ce type de projet"}
        return impacts
    dist = features_ch[0]["properties"].get("distance_m", 9999)
    nom = features_ch[0]["properties"].get("nom_reseau", features_ch[0]["properties"].get("nom", "Réseau local"))
    if dist < 100:
        impacts["serre"] = {"niveau": "ok", "texte": f"Réseau « {nom} » à {dist} m — Raccordement très probable, atout majeur"}
    elif dist < 500:
        impacts["serre"] = {"niveau": "ok", "texte": f"Réseau « {nom} » à {dist} m — Extension envisageable"}
    elif dist < 1500:
        impacts["serre"] = {"niveau": "warn", "texte": f"Réseau « {nom} » à {dist} m — Extension coûteuse, étudier alternatives"}
    else:
        impacts["serre"] = {"niveau": "warn", "texte": f"Réseau le plus proche à {dist} m — Chauffage autonome à prévoir"}
    for k in ["plein_sol", "bac", "toiture", "facade"]:
        impacts[k] = {"niveau": "ok", "texte": "Réseau de chaleur non critique pour ce type de projet"}
    return impacts


# ════════════════════════════════════════════════════════
#  LOGIQUE PLU
# ════════════════════════════════════════════════════════

def analyser_plu(type_zone: str, libelle: str) -> dict:
    z = type_zone.upper()
    impacts = {}
    if z.startswith("N"):
        impacts["plein_sol"] = {"niveau": "ok", "texte": f"Zone {z} — Agriculture en plein sol autorisée"}
        impacts["bac"] = {"niveau": "ok", "texte": f"Zone {z} — Culture en bac généralement autorisée"}
        impacts["toiture"] = {"niveau": "danger", "texte": f"Zone {z} — Constructions en toiture très limitées"}
        impacts["serre"] = {"niveau": "warn", "texte": f"Zone {z} — Serre soumise à autorisation spéciale"}
        impacts["facade"] = {"niveau": "warn", "texte": f"Zone {z} — Végétalisation façade à vérifier"}
    elif z.startswith("A") and not z.startswith("AU"):
        for k in TYPES_PROJETS:
            impacts[k] = {"niveau": "ok", "texte": f"Zone agricole ({z}) — Usage agricole autorisé par nature"}
    elif z.startswith("AU"):
        for k in TYPES_PROJETS:
            impacts[k] = {"niveau": "warn", "texte": f"Zone à urbaniser ({z}) — Règlement en cours, consulter la mairie"}
    elif z in ("UA", "UB", "UC", "UD", "UM", "U"):
        impacts["plein_sol"] = {"niveau": "warn", "texte": f"Zone urbaine ({z}) — Agriculture en sol à vérifier selon règlement local"}
        impacts["bac"] = {"niveau": "ok", "texte": f"Zone urbaine ({z}) — Culture en bac généralement compatible"}
        impacts["toiture"] = {"niveau": "ok", "texte": f"Zone urbaine ({z}) — Toiture agricole généralement compatible"}
        impacts["serre"] = {"niveau": "ok", "texte": f"Zone urbaine ({z}) — Serre en toiture à vérifier (surcharge)"}
        impacts["facade"] = {"niveau": "ok", "texte": f"Zone urbaine ({z}) — Mur végétal généralement autorisé"}
    elif z in ("UE", "UI", "UX", "UZ"):
        impacts["plein_sol"] = {"niveau": "danger", "texte": f"Zone économique ({z}) — Usage agricole au sol généralement interdit"}
        impacts["bac"] = {"niveau": "warn", "texte": f"Zone économique ({z}) — À vérifier selon règlement"}
        impacts["toiture"] = {"niveau": "ok", "texte": f"Zone économique ({z}) — Toiture agricole souvent possible"}
        impacts["serre"] = {"niveau": "warn", "texte": f"Zone économique ({z}) — Serre à vérifier"}
        impacts["facade"] = {"niveau": "ok", "texte": f"Zone économique ({z}) — Façade généralement possible"}
    else:
        for k in TYPES_PROJETS:
            impacts[k] = {"niveau": "warn", "texte": f"Zone {z} — Consulter le règlement local"}
    return impacts


# ════════════════════════════════════════════════════════
#  LOGIQUE PLUIE / CLIMAT
# ════════════════════════════════════════════════════════

def analyser_pluie(mm_an: float) -> dict:
    if mm_an >= 900:
        niveau, label = "ok", f"Pluviométrie abondante ({round(mm_an)} mm/an)"
        details = {"plein_sol": "Arrosage naturel très favorable — drainage à prévoir", "bac": "Arrosage naturel possible — prévoir drainage", "toiture": "Récupération eaux pluviales très rentable", "serre": "Ressource en eau abondante", "facade": "Arrosage naturel partiel, attention aux excès"}
    elif mm_an >= 600:
        niveau, label = "ok", f"Pluviométrie correcte ({round(mm_an)} mm/an)"
        details = {"plein_sol": "Arrosage d'appoint utile en été", "bac": "Arrosage régulier requis en période sèche", "toiture": "Récupération eaux pluviales intéressante", "serre": "Arrosage d'appoint à prévoir en été", "facade": "Arrosage d'appoint en période sèche"}
    elif mm_an >= 400:
        niveau, label = "warn", f"Pluviométrie modérée ({round(mm_an)} mm/an)"
        details = {"plein_sol": "Arrosage régulier indispensable — goutte-à-goutte recommandé", "bac": "Arrosage fréquent requis", "toiture": "Récupération d'eau recommandée", "serre": "Système d'arrosage automatique recommandé", "facade": "Arrosage automatique recommandé"}
    else:
        niveau, label = "warn", f"Pluviométrie faible ({round(mm_an)} mm/an)"
        details = {"plein_sol": "Arrosage intensif indispensable — zone sèche", "bac": "Arrosage très fréquent requis", "toiture": "Récupération d'eau prioritaire", "serre": "Irrigation automatique obligatoire", "facade": "Irrigation automatique obligatoire"}
    return {
        "mm_an": round(mm_an), "niveau": niveau, "label": label,
        "impact_par_projet": {k: {"niveau": niveau, "texte": details[k]} for k in TYPES_PROJETS}
    }


def interpreter_climat(t_moy: float, jours_gel: int, jours_saison: int) -> dict:
    if jours_gel < 20 and t_moy > 13:
        return {"zone": "Méditerranéenne", "label": "Climat favorable", "detail": "Longue saison de culture, gel rare — cultures subtropicales possibles"}
    elif jours_gel < 40 and jours_saison > 270:
        return {"zone": "Océanique", "label": "Climat favorable", "detail": "Saison longue, hivers doux — polyculture maraîchère possible toute l'année"}
    elif jours_gel < 70 and jours_saison > 230:
        return {"zone": "Semi-continental", "label": "Climat correct", "detail": "Saison correcte, gels hivernaux — protection nécessaire de novembre à mars"}
    elif jours_gel < 100:
        return {"zone": "Continental", "label": "Climat contraignant", "detail": "Hivers froids, saison courte — serre ou tunnel recommandés"}
    else:
        return {"zone": "Montagnard", "label": "Climat difficile", "detail": "Gels fréquents, saison très courte — serre chauffée indispensable"}


# ════════════════════════════════════════════════════════
#  MOTEUR DE RECOMMANDATION
# ════════════════════════════════════════════════════════

NIVEAU_SCORE = {"ok": 100, "warn": 50, "danger": 0}

def calculer_score_projet(type_projet, pollution, ensoleillement, chaleur, plu, pluie):
    criteres = {
        "pollution": pollution["impact_par_projet"][type_projet],
        "ensoleillement": ensoleillement[type_projet],
        "plu": plu[type_projet],
        "chaleur": chaleur[type_projet],
        "pluie": pluie["impact_par_projet"][type_projet],
    }
    poids = {
        "plein_sol": {"pollution": 0.40, "ensoleillement": 0.25, "plu": 0.20, "chaleur": 0.05, "pluie": 0.10},
        "bac":       {"pollution": 0.25, "ensoleillement": 0.25, "plu": 0.20, "chaleur": 0.05, "pluie": 0.10},
        "toiture":   {"pollution": 0.05, "ensoleillement": 0.35, "plu": 0.30, "chaleur": 0.10, "pluie": 0.10},
        "serre":     {"pollution": 0.10, "ensoleillement": 0.20, "plu": 0.20, "chaleur": 0.35, "pluie": 0.05},
        "facade":    {"pollution": 0.05, "ensoleillement": 0.35, "plu": 0.30, "chaleur": 0.05, "pluie": 0.10},
    }.get(type_projet, {"pollution": 0.25, "ensoleillement": 0.25, "plu": 0.25, "chaleur": 0.15, "pluie": 0.10})

    score = sum(NIVEAU_SCORE[criteres[k]["niveau"]] * poids[k] for k in criteres)
    score = round(score)
    bloquants = [c for c in criteres if criteres[c]["niveau"] == "danger"]
    if bloquants:
        score = min(score, 30)

    if score >= 70:
        verdict, couleur = "Recommandé", "#22c55e"
    elif score >= 40:
        verdict, couleur = "Envisageable", "#f59e0b"
    else:
        verdict, couleur = "Déconseillé", "#ef4444"

    if bloquants:
        verdict, couleur = "Déconseillé", "#ef4444"

    return {
        "type": type_projet,
        "label": TYPES_PROJETS[type_projet]["label"],
        "icone": TYPES_PROJETS[type_projet]["icone"],
        "description": TYPES_PROJETS[type_projet]["description"],
        "score": score, "verdict": verdict, "couleur": couleur,
        "criteres": [
            {"nom": "Pollution", "niveau": criteres["pollution"]["niveau"], "texte": criteres["pollution"]["texte"]},
            {"nom": "Ensoleillement", "niveau": criteres["ensoleillement"]["niveau"], "texte": criteres["ensoleillement"]["texte"]},
            {"nom": "Zonage PLU", "niveau": criteres["plu"]["niveau"], "texte": criteres["plu"]["texte"]},
            {"nom": "Réseau de chaleur", "niveau": criteres["chaleur"]["niveau"], "texte": criteres["chaleur"]["texte"]},
            {"nom": "Pluviométrie", "niveau": criteres["pluie"]["niveau"], "texte": criteres["pluie"]["texte"]},
        ]
    }


# ════════════════════════════════════════════════════════
#  ENDPOINT 1 — Pollution (Géorisques SSP/CASIAS)
# ════════════════════════════════════════════════════════

@app.get("/api/pollution")
async def get_pollution(lat: float = Query(...), lng: float = Query(...), rayon: int = Query(2000)):
    url = "https://www.georisques.gouv.fr/api/v1/ssp/casias"
    params = {"rayon": rayon, "latlon": f"{lng},{lat}", "page": 1, "page_size": 50}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=str(e))

    raw = resp.json()
    features = []
    for site in raw.get("data", []):
        geom = site.get("geom", {})
        if not geom:
            continue
        try:
            c = geom["coordinates"][0][0][0]
            lon, lat_s = c[0], c[1]
        except (KeyError, IndexError, TypeError):
            continue
        etat = site.get("statut", "")
        famille = site.get("activite_principale") or ""
        rayon_m = estimer_rayon_exclusion(etat, famille)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat_s]},
            "properties": {
                "id": site.get("identifiant_ssp", ""),
                "nom": site.get("nom_etablissement", "Site inconnu"),
                "adresse": site.get("adresse", ""),
                "commune": site.get("nom_commune", ""),
                "statut": etat, "famille": famille,
                "rayon_m": rayon_m,
                "distance_m": round(haversine(lat, lng, lat_s, lon)),
            }
        })
    features.sort(key=lambda f: f["properties"]["distance_m"])
    return {"type": "FeatureCollection", "features": features,
            "meta": {"total": raw.get("results", len(features)), "source": "Géorisques SSP CASIAS"}}


def estimer_rayon_exclusion(etat, famille):
    etat_lower = (etat or "").lower()
    famille_lower = (famille or "").lower()
    if "libre" in etat_lower and "traité" in etat_lower: return 30
    if "amiante" in famille_lower: return 300
    if "déchets" in famille_lower: return 200
    if "hydrocarbure" in famille_lower or "solvant" in famille_lower: return 150
    if "metal" in famille_lower or "métal" in famille_lower: return 100
    return 80


# ════════════════════════════════════════════════════════
#  ENDPOINT 2 — Ensoleillement (PVGIS / JRC)
# ════════════════════════════════════════════════════════

@app.get("/api/ensoleillement")
async def get_ensoleillement(lat: float = Query(...), lng: float = Query(...)):
    url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
    params = {"lat": lat, "lon": lng, "peakpower": 1, "loss": 14, "outputformat": "json", "browser": 0}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))
    raw = resp.json()
    try:
        e_year = raw["outputs"]["totals"]["fixed"]["E_y"]
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"kwh_m2_an": round(e_year), "source": "PVGIS v5.2 — JRC"}


# ════════════════════════════════════════════════════════
#  ENDPOINT 3 — Réseaux de chaleur (fichier local GeoJSON)
# ════════════════════════════════════════════════════════

_chaleur_cache = None
CHALEUR_GEOJSON_FILE = Path(__file__).parent / "reseaux-de-chaleur.geojson"


async def charger_chaleur():
    global _chaleur_cache
    if _chaleur_cache is not None:
        return _chaleur_cache
    try:
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
        with open(CHALEUR_GEOJSON_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for feature in data.get("features", []):
            geom = feature.get("geometry", {})
            if not geom:
                continue
            coords = geom.get("coordinates", [])
            if geom["type"] == "Point":
                lon, lat_c = transformer.transform(coords[0], coords[1])
                geom["coordinates"] = [lon, lat_c]
            elif geom["type"] == "MultiPoint":
                geom["coordinates"] = [list(transformer.transform(c[0], c[1])) for c in coords]
            if "crs" in geom:
                del geom["crs"]
        _chaleur_cache = data
    except Exception as e:
        _chaleur_cache = {"type": "FeatureCollection", "features": [], "error": str(e)}
    return _chaleur_cache


@app.get("/api/chaleur")
async def get_chaleur(lat: float = Query(...), lng: float = Query(...), rayon: int = Query(2000)):
    geojson = await charger_chaleur()
    features_proches = []
    for f in geojson.get("features", []):
        geom = f.get("geometry", {})
        if not geom:
            continue
        coords = geom.get("coordinates", [])
        if not coords:
            continue
        try:
            if geom["type"] == "Point":
                lon_r, lat_r = coords[0], coords[1]
            elif geom["type"] == "MultiPoint":
                lon_r, lat_r = coords[0][0], coords[0][1]
            else:
                continue
        except (IndexError, TypeError):
            continue
        dist = haversine(lat, lng, lat_r, lon_r)
        if dist <= rayon:
            f["properties"]["distance_m"] = round(dist)
            features_proches.append(f)
    features_proches.sort(key=lambda f: f["properties"].get("distance_m", 9999))
    return {"type": "FeatureCollection", "features": features_proches[:20],
            "meta": {"total_france": len(geojson.get("features", [])), "dans_rayon": len(features_proches)}}


# ════════════════════════════════════════════════════════
#  ENDPOINT 4 — PLU (API Carto IGN)
# ════════════════════════════════════════════════════════

@app.get("/api/plu")
async def get_plu(lat: float = Query(...), lng: float = Query(...)):
    geom = {"type": "Point", "coordinates": [lng, lat]}
    geom_str = urllib.parse.quote(json.dumps(geom))
    url = f"https://apicarto.ign.fr/api/gpu/zone-urba?geom={geom_str}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            return {"type_zone": "inconnu", "libelle": "", "score": 50, "verdict": "Erreur", "url_reglement": ""}
    raw = resp.json()
    features = raw.get("features", [])
    if not features:
        return {"type_zone": "inconnu", "libelle": "Aucun zonage trouvé", "score": 50, "verdict": "À vérifier", "url_reglement": ""}
    props = features[0]["properties"]
    type_zone = props.get("typezone", "?")
    libelle = props.get("libelong", props.get("libelle", ""))
    insee = props.get("partition", "") or ""
    code_insee = insee.replace("DU_", "") if insee.startswith("DU_") else ""
    url_reglement = f"https://www.geoportail-urbanisme.gouv.fr/map/#tile=1&lon={lng}&lat={lat}&zoom=16&mlon={lng}&mlat={lat}"
    return {"type_zone": type_zone, "libelle": libelle, "url_reglement": url_reglement, "source": "API Carto IGN"}


def scorer_plu(type_zone: str, libelle: str) -> dict:
    z = type_zone.upper()
    if z.startswith("N"):
        return {"score": 30, "verdict": "Contraignant", "detail": "Zone naturelle — serres soumises à autorisation spéciale"}
    if z.startswith("A") and not z.startswith("AU"):
        return {"score": 65, "verdict": "Favorable (plein air)", "detail": "Zone agricole — usage agricole autorisé par nature"}
    if z.startswith("AU"):
        return {"score": 45, "verdict": "Incertain", "detail": "Zone à urbaniser — consulter la mairie"}
    if z in ("UA", "UB", "UC", "UD", "UM", "U"):
        return {"score": 80, "verdict": "Compatible (toiture/façade)", "detail": f"Zone urbaine ({z}) — agriculture en toiture compatible"}
    if z in ("UE", "UI", "UX", "UZ"):
        return {"score": 55, "verdict": "Partiel", "detail": f"Zone économique ({z}) — toiture possible, sol agricole souvent interdit"}
    if z.startswith("UP") or z.startswith("UT"):
        return {"score": 50, "verdict": "À négocier", "detail": "Zone de projet — opportunité à négocier dès la conception"}
    return {"score": 50, "verdict": "Inconnu", "detail": f"Type de zone {z} — consulter le règlement local"}


# ════════════════════════════════════════════════════════
#  ENDPOINT 5 — Pluie + Climat (Open-Meteo)
# ════════════════════════════════════════════════════════

@app.get("/api/pluie")
async def get_pluie(lat: float = Query(...), lng: float = Query(...)):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat, "longitude": lng,
        "start_date": "2018-01-01", "end_date": "2023-12-31",
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,temperature_2m_mean",
        "timezone": "Europe/Paris",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    raw = resp.json()
    try:
        daily = raw["daily"]
        dates = daily["time"]
        precipitations = daily["precipitation_sum"]
        t_min = daily["temperature_2m_min"]
        t_mean = daily["temperature_2m_mean"]
    except (KeyError, TypeError):
        return {"mm_an": 600, "source": "Open-Meteo (valeur par défaut)"}

    from collections import defaultdict
    pluie_an = defaultdict(float)
    t_moy_an = defaultdict(list)
    jours_gel_an = defaultdict(int)
    jours_saison_an = defaultdict(int)
    t_ete_an = defaultdict(list)

    for i, date_str in enumerate(dates):
        annee = date_str[:4]
        mois = int(date_str[5:7])
        if precipitations[i] is not None:
            pluie_an[annee] += precipitations[i]
        if t_mean[i] is not None:
            t_moy_an[annee].append(t_mean[i])
            if t_mean[i] > 5:
                jours_saison_an[annee] += 1
        if t_min[i] is not None and t_min[i] < 0:
            jours_gel_an[annee] += 1
        if mois in [6, 7, 8] and t_mean[i] is not None:
            t_ete_an[annee].append(t_mean[i])

    annees = sorted(pluie_an.keys())
    mm_an = round(sum(pluie_an.values()) / len(annees)) if annees else 600
    t_moy = round(sum(sum(v)/len(v) for v in t_moy_an.values()) / len(t_moy_an), 1) if t_moy_an else 11.0
    jours_gel = round(sum(jours_gel_an.values()) / len(jours_gel_an)) if jours_gel_an else 30
    jours_saison = round(sum(jours_saison_an.values()) / len(jours_saison_an)) if jours_saison_an else 250
    t_ete = round(sum(sum(v)/len(v) for v in t_ete_an.values()) / len(t_ete_an), 1) if t_ete_an else 19.0

    return {
        "mm_an": mm_an,
        "temperature_moy_annuelle": t_moy,
        "jours_gel": jours_gel,
        "jours_saison_culture": jours_saison,
        "temperature_moy_ete": t_ete,
        "interpretation_climat": interpreter_climat(t_moy, jours_gel, jours_saison),
        "source": f"Open-Meteo Archive ({annees[0]}-{annees[-1]})" if annees else "Open-Meteo"
    }


# ════════════════════════════════════════════════════════
#  ENDPOINT 6 — Adresse (reverse geocoding)
# ════════════════════════════════════════════════════════

@app.get("/api/adresse")
async def get_adresse(lat: float = Query(...), lng: float = Query(...)):
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            resp = await client.get("https://api-adresse.data.gouv.fr/reverse/", params={"lon": lng, "lat": lat})
            resp.raise_for_status()
            features = resp.json().get("features", [])
            if features:
                props = features[0]["properties"]
                return {"adresse": props.get("label", ""), "ville": props.get("city", ""),
                        "citycode": props.get("citycode", "")}
        except Exception:
            pass
    return {"adresse": f"{lat:.5f}°N, {lng:.5f}°E", "citycode": ""}


# ════════════════════════════════════════════════════════
#  ENDPOINT 7 — Foncier DVF
# ════════════════════════════════════════════════════════

DVF_STATS_FILE = Path(__file__).parent / "dvf_stats.json"
_dvf_cache = None

def charger_dvf():
    global _dvf_cache
    if _dvf_cache is not None:
        return _dvf_cache
    try:
        with open(DVF_STATS_FILE, encoding="utf-8") as f:
            _dvf_cache = json.load(f)
    except Exception:
        _dvf_cache = {}
    return _dvf_cache


def interpreter_prix(prix: int, code_commune: str) -> dict:
    dvf = charger_dvf()
    dep = code_commune[:2]
    medianes_dep = dvf.get("_medianes_dep", {})
    mediane_dep = medianes_dep.get(dep)
    if not mediane_dep:
        if prix > 8000:
            return {"niveau": "eleve", "label": "Élevé", "detail": "Prix élevé — modèle locatif ou toiture recommandé"}
        elif prix > 3000:
            return {"niveau": "moyen", "label": "Dans la moyenne", "detail": "Prix dans la moyenne nationale"}
        else:
            return {"niveau": "accessible", "label": "Accessible", "detail": "Prix favorable à l'acquisition foncière"}
    ratio = prix / mediane_dep
    if ratio > 1.5:
        return {"niveau": "tres_eleve", "label": "Bien au-dessus du marché local",
                "detail": f"Prix {round((ratio-1)*100)}% au-dessus de la médiane locale ({mediane_dep:,} €/m²) — privilégier toiture ou façade"}
    elif ratio > 1.1:
        return {"niveau": "eleve", "label": "Au-dessus du marché local",
                "detail": f"Prix légèrement supérieur à la médiane locale ({mediane_dep:,} €/m²)"}
    elif ratio > 0.9:
        return {"niveau": "moyen", "label": "Dans le marché local",
                "detail": f"Prix dans la médiane locale ({mediane_dep:,} €/m²)"}
    elif ratio > 0.6:
        return {"niveau": "accessible", "label": "En dessous du marché local",
                "detail": f"Prix favorable par rapport à la médiane locale ({mediane_dep:,} €/m²)"}
    else:
        return {"niveau": "accessible", "label": "Très en dessous du marché local",
                "detail": f"Prix très favorable — opportunité foncière ({mediane_dep:,} €/m²)"}


@app.get("/api/foncier")
async def get_foncier(lat: float = Query(...), lng: float = Query(...)):
    code_commune = None
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            resp = await client.get("https://api-adresse.data.gouv.fr/reverse/", params={"lon": lng, "lat": lat})
            resp.raise_for_status()
            features = resp.json().get("features", [])
            if features:
                citycode = features[0]["properties"].get("citycode", "")
                code_commune = citycode if citycode else None
        except Exception:
            pass
    if not code_commune:
        return {"disponible": False, "message": "Localisation non trouvée"}
    dvf = charger_dvf()
    stats = dvf.get(code_commune)
    if not stats:
        return {"disponible": False, "message": f"Pas de données DVF pour ce secteur ({code_commune})"}
    return {
        "disponible": True, "code_commune": code_commune,
        "prix_m2_median": stats["median"], "prix_m2_min": stats["min"],
        "prix_m2_max": stats["max"], "nb_transactions": stats["nb"],
        "periode": "2022–2025",
        "interpretation": interpreter_prix(stats["median"], code_commune),
        "source": "DVF — DGFiP (2022–2025)",
    }


# ════════════════════════════════════════════════════════
#  ENDPOINT 8 — Friches (Cartofriches / Cerema)
# ════════════════════════════════════════════════════════

_friches_cache = None
FRICHES_FILE = Path(__file__).parent / "friches.geojson"

def charger_friches():
    global _friches_cache
    if _friches_cache is not None:
        return _friches_cache
    try:
        with open(FRICHES_FILE, encoding="utf-8") as f:
            _friches_cache = json.load(f)
    except Exception as e:
        _friches_cache = {"type": "FeatureCollection", "features": [], "error": str(e)}
    return _friches_cache


@app.get("/api/friches")
async def get_friches(lat: float = Query(...), lng: float = Query(...), rayon: int = Query(2000)):
    data = charger_friches()
    features_proches = []
    for f in data.get("features", []):
        geom = f.get("geometry", {})
        if not geom or geom["type"] != "Point":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        dist = haversine(lat, lng, coords[1], coords[0])
        if dist <= rayon:
            statut = f["properties"].get("site_statut", "")
            if statut == "friche reconvertie":
                continue
            f["properties"]["distance_m"] = round(dist)
            f["properties"]["couleur"] = {
                "friche sans projet": "#4ade80",
                "friche potentielle": "#fbbf24",
                "friche avec projet": "#60a5fa",
            }.get(statut, "#9ca3af")
            features_proches.append(f)
    features_proches.sort(key=lambda f: f["properties"].get("distance_m", 9999))
    return {
        "type": "FeatureCollection",
        "features": features_proches[:30],
        "meta": {"dans_rayon": len(features_proches), "source": "Cartofriches — Cerema 2026"}
    }


# ════════════════════════════════════════════════════════
#  ENDPOINT — BASIAS (anciens sites industriels)
# ════════════════════════════════════════════════════════

@app.get("/api/basias")
async def get_basias(lat: float = Query(...), lng: float = Query(...), rayon: int = Query(2000)):
    url = "https://www.georisques.gouv.fr/api/v1/basias"
    params = {"rayon": rayon, "latlon": f"{lng},{lat}", "page": 1, "page_size": 50}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except Exception as e:
            return {"type": "FeatureCollection", "features": [], "error": str(e)}
    raw = resp.json()
    features = []
    for site in raw.get("data", []):
        coords = site.get("coordonnees", {})
        lon = coords.get("lon") or site.get("longitude")
        lat_s = coords.get("lat") or site.get("latitude")
        if not lon or not lat_s:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat_s]},
            "properties": {
                "nom": site.get("nom_usuel", site.get("raison_sociale", "Site BASIAS")),
                "adresse": site.get("adresse", ""),
                "commune": site.get("commune", ""),
                "activite": site.get("activite_principale", ""),
                "statut": site.get("etat_avancement", ""),
                "distance_m": round(haversine(lat, lng, lat_s, lon)),
                "source": "BASIAS",
            }
        })
    features.sort(key=lambda f: f["properties"]["distance_m"])
    return {"type": "FeatureCollection", "features": features,
            "meta": {"total": raw.get("total", len(features)), "source": "BASIAS — Géorisques"}}


# ════════════════════════════════════════════════════════
#  ENDPOINT — PPRI (zones inondables)
# ════════════════════════════════════════════════════════

@app.get("/api/ppri")
async def get_ppri(lat: float = Query(...), lng: float = Query(...)):
    url = "https://www.georisques.gouv.fr/api/v1/zonage_inondation"
    params = {"latlon": f"{lng},{lat}", "rayon": 100, "page": 1, "page_size": 5}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except Exception as e:
            return {"en_zone_inondable": False, "erreur": str(e)}
    raw = resp.json()
    zones = raw.get("data", [])
    if not zones:
        return {"en_zone_inondable": False, "zones": [], "source": "Géorisques PPRI"}
    return {
        "en_zone_inondable": True,
        "zones": [{"nom": z.get("libelle_zone", "Zone inondable"), "type": z.get("type_zone", "")} for z in zones],
        "source": "Géorisques PPRI"
    }

# ════════════════════════════════════════════════════════
#  ENDPOINT 9 — Diagnostic complet
# ════════════════════════════════════════════════════════

@app.get("/api/diagnostic")
async def get_diagnostic(lat: float = Query(...), lng: float = Query(...)):
    import asyncio

    results = await asyncio.gather(
        get_pollution(lat=lat, lng=lng, rayon=2000),
        get_ensoleillement(lat=lat, lng=lng),
        get_chaleur(lat=lat, lng=lng, rayon=2000),
        get_plu(lat=lat, lng=lng),
        get_pluie(lat=lat, lng=lng),
        get_adresse(lat=lat, lng=lng),
        return_exceptions=True
    )
    pollution_data, ensoleil_data, chaleur_data, plu_data, pluie_data, adresse_data = results

    try:
        foncier_data = await get_foncier(lat=lat, lng=lng)
    except Exception as e:
        foncier_data = {"disponible": False, "message": str(e)}

    sites = pollution_data.get("features", []) if not isinstance(pollution_data, Exception) else []
    pollution_analyse = analyser_pollution(sites)

    kwh = ensoleil_data.get("kwh_m2_an", 1000) if not isinstance(ensoleil_data, Exception) else 1000
    ensoleil_analyse = analyser_ensoleillement(kwh)

    features_ch = chaleur_data.get("features", []) if not isinstance(chaleur_data, Exception) else []
    chaleur_analyse = analyser_chaleur(features_ch)

    type_zone = plu_data.get("type_zone", "inconnu") if not isinstance(plu_data, Exception) else "inconnu"
    libelle_zone = plu_data.get("libelle", "") if not isinstance(plu_data, Exception) else ""
    url_reglement = plu_data.get("url_reglement", "") if not isinstance(plu_data, Exception) else ""
    plu_analyse = analyser_plu(type_zone, libelle_zone)

    mm_an = 600
    if not isinstance(pluie_data, Exception) and isinstance(pluie_data, dict):
        mm_an = pluie_data.get("mm_an", 600) or 600
    pluie_analyse = analyser_pluie(mm_an)
    if pluie_analyse is None:
        pluie_analyse = analyser_pluie(600)

    projets = []
    for type_projet in TYPES_PROJETS:
        score_projet = calculer_score_projet(type_projet, pollution_analyse, ensoleil_analyse,
                                             chaleur_analyse, plu_analyse, pluie_analyse)
        projets.append(score_projet)
    projets.sort(key=lambda p: p["score"], reverse=True)
    top3 = projets[:3]

    adresse_str = f"{lat:.5f}°N, {lng:.5f}°E"
    if not isinstance(adresse_data, Exception):
        adresse_str = adresse_data.get("adresse", adresse_str)

    climat = {}
    if not isinstance(pluie_data, Exception) and isinstance(pluie_data, dict):
        climat = pluie_data.get("interpretation_climat", {})

    return {
        "lat": lat, "lng": lng, "adresse": adresse_str,
        "projets": top3, "tous_projets": projets,
        "contexte": {
            "ensoleillement_kwh": kwh,
            "pluie_mm_an": mm_an,
            "pluie_label": pluie_analyse["label"],
            "temperature_moy": pluie_data.get("temperature_moy_annuelle") if not isinstance(pluie_data, Exception) else None,
            "jours_gel": pluie_data.get("jours_gel") if not isinstance(pluie_data, Exception) else None,
            "jours_saison": pluie_data.get("jours_saison_culture") if not isinstance(pluie_data, Exception) else None,
            "temperature_ete": pluie_data.get("temperature_moy_ete") if not isinstance(pluie_data, Exception) else None,
            "climat": climat,
            "pollution_resume": pollution_analyse["resume"],
            "pollution_niveau": pollution_analyse["niveau_global"],
            "zone_plu": f"{type_zone} — {libelle_zone}" if libelle_zone else type_zone,
            "url_plu": url_reglement,
        },
        "foncier": foncier_data if not isinstance(foncier_data, Exception) else {"disponible": False},
        "sources": [
            "SSP CASIAS — Géorisques",
            "PVGIS v5.2 — JRC / Commission Européenne",
            "SNCU / CEREMA — data.gouv.fr",
            "API Carto IGN — Géoportail Urbanisme",
            "Open-Meteo Archive",
            "API Adresse — adresse.data.gouv.fr",
            "DVF — DGFiP (2022–2025)",
            "Cartofriches — Cerema 2026",
            "BASIAS — Géorisques",
            "PPRI — Géorisques",
        ]
    }


# ════════════════════════════════════════════════════════
#  ENDPOINT 10 — PDF
# ════════════════════════════════════════════════════════

@app.post("/api/pdf")
async def generer_pdf(payload: dict = Body(...)):
    from fpdf import FPDF

    FONT_DIR = Path(__file__).parent
    diag = payload.get("diagnostic", {})
    type_choisi = payload.get("projet_choisi", "")

    tous_projets = diag.get("tous_projets", diag.get("projets", []))
    projet = next((p for p in tous_projets if p["type"] == type_choisi), tous_projets[0] if tous_projets else {})
    autres = [p for p in diag.get("projets", []) if p["type"] != type_choisi][:2]

    ctx = diag.get("contexte", {})
    foncier = diag.get("foncier", {})
    adresse = diag.get("adresse", "-")
    lat = diag.get("lat", 0)
    lng = diag.get("lng", 0)
    today = date_cls.today().strftime("%d/%m/%Y")

    def t(texte):
        if not texte:
            return ""
        return str(texte).replace('\u2014', ' — ').replace('\u2013', '-').replace('\u00a0', ' ')

    def niveau_sym(niveau):
        return {"ok": "✓ Favorable", "warn": "⚠ Vigilance", "danger": "✗ Bloquant"}.get(niveau, "-")

    pdf = FPDF()
    pdf.set_margins(20, 18, 20)
    font_reg = str(FONT_DIR / "DejaVuSans.ttf")
    font_bold = str(FONT_DIR / "DejaVuSans-Bold.ttf")
    pdf.add_font("DejaVu", "", font_reg)
    pdf.add_font("DejaVu", "B", font_bold)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)

    pdf.set_font("DejaVu", "B", 17)
    pdf.cell(0, 9, "Fiche Diagnostic Foncier", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 6, t(adresse), ln=True)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 5, f"{lat:.5f}°N, {lng:.5f}°E  |  Généré le {today}  |  Foncier Agricole Urbain v2", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    pdf.set_draw_color(30, 30, 30)
    pdf.set_line_width(0.8)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(7)

    def section_title(titre):
        pdf.set_font("DejaVu", "B", 12)
        pdf.set_draw_color(30, 30, 30)
        pdf.cell(0, 7, titre, ln=True)
        pdf.set_line_width(0.3)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(4)

    section_title("Projet sélectionné")
    pdf.set_fill_color(245, 245, 245)
    y0 = pdf.get_y()
    pdf.rect(20, y0, 170, 20, "F")
    pdf.set_xy(24, y0 + 3)
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(110, 7, t(projet.get("label", "")), ln=False)
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(46, 7, f"{t(projet.get('verdict', ''))}  {projet.get('score', 0)}/100", align="R", ln=True)
    pdf.set_xy(24, pdf.get_y())
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, t(projet.get("description", "")), ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(0, 6, "Analyse des critères", ln=True)
    pdf.ln(2)
    for c in projet.get("criteres", []):
        sym = niveau_sym(c["niveau"])
        pdf.set_font("DejaVu", "B", 9)
        pdf.cell(38, 5, t(c["nom"]), ln=False)
        pdf.cell(26, 5, sym, ln=False)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 5, t(c["texte"]))
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(220, 220, 220)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(1)
    pdf.ln(5)

    section_title("Données du site")
    climat = ctx.get("climat", {})
    donnees = [
        ("Ensoleillement", f"{ctx.get('ensoleillement_kwh', '-')} kWh/m²/an  (PVGIS / JRC)"),
        ("Pluviométrie", f"{t(ctx.get('pluie_label', '-'))}  (Open-Meteo 2018–2023)"),
        ("Température moy.", f"{ctx.get('temperature_moy', '-')} °C / été : {ctx.get('temperature_ete', '-')} °C"),
        ("Jours de gel", f"{ctx.get('jours_gel', '-')} jours/an — Saison culture : {ctx.get('jours_saison', '-')} jours"),
        ("Zone climatique", f"{t(climat.get('zone', '-'))} — {t(climat.get('detail', '-'))}"),
        ("Zonage PLU", t(ctx.get("zone_plu", "-"))),
        ("Pollution", t(ctx.get("pollution_resume", "-"))),
    ]
    if foncier.get("disponible"):
        interp = foncier.get("interpretation", {})
        donnees.append(("Prix foncier médian", f"{foncier.get('prix_m2_median', 0):,} €/m² — {t(interp.get('label', ''))}"))
        donnees.append(("Fourchette prix", f"{foncier.get('prix_m2_min', 0):,} – {foncier.get('prix_m2_max', 0):,} €/m²  ({foncier.get('nb_transactions', 0)} transactions, {foncier.get('periode', '')})"))

    for label_d, valeur_d in donnees:
        pdf.set_font("DejaVu", "B", 9)
        pdf.cell(52, 6, label_d, ln=False)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 5, t(valeur_d))
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(220, 220, 220)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(1)
    pdf.ln(5)

    section_title("Réglementation urbanisme")
    url_plu = ctx.get("url_plu", "")
    url_affichee = url_plu[:80] + "..." if len(url_plu) > 80 else url_plu
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(52, 6, "Consulter le PLU :", ln=False)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(30, 60, 120)
    pdf.multi_cell(0, 5, t(url_affichee) if url_plu else "Non disponible")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 5, t(f"Le zonage {ctx.get('zone_plu', '-')} est indicatif. Le règlement complet de la zone détermine les usages autorisés, les hauteurs maximales et les coefficients d'emprise. Une consultation du service urbanisme est recommandée avant tout dépôt de dossier."))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    if autres:
        section_title("Autres projets évalués")
        for p in autres:
            pdf.set_font("DejaVu", "B", 9)
            pdf.cell(90, 6, t(p.get("label", "")), ln=False)
            pdf.set_font("DejaVu", "", 9)
            pdf.cell(50, 6, t(p.get("verdict", "")), ln=False)
            pdf.cell(0, 6, f"{p.get('score', 0)}/100", align="R", ln=True)
        pdf.ln(5)

    section_title("Sources de données")
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(80, 80, 80)
    for s in diag.get("sources", []):
        pdf.cell(0, 5, t(f"• {s}"), ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("DejaVu", "", 7)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4, t("Avertissement : Ce diagnostic est fourni à titre indicatif sur la base de données publiques disponibles à la date de génération. Il ne constitue pas une étude réglementaire, environnementale ou technique et ne saurait engager la responsabilité de ses auteurs. Une étude pédologique, une consultation du service urbanisme compétent et un avis d'expert sont recommandés avant tout engagement."))

    pdf_bytes = bytes(pdf.output())
    nom_clean = adresse[:30].replace(' ', '_').replace(',', '').replace('/', '')
    nom = f"diagnostic_{nom_clean}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={nom}"})


# ════════════════════════════════════════════════════════
#  UTILITAIRES
# ════════════════════════════════════════════════════════

def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def score_to_type(score):
    if score >= 70: return "ok"
    if score >= 40: return "warn"
    return "danger"


def niveau_to_type(niveau):
    return {"excellent": "ok", "bon": "ok", "moyen": "warn", "insuffisant": "danger"}.get(niveau, "warn")


@app.get("/")
async def root():
    return {"message": "Foncier Agricole Urbain API v2", "docs": "http://localhost:8000/docs"}
