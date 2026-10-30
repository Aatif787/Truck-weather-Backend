import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

ORS_GEOCODE_URL = 'https://api.openrouteservice.org/geocode/search'
ORS_DIRECTIONS_HGV_URL = 'https://api.openrouteservice.org/v2/directions/driving-hgv/geojson'
ORS_DIRECTIONS_CAR_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'

METERS_TO_MILES = 0.000621371

def geocode_location(query: str) -> dict:
    """
    Geocodes a query string (e.g. city or address) to [lon, lat] and a display name.
    Returns: {"name": str, "coordinates": [lon, lat]}
    Raises ValueError on not found or API failure.
    """
    api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
    if not api_key:
        raise ValueError("OpenRouteService API key is missing on the server.")

    headers = {'Authorization': api_key}
    params = {'text': query.strip(), 'size': 1}

    try:
        resp = requests.get(ORS_GEOCODE_URL, params=params, headers=headers, timeout=10)
    except requests.RequestException as e:
        logger.error(f"Geocoding request failed: {e}")
        raise ValueError("Geocoding service unavailable or timed out.")

    if resp.status_code == 401 or resp.status_code == 403:
        raise ValueError("Invalid or unauthorized OpenRouteService API key.")
    elif resp.status_code != 200:
        raise ValueError(f"Geocoding failed with status {resp.status_code}.")

    data = resp.json()
    features = data.get('features', [])
    if not features:
        raise ValueError(f"Location not found: '{query}'")

    first = features[0]
    coords = first.get('geometry', {}).get('coordinates', [])
    if len(coords) < 2:
        raise ValueError(f"Invalid coordinates returned for '{query}'")

    label = first.get('properties', {}).get('label') or first.get('properties', {}).get('name') or query
    return {
        'name': label,
        'coordinates': [float(coords[0]), float(coords[1])]
    }

def _parse_feature(feature, route_index, origin_coords, dest_coords, route_name_prefix="Route"):
    props = feature.get('properties', {})
    summary = props.get('summary', {})
    meters = float(summary.get('distance', 0.0))
    duration_sec = float(summary.get('duration', 0.0))
    if duration_sec <= 0 and meters > 0:
        # Graceful fallback duration based on standard truck speed (approx 50 mph)
        duration_sec = meters / 22.35

    geometry = feature.get('geometry', {})

    return {
        'id': f"route-{route_index}",
        'name': f"{route_name_prefix} {route_index}",
        'distance_miles': round(meters * METERS_TO_MILES, 2),
        'duration_seconds': round(duration_sec, 1),
        'geometry': geometry,
        'start_coordinates': origin_coords,
        'destination_coordinates': dest_coords,
    }

def get_routes(origin_coords: list, dest_coords: list) -> list:
    """
    Fetches driving-hgv route(s) between origin and destination coordinates [lon, lat].
    Attempts to fetch alternative routes. If the distance exceeds ORS limit (100km)
    for alternative_routes algorithm, gracefully falls back to multi-preference routing.
    """
    api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
    if not api_key:
        raise ValueError("OpenRouteService API key is missing on the server.")

    headers = {
        'Authorization': api_key,
        'Content-Type': 'application/json'
    }

    # Attempt 1: alternative_routes parameter (works up to 100km)
    body_alt = {
        'coordinates': [origin_coords, dest_coords],
        'alternative_routes': {
            'target_count': 3,
            'weight_factor': 1.4,
            'share_factor': 0.6
        }
    }

    try:
        resp = requests.post(ORS_DIRECTIONS_HGV_URL, json=body_alt, headers=headers, timeout=15)
        if resp.status_code == 200:
            features = resp.json().get('features', [])
            if features:
                unique_features = []
                seen_signatures = set()
                for f in features:
                    s = f.get('properties', {}).get('summary', {})
                    sig = (round(float(s.get('distance', 0.0)), 1), round(float(s.get('duration', 0.0)), 1))
                    if sig not in seen_signatures:
                        seen_signatures.add(sig)
                        unique_features.append(f)

                if unique_features:
                    return [
                        _parse_feature(f, idx + 1, origin_coords, dest_coords)
                        for idx, f in enumerate(unique_features[:3])
                    ]
    except requests.RequestException as e:
        logger.warning(f"Alternative routes request failed: {e}")

    # Fallback for >100km or when alternative_routes returns non-200 (e.g. code 2004 limit):
    # We fetch routes using distinct preferences ('recommended' and 'shortest')
    routes = []
    seen_distances = set()

    for pref in ['recommended', 'shortest']:
        body_pref = {
            'coordinates': [origin_coords, dest_coords],
            'preference': pref
        }
        try:
            r = requests.post(ORS_DIRECTIONS_HGV_URL, json=body_pref, headers=headers, timeout=15)
            if r.status_code == 200:
                features = r.json().get('features', [])
                if features:
                    parsed = _parse_feature(features[0], len(routes) + 1, origin_coords, dest_coords)
                    # Deduplicate if identical distance
                    if parsed['distance_miles'] not in seen_distances:
                        seen_distances.add(parsed['distance_miles'])
                        routes.append(parsed)
            elif r.status_code in (401, 403):
                raise ValueError("Invalid or unauthorized OpenRouteService API key.")
        except requests.RequestException as e:
            logger.error(f"Route query error for preference {pref}: {e}")

    if not routes:
        raise ValueError("No viable truck routes could be calculated for these locations.")

    return routes

