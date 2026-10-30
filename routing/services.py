import requests
import re
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


HIGHWAY_REF_PATTERNS = [
    re.compile(r'\b(A\s?\d+)\b', re.I),           # Autobahn / European Motorway
    re.compile(r'\b(B\s?\d+)\b', re.I),           # German Federal Highway (Bundesstraße)
    re.compile(r'\b(I[- ]?\d+)\b', re.I),         # US Interstate
    re.compile(r'\b(US[- ]?\d+)\b', re.I),        # US Highway
    re.compile(r'\b(E\s?\d+)\b', re.I),           # European E-road
    re.compile(r'\b(M\s?\d+)\b', re.I),           # UK Motorway
    re.compile(r'\b(L\s?\d+)\b', re.I),           # Landesstraße
    re.compile(r'\b(K\s?\d+)\b', re.I),           # Kreisstraße
    re.compile(r'\b(State (?:Route|Hwy)\s?\d+)\b', re.I),
]


def extract_highway_refs(name: str) -> list[str]:
    """Extracts standard highway and road reference codes (e.g. A 5, B 37, I-80)."""
    if not name or name == '-':
        return []
    refs = []
    for pat in HIGHWAY_REF_PATTERNS:
        for match in pat.findall(name):
            clean = match.strip().upper()
            if clean not in refs:
                refs.append(clean)
    return refs


def is_major_classification(name: str, waycategory_id: int | None = None) -> bool:
    """Determines whether a road segment is a major motorway, highway, or expressway."""
    if waycategory_id in (1, 3):  # ORS waycategory: 1 = Motorway, 3 = Motorway + Tollway
        return True
    if not name or name == '-':
        return False
    lower = name.lower()
    if any(k in lower for k in ['autobahn', 'motorway', 'interstate', 'expressway', 'freeway', 'turnpike']):
        return True
    # If contains Autobahn (A x), Bundesstraße (B x), Interstate (I-x), or US Hwy
    for pat in [HIGHWAY_REF_PATTERNS[0], HIGHWAY_REF_PATTERNS[1], HIGHWAY_REF_PATTERNS[2], HIGHWAY_REF_PATTERNS[3]]:
        if pat.search(name):
            return True
    return False


def parse_route_roads(
    steps: list[dict] | None,
    waycategory_values: list[list[int]] | None = None,
    waycategory_summary: list[dict] | None = None,
    tollways_summary: list[dict] | None = None,
    total_distance_meters: float = 0.0,
) -> dict:
    """
    Parses turn-by-turn steps from OpenRouteService directions into an ordered list
    of deduplicated roads, extracting road names, highway reference numbers,
    road classifications, and distances.
    """
    if not steps:
        return {
            'roads': [],
            'roads_travel_order': [],
            'major_roads': [],
            'highway_distance_miles': 0.0,
            'highway_percentage': 0.0,
            'toll_distance_miles': 0.0,
            'toll_percentage': 0.0,
            'has_toll_roads': False,
            'total_roads_count': 0,
        }

    waycat_list = waycategory_values or []
    raw_roads = []

    for step in steps:
        name = (step.get('name') or '').strip()
        dist_m = float(step.get('distance', 0.0))
        dur_s = float(step.get('duration', 0.0))
        wp = step.get('way_points', [0, 0])
        mid_pt = (wp[0] + wp[1]) // 2 if len(wp) >= 2 else 0

        # Correlate geometry coordinates with ORS waycategory extras
        cat_id = None
        for item in waycat_list:
            if len(item) >= 3 and item[0] <= mid_pt <= item[1]:
                cat_id = item[2]
                break

        is_major = is_major_classification(name, cat_id)
        refs = extract_highway_refs(name)

        if not name or name == '-':
            if cat_id in (1, 3):
                display_name = "Motorway / Highway (Name unassigned)"
                road_type = "motorway"
                is_major = True
            else:
                display_name = "Road name unavailable"
                road_type = "unnamed"
        else:
            display_name = name
            if is_major:
                road_type = "motorway" if (cat_id in (1, 3) or any(r.startswith('A') for r in refs)) else "highway"
            else:
                road_type = "local"

        raw_roads.append({
            'name': display_name,
            'distance_meters': dist_m,
            'duration_seconds': dur_s,
            'highway_refs': refs,
            'is_major_road': is_major,
            'road_type': road_type,
            'instruction': step.get('instruction', ''),
        })

    # Deduplicate CONSECUTIVE roads with the same road name while preserving travel order
    deduped = []
    for road in raw_roads:
        if not deduped:
            deduped.append(dict(road))
        else:
            last = deduped[-1]
            if last['name'] == road['name']:
                last['distance_meters'] += road['distance_meters']
                last['duration_seconds'] += road['duration_seconds']
                for ref in road['highway_refs']:
                    if ref not in last['highway_refs']:
                        last['highway_refs'].append(ref)
                if road['is_major_road']:
                    last['is_major_road'] = True
            else:
                deduped.append(dict(road))

    # Convert distances to miles and round values
    for r in deduped:
        r['distance_miles'] = round(r['distance_meters'] * METERS_TO_MILES, 2)
        r['duration_seconds'] = round(r['duration_seconds'], 1)

    # Filter out terminal 0-distance arrival markers if present
    clean_roads = [r for r in deduped if r['distance_meters'] > 0 or r['name'] != 'Road name unavailable']
    if not clean_roads and deduped:
        clean_roads = deduped

    travel_order_names = [r['name'] for r in clean_roads]
    major_roads_only = [r for r in clean_roads if r['is_major_road']]

    # Calculate Highway distance and percentage from ORS waycategory summary
    highway_meters = 0.0
    if waycategory_summary:
        for item in waycategory_summary:
            if item.get('value') in (1.0, 3.0, 1, 3):
                highway_meters += float(item.get('distance', 0.0))
    elif major_roads_only:
        highway_meters = sum(r['distance_meters'] for r in major_roads_only)

    highway_miles = round(highway_meters * METERS_TO_MILES, 2)
    tot_m = total_distance_meters if total_distance_meters > 0 else (sum(r['distance_meters'] for r in clean_roads) or 1.0)
    highway_pct = round(min(100.0, (highway_meters / tot_m) * 100.0), 1)

    # Calculate Toll distance and percentage from ORS tollways summary
    toll_meters = 0.0
    if tollways_summary:
        for item in tollways_summary:
            if item.get('value') in (1.0, 3.0, 1, 3):
                toll_meters += float(item.get('distance', 0.0))

    toll_miles = round(toll_meters * METERS_TO_MILES, 2)
    toll_pct = round(min(100.0, (toll_meters / tot_m) * 100.0), 1)

    return {
        'roads': clean_roads,
        'roads_travel_order': travel_order_names,
        'major_roads': major_roads_only,
        'highway_distance_miles': highway_miles,
        'highway_percentage': highway_pct,
        'toll_distance_miles': toll_miles,
        'toll_percentage': toll_pct,
        'has_toll_roads': toll_miles > 0,
        'total_roads_count': len(clean_roads),
    }


