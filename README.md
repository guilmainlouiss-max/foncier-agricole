# Foncier Agricole Urbain — Prototype de diagnostic préventif

Carte interactive de viabilité foncière pour l'agriculture urbaine.
Branchée sur les vraies API open data françaises.

---

## Lancement en 3 commandes

```bash
# 1. Cloner / décompresser le projet, puis :
cd foncier-agricole/backend

# 2. Installer les dépendances Python
pip install -r requirements.txt

# 3. Démarrer le backend
python -m uvicorn main:app --reload --port 8000
```

Ensuite, ouvrir dans votre navigateur :
- **La carte** : `../frontend/index.html`  (ouvrir directement dans le navigateur)
- **Documentation API interactive** : http://localhost:8000/docs  ← Swagger UI, très utile

---

## Architecture

```
foncier-agricole/
├── backend/
│   ├── main.py          ← API FastAPI (6 endpoints)
│   └── requirements.txt
└── frontend/
    └── index.html       ← Carte MapLibre + diagnostic
```

**Flux d'un clic sur la carte :**
```
Navigateur (clic)
  → GET /api/diagnostic?lat=X&lng=Y
      → [parallèle] Géorisques BASOL API
      → [parallèle] PVGIS (ensoleillement)
      → [parallèle] SNCU réseaux de chaleur
      → [parallèle] IGN GPU PLU (WFS)
      → [parallèle] API Adresse (reverse geocoding)
  ← score_global + critères + alertes + étapes
```

---

## API sources utilisées

| Données | API | Clé requise | Limites |
|---|---|---|---|
| Pollution des sols (BASOL) | georisques.gouv.fr/api/v1/installations | Non | 1000 req/min |
| Ensoleillement annuel | re.jrc.ec.europa.eu/api/v5_2/PVcalc | Non | 30 req/min |
| Réseaux de chaleur | data.gouv.fr (GeoJSON SNCU) | Non | Fichier unique (~2 Mo) |
| Zonage PLU | wxs.ign.fr/essentiels/geoportail/wfs | Non | Usage "raisonnable" |
| Adresse (reverse geocoding) | api-adresse.data.gouv.fr/reverse | Non | Illimitée |

---

## Ce qui reste à faire (roadmap)

### Court terme (MVP)
- [ ] **Couche ensoleillement en grille** : appeler PVGIS sur une grille de points
      pour afficher la couche couleur sur la carte (actuellement vide au démarrage).
      → Pré-calculer sur Paris une nuit, stocker en GeoJSON, servir statiquement.

- [ ] **URL GeoJSON réseaux de chaleur** : vérifier l'URL exacte sur data.gouv.fr
      (elle change parfois). Récupérer depuis :
      https://www.data.gouv.fr/fr/datasets/reseaux-de-chaleur-et-de-froid/

- [ ] **Affichage couche PLU** : l'API WFS IGN retourne la géométrie complète
      de la zone. L'ajouter à la couche `plu-zone` dans `updateMapLayers()`.

### Moyen terme
- [ ] **LiDAR IGN pour les toitures** : remplacer PVGIS (irradiation horizontale)
      par le calcul GRASS r.sun sur le MNS LiDAR HD IGN pour les façades et toitures.
      Pipeline : télécharger les dalles LAZ → PDAL → GRASS r.sun → GeoTIFF → GeoJSON.

- [ ] **Données foncières DVF** : ajouter le prix au m² des transactions récentes
      pour évaluer le coût d'acquisition. API : api.cquest.org/dvf

- [ ] **Export PDF** : générer une fiche A4 téléchargeable avec jsPDF.

- [ ] **Cache Redis** : les appels PVGIS et IGN sont lents (2-5s).
      Cacher les résultats par coordonnée arrondie à 3 décimales.

### Long terme
- [ ] **Base PostGIS** : stocker les diagnostics calculés pour les réutiliser.
- [ ] **Compte utilisateur** : sauvegarder des sites favoris, comparer.
- [ ] **API BASIAS** : ajouter les sites industriels anciens (pas seulement BASOL).

---

## Structure d'une réponse /api/diagnostic

```json
{
  "lat": 48.856,
  "lng": 2.348,
  "adresse": "12 Rue de Rivoli, 75001 Paris",
  "score_global": 67,
  "verdict": {
    "label": "Vigilance requise",
    "niveau": "moyen",
    "couleur": "#fbbf24",
    "detail": "Étude approfondie recommandée avant engagement"
  },
  "criteres": [
    {
      "nom": "Pollution des sols",
      "score": 88,
      "poids": "35%",
      "valeur": "450 m du site le plus proche",
      "alerte": { "type": "ok", "texte": "..." }
    },
    ...
  ],
  "prochaines_etapes": [
    "🟢 Contacter le service urbanisme pour pré-instruction",
    "📋 Déposer un dossier ADEME"
  ],
  "sources": ["BASOL — Géorisques", "PVGIS v5.2 — JRC", ...]
}
```
