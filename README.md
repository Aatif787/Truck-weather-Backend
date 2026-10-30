# Weather-Aware Truck Routing

A production-ready web application designed for commercial truck dispatchers and freight drivers to plan highway routes, assess weather hazards along the trip corridor, and select the safest route. It couples real-time OpenRouteService heavy-vehicle routing with Open-Meteo localized meteorological forecasting to calculate risk scores adjusted for cargo weight.

---

## Table of Contents

1. [Overview & Purpose](#1-overview--purpose)
2. [Key Features](#2-key-features)
3. [Technology Stack](#3-technology-stack)
4. [Prerequisites](#4-prerequisites)
5. [Installation & Setup](#5-installation--setup)
6. [Running Locally](#6-running-locally)
7. [Environment Variables](#7-environment-variables)
8. [API Endpoints](#8-api-endpoints)
9. [Weather Risk Thresholds](#9-weather-risk-thresholds)
10. [Truck Load Adjustment Rules](#10-truck-load-adjustment-rules)
11. [Route Ranking & Recommendation Engine](#11-route-ranking--recommendation-engine)
12. [UNKNOWN & NO_TRAVEL Handling](#12-unknown--notravel-handling)
13. [Forecast Timeline Slider (0–48h)](#13-forecast-timeline-slider-048h)
14. [Testing & Verification](#14-testing--verification)
15. [Known Limitations](#15-known-limitations)
16. [Production Deployment Guide](#16-production-deployment-guide)

---

## 1. Overview & Purpose

Freight hauling faces critical safety hazards during severe meteorological events—especially high crosswinds for heavy-duty box trucks and tractor-trailers, flash flooding, and blizzards. 

This application calculates dynamic risk metrics at fixed distance intervals (10, 25, or 50 miles) along actual highway corridors. By combining route geometries, estimated arrival times (ETA), cargo weight, and localized hourly forecasts, it recommends the safest path among alternatives or warns when travel must be suspended entirely.

---

## 2. Key Features

- **Heavy-Vehicle Road Routing:** Real road-network geometries and alternative paths via the OpenRouteService `driving-hgv` profile.
- **Dynamic Checkpoint Sampling:** Samples routes at user-configurable intervals (10, 25, or 50 miles) with forward-interpolated arrival times.
- **Localized Weather Forecasts:** Queries Open-Meteo for wind speed (10m), rain accumulation, total precipitation, and snowfall in US customary units (`mph`, `in/hr`).
- **Load-Adjusted Wind Vulnerability:** Escalates wind risk based on cargo gross weight (e.g., wind > 35 mph elevates to SEVERE for loads > 40,000 lbs).
- **0–48 Hour Forecast Timeline Slider:** Enables interactive weather inspection from departure (+0h) up to 48 hours into the future, alongside the default trajectory ETA forecast mode.
- **Interactive Map:** WebGL-rendered MapLibre GL map with monochrome/desaturated basemap, high-visibility non-blue route polylines, corridor risk halos, and interactive checkpoint markers.
- **4-Tier Deterministic Ranking:** Evaluates routes across severe miles, high miles, composite average risk, and travel duration.
- **Strict Color Guidelines:** Completely free of blue elements. Uses off-white, white, charcoal, and orange accents, with standard semantic colors reserved exclusively for risk states.

---

## 3. Technology Stack

- **Backend:** Python 3.12+, Django 6.1+, Django REST Framework (DRF) 3.18+, `django-cors-headers`, `requests`, `python-dotenv`, `gunicorn`.
- **Frontend:** React 19, TypeScript 5.9, Vite 8.3, MapLibre GL JS 5.x.
- **Styling:** Custom CSS adhering strictly to a neutral charcoal/orange palette with no blue hues.
- **External APIs:**
  - [OpenRouteService API](https://openrouteservice.org/) (Geocoding `/geocode/search`, HGV Directions `/v2/directions/driving-hgv/geojson`).
  - [Open-Meteo Forecast API](https://open-meteo.com/en/docs) (`/v1/forecast`).

---

## 4. Prerequisites

- **Python:** Version 3.12 or higher (Python 3.13 supported).
- **Node.js:** Version 18.x or higher (Node 20+ LTS recommended).
- **npm:** Version 9.x or higher.
- **OpenRouteService API Key:** Free account at [openrouteservice.org](https://openrouteservice.org/).

---

## 5. Installation & Setup

### Clone Repository
```bash
git clone <repository-url>
cd truck
```

### Backend Setup
```bash
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate      # Windows (PowerShell/CMD)
# source .venv/bin/activate    # macOS/Linux

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create .env from template
cp .env.example .env
# Edit .env and enter your OPENROUTESERVICE_API_KEY
```

### Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env
cd ..
```

---

## 6. Running Locally

### 1. Start Django Backend (Port 8001)
> [!NOTE]
> Port 8001 is used to prevent port conflicts with system services or background web servers on port 8000.

```bash
# In project root with .venv activated
python manage.py migrate
python manage.py runserver 8001
```
The backend health check is available at: `http://127.0.0.1:8001/api/health/`.

### 2. Start React Frontend (Port 5173)
```bash
cd frontend
npm run dev
```
Open your browser at `http://localhost:5173`.

---

## 7. Environment Variables

### Root / Backend `.env`
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `DJANGO_SECRET_KEY` | No (Yes in Prod) | `insecure-dev-...` | Cryptographic secret for Django security. |
| `DEBUG` | No | `True` | Enables Django debug mode. Set to `False` in production. |
| `DJANGO_ALLOWED_HOSTS`| No | `localhost,127.0.0.1` | Comma-separated allowed hostnames. |
| `CORS_ALLOWED_ORIGINS`| No | `http://localhost:5173` | Comma-separated frontend domains allowed for CORS. |
| `OPENROUTESERVICE_API_KEY` | **Yes** | *None* | Authentication token for OpenRouteService HGV routing. |

### Frontend `frontend/.env`
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `VITE_API_BASE_URL` | No | `http://127.0.0.1:8001` | Base URL for the Django backend API. |

---

## 8. API Endpoints

### 1. Health Check: `GET /api/health/`
Returns service status, environment readiness, and timestamp.
```json
{
  "status": "ok",
  "service": "weather-aware-truck-routing",
  "ors_configured": true,
  "timestamp": "2026-10-30T05:55:00.000Z"
}
```

### 2. Route Evaluation: `POST /api/routes/`
Computes highway routes, creates checkpoints, samples hourly weather, assesses risk, and ranks alternatives.

**Request Payload:**
```json
{
  "origin": "Mannheim, Germany",
  "destination": "Heidelberg, Germany",
  "departure_time": "2026-10-30T10:00:00.000Z",
  "cargo_weight_lbs": 35000,
  "sampling_interval_miles": 10
}
```

**Response Format:**
```json
{
  "origin": "Mannheim, Germany",
  "destination": "Heidelberg, Germany",
  "departure_time": "2026-10-30T10:00:00.000Z",
  "cargo_weight_lbs": 35000,
  "sampling_interval_miles": 10,
  "routes": [
    {
      "id": "route_1",
      "name": "Route 1",
      "distance_miles": 14.8,
      "duration_minutes": 22.5,
      "recommendation_rank": 1,
      "is_recommended": true,
      "overall_risk": "LOW",
      "severe_miles": 0.0,
      "high_miles": 0.0,
      "average_risk_score": 1.0,
      "geometry": { "type": "LineString", "coordinates": [...] },
      "checkpoints": [
        {
          "checkpoint_index": 1,
          "distance_from_origin_miles": 0.0,
          "coordinates": [8.466, 49.487],
          "estimated_arrival_time": "2026-10-30T10:00:00.000Z",
          "weather": {
            "wind_speed_mph": 8.4,
            "rain_intensity_in_hr": 0.0,
            "snow_intensity_in_hr": 0.0,
            "wind_risk": "LOW",
            "rain_risk": "LOW",
            "snow_risk": "LOW",
            "load_adjusted_wind_risk": "LOW",
            "final_risk": "LOW",
            "weather_status": "AVAILABLE"
          },
          "hourly_forecasts": [
            {
              "offset_hours": 0,
              "forecast_timestamp": "2026-10-30T10:00:00Z",
              "wind_speed_mph": 8.4,
              "rain_intensity_in_hr": 0.0,
              "snow_intensity_in_hr": 0.0,
              "final_risk": "LOW"
            }
          ]
        }
      ]
    }
  ]
}
```

---

## 9. Weather Risk Thresholds

Each metric is independently categorized into severity levels:

| Level | Wind Speed (`mph`) | Rain Intensity (`in/hr`) | Snowfall (`in/hr`) | Numeric Weight | UI Color |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **LOW** | < 25 | < 0.10 | < 0.50 | 1 | Green (`#15803D`) |
| **MODERATE** | 25 – 34 | 0.10 – 0.25 | 0.50 – 1.00 | 2 | Yellow (`#A16207`) |
| **HIGH** | 35 – 44 | 0.25 – 0.50 | 1.00 – 2.00 | 3 | Orange (`#C2410C`) |
| **SEVERE** | 45 – 54 | 0.50 – 1.00 | 2.00 – 3.00 | 4 | Red (`#DC2626`) |
| **NO_TRAVEL** | ≥ 55 | > 1.00 | > 3.00 | 5 | Dark Red (`#991B1B`) |
| **UNKNOWN** | *Unavailable* | *Unavailable* | *Unavailable* | 3.0 (Penalty) | Gray (`#71717A`) |

---

## 10. Truck Load Adjustment Rules

Cargo weight significantly impacts truck aerodynamics, center of gravity, and rollover susceptibility during strong winds:

1. **Universal No-Travel Rule:**
   - Wind $\ge 55\text{ mph} \implies \text{\textbf{NO\_TRAVEL}}$ regardless of truck weight.
2. **Heavy-Load Rule (> 30,000 lbs):**
   - Wind $45\text{–}54\text{ mph} \implies \text{\textbf{NO\_TRAVEL}}$ (escalated from SEVERE).
3. **Severe-Load Rule (> 40,000 lbs):**
   - Wind $35\text{–}44\text{ mph} \implies \text{\textbf{SEVERE}}$ (escalated from HIGH).
4. **Rain & Snow:**
   - Hydroplaning and traction hazards remain constant across gross load weights.

---

## 11. Route Ranking & Recommendation Engine

Candidate routes are ranked deterministically using a 4-tier hierarchy:

1. **Tier 1 — Fewest Severe Miles:**
   - Routes with fewer miles affected by `SEVERE` or `NO_TRAVEL` weather always rank higher. Represented miles are calculated using Voronoi midpoint intervals along the route.
2. **Tier 2 — Fewest High Miles:**
   - If tied on severe miles, the route with fewer miles affected by `HIGH` risk is prioritized.
3. **Tier 3 — Lowest Average Risk Score:**
   - If tied on severe and high miles, the distance-weighted composite risk score breaks the tie.
4. **Tier 4 — Shortest Travel Time:**
   - If weather metrics are identical, the route with the shortest duration (minutes) wins.

---

## 12. UNKNOWN & NO_TRAVEL Handling

### UNKNOWN Weather Handling
- When a weather service outage or coordinates error occurs, the checkpoint is flagged as `weather_status = 'UNAVAILABLE'` and risk is set to `UNKNOWN`.
- The ranking engine assigns an impartial risk penalty score of `3.0` (equivalent to HIGH risk) to unverified checkpoints, ensuring routes with verified good weather are favored over unverified routes.
- The UI highlights UNKNOWN points with neutral gray badges (`#71717A`) and surfaces warning notices.

### NO_TRAVEL Condition Handling
- If any segment of a route encounters `NO_TRAVEL` conditions (or load-adjusted `NO_TRAVEL` crosswinds), the route is flagged as `overall_risk = 'NO_TRAVEL'`.
- A route with `NO_TRAVEL` is strictly disqualified from receiving the `is_recommended = true` badge.
- If all available routes have `NO_TRAVEL` hazards, the application declares a **No Travel Advisable** status across the entire trip corridor, alerting drivers to delay departure.

---

## 13. Forecast Timeline Slider (0–48h)

The route map features an interactive 0–48 hour timeline controller:

- **ETA Trajectory Mode (Default):**
  - Checkpoint weather displays the conditions forecasted at that specific checkpoint's estimated arrival time based on driving speed and departure timestamp.
- **Snapshot Offset Mode (+0h to +48h):**
  - Moving the slider shifts all checkpoint markers and corridor risk overlays to show the weather snapshot at `Departure + N hours`.
  - Quick-jump buttons allow instant inspection at `+0h (Departure)`, `+6h`, `+12h`, `+24h (Day 1)`, and `+48h (Day 2)`.
  - Checkpoint inspector cards update dynamically with temperature, wind, rain, snow, and load-adjusted risk for the selected offset.

---

## 14. Testing & Verification

### Run Backend Unit & Integration Tests
```bash
# 34 automated unit and integration tests
.\.venv\Scripts\python.exe manage.py test
```
*Tests cover: Geocoding, ORS client fallbacks, alternative deduplication, checkpoint spacing, Open-Meteo unit conversion, weather risk mapping, truck load escalation, Voronoi segment weighting, 4-tier ranking, UNKNOWN penalties, and API validation.*

### Run Frontend Type Check & Build
```bash
cd frontend
npm run build
```
*Executes `tsc -b` and `vite build`. Verifies zero TypeScript errors, clean bundle compilation, and assets generation.*

---

## 15. Known Limitations

- **OpenRouteService Free Tier Distance Limit:**
  - The OpenRouteService public API enforces a maximum matrix and direction distance limit of **100 kilometers (~62 miles)** on its free public plan. Queries exceeding 100km return an HTTP 400 error from ORS. For commercial long-haul trips (> 100km), a self-hosted ORS Docker instance or paid ORS token should be configured.
- **Open-Meteo Free Tier Limits:**
  - Open-Meteo allows up to 10,000 API calls per day free for non-commercial use. Commercial use requires an API key.

---

## 16. Production Deployment Guide

### Architecture Recommendation
- **Backend:** Host on [Render](https://render.com/), [Railway](https://railway.app/), or [Heroku](https://www.heroku.com/) using the provided `Procfile` and `requirements.txt`.
- **Frontend:** Host on [Vercel](https://vercel.com/) or [Netlify](https://www.netlify.com/) using the provided `vercel.json` SPA routing rewrite.

### Backend Deployment (e.g. Render / Railway)
1. Link your Git repository.
2. Set Build Command: `pip install -r requirements.txt && python manage.py migrate`
3. Set Start Command: `gunicorn backend.wsgi:application`
4. Set Environment Variables:
   - `DJANGO_SECRET_KEY`: Generate a secure random 50-character string.
   - `DEBUG`: `False`
   - `DJANGO_ALLOWED_HOSTS`: `your-app.onrender.com`
   - `CORS_ALLOWED_ORIGINS`: `https://your-frontend.vercel.app`
   - `OPENROUTESERVICE_API_KEY`: Your live OpenRouteService key.

### Frontend Deployment (e.g. Vercel)
1. Link your Git repository with root directory set to `frontend`.
2. Framework Preset: `Vite`
3. Build Command: `npm run build`
4. Output Directory: `dist`
5. Set Environment Variable:
   - `VITE_API_BASE_URL`: `https://your-app.onrender.com`
6. Deploy!