def generate_route_corridor_name(route_index: int, roads: list[dict], major_roads: list[dict]) -> tuple[str, str]:
    """
    Generates a natural, human-readable route name based on the actual primary highways
    and corridors used, e.g. ("Route 1: via B 37", "via B 37").
    """
    major_refs = []
    seen = set()
    for r in (major_roads or []):
        for ref in r.get('highway_refs', []):
            if ref not in seen:
                seen.add(ref)
                major_refs.append(ref)

    if major_refs:
        if len(major_refs) == 1:
            via = f"via {major_refs[0]}"
        elif len(major_refs) == 2:
            via = f"via {major_refs[0]} & {major_refs[1]}"
        elif len(major_refs) == 3:
            via = f"via {major_refs[0]}, {major_refs[1]} & {major_refs[2]}"
        else:
            sorted_by_dist = sorted(
                [r for r in major_roads if r.get('highway_refs')],
                key=lambda x: x.get('distance_meters', 0),
                reverse=True
            )
            top_refs = []
            for r in sorted_by_dist:
                for ref in r.get('highway_refs', []):
                    if ref not in top_refs:
                        top_refs.append(ref)
                    if len(top_refs) == 3:
                        break
                if len(top_refs) == 3:
                    break
            if len(top_refs) == 3:
                via = f"via {top_refs[0]}, {top_refs[1]} & {top_refs[2]}"
            elif len(top_refs) == 2:
                via = f"via {top_refs[0]} & {top_refs[1]}"
            else:
                via = f"via {top_refs[0]}" if top_refs else f"via {major_refs[0]}"
        return f"Route {route_index}: {via}", via

    named_roads = [
        r for r in (roads or [])
        if r.get('name') and r['name'] not in ('Road name unavailable', '-', '')
    ]
    if named_roads:
        longest = max(named_roads, key=lambda x: x.get('distance_meters', 0))
        via = f"via {longest['name']}"
        return f"Route {route_index}: {via}", via

    return f"Route {route_index}", f"Route {route_index}"


def ensure_unique_corridor_names(routes: list[dict]) -> list[dict]:
    """
    Ensures every route alternative has a unique, descriptive corridor name.
    If multiple routes share the same primary corridor name, distinguishes them
    with clean alternative letters, e.g. 'Route 2: via B 535 & B 36 (Alt A)'.
    """
    from collections import Counter
    corridor_counts = Counter(r.get('corridor_name') for r in routes if r.get('corridor_name'))

    seen = {}
    for idx, r in enumerate(routes):
        c_name = r.get('corridor_name')
        if not c_name:
            continue
        if corridor_counts[c_name] > 1:
            seen[c_name] = seen.get(c_name, 0) + 1
            alt_num = seen[c_name]
            alt_suffix = f"(Alt {chr(64 + alt_num)})"
            new_corridor = f"{c_name} {alt_suffix}"
            r['corridor_name'] = new_corridor
            r['name'] = f"Route {idx + 1}: {new_corridor}"
    return routes


def _parse_feature(feature, route_index, origin_coords, dest_coords, route_name_prefix="Route"):
    props = feature.get('properties', {})
    summary = props.get('summary', {})
    meters = float(summary.get('distance', 0.0))
    duration_sec = float(summary.get('duration', 0.0))
    if duration_sec <= 0 and meters > 0:
        # Graceful fallback duration based on standard truck speed (approx 50 mph)
        duration_sec = meters / 22.35

    geometry = feature.get('geometry', {})

    # Extract turn-by-turn road information and highway classification
    segments = props.get('segments', [])
    steps = segments[0].get('steps', []) if segments else []
    extras = props.get('extras', {})
    waycategory_values = extras.get('waycategory', {}).get('values', [])
    waycategory_summary = extras.get('waycategory', {}).get('summary', [])
    tollways_summary = extras.get('tollways', {}).get('summary', [])

    roads_info = parse_route_roads(
        steps=steps,
        waycategory_values=waycategory_values,
        waycategory_summary=waycategory_summary,
        tollways_summary=tollways_summary,
        total_distance_meters=meters,
    )

    full_name, corridor_label = generate_route_corridor_name(
        route_index,
        roads_info['roads'],
        roads_info['major_roads']
    )

    return {
        'id': f"route-{route_index}",
        'name': full_name,
        'corridor_name': corridor_label,
        'distance_miles': round(meters * METERS_TO_MILES, 2),
        'duration_seconds': round(duration_sec, 1),
        'geometry': geometry,
        'start_coordinates': origin_coords,
        'destination_coordinates': dest_coords,
        'roads_used': roads_info['roads'],
        'roads_travel_order': roads_info['roads_travel_order'],
        'major_roads': roads_info['major_roads'],
        'highway_distance_miles': roads_info['highway_distance_miles'],
        'highway_percentage': roads_info['highway_percentage'],
        'toll_distance_miles': roads_info['toll_distance_miles'],
        'toll_percentage': roads_info['toll_percentage'],
        'has_toll_roads': roads_info['has_toll_roads'],
    }


def get_routes(origin_coords: list, dest_coords: list) -> list:
    """
    Fetches driving-hgv route(s) between origin and destination coordinates [lon, lat].
    Attempts to fetch alternative routes. If the distance exceeds ORS limit (100km)
    for alternative_routes algorithm, gracefully falls back to multi-preference routing.
    Requests turn-by-turn instructions and highway/toll classification extras.
    """
    api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
    if not api_key:
        raise ValueError("OpenRouteService API key is missing on the server.")

    headers = {
        'Authorization': api_key,
        'Content-Type': 'application/json'
    }

    # Attempt 1: alternative_routes parameter with instructions and waycategory/tollways
    body_alt = {
        'coordinates': [origin_coords, dest_coords],
        'instructions': True,
        'extra_info': ['waycategory', 'tollways'],
        'alternative_routes': {
            'target_count': 3,
            'weight_factor': 1.4,
            'share_factor': 0.6
        }
    }

    try:
        resp = requests.post(ORS_DIRECTIONS_HGV_URL, json=body_alt, headers=headers, timeout=15)
        # If extra_info was rejected by older ORS profile, retry without extra_info
        if resp.status_code == 400 and 'extra_info' in resp.text:
            body_alt_simple = dict(body_alt)
            body_alt_simple.pop('extra_info', None)
            resp = requests.post(ORS_DIRECTIONS_HGV_URL, json=body_alt_simple, headers=headers, timeout=15)

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
                    parsed_routes = [
                        _parse_feature(f, idx + 1, origin_coords, dest_coords)
                        for idx, f in enumerate(unique_features[:3])
                    ]
                    return ensure_unique_corridor_names(parsed_routes)
    except requests.RequestException as e:
        logger.warning(f"Alternative routes request failed: {e}")

    # Fallback for >100km or when alternative_routes returns non-200 (e.g. code 2004 limit):
    # We fetch routes using distinct preferences ('recommended' and 'shortest')
    routes = []
    seen_distances = set()

    for pref in ['recommended', 'shortest']:
        body_pref = {
            'coordinates': [origin_coords, dest_coords],
            'instructions': True,
            'extra_info': ['waycategory', 'tollways'],
            'preference': pref
        }
        try:
            r = requests.post(ORS_DIRECTIONS_HGV_URL, json=body_pref, headers=headers, timeout=15)
            if r.status_code == 400 and 'extra_info' in r.text:
                body_pref_simple = dict(body_pref)
                body_pref_simple.pop('extra_info', None)
                r = requests.post(ORS_DIRECTIONS_HGV_URL, json=body_pref_simple, headers=headers, timeout=15)

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

    return ensure_unique_corridor_names(routes)

