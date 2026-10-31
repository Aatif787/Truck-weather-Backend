import requests
import re
import math
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

ORS_GEOCODE_URL = 'https://api.openrouteservice.org/geocode/search'
ORS_DIRECTIONS_HGV_URL = 'https://api.openrouteservice.org/v2/directions/driving-hgv/geojson'
ORS_DIRECTIONS_CAR_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'

METERS_TO_MILES = 0.000621371


def _geocode_nominatim(query: str) -> tuple[dict | None, bool]:
    """Fallback geocoding using OpenStreetMap Nominatim API. Returns (result_dict, is_network_error)."""
    try:
        nom_headers = {
            'User-Agent': 'SpotterFleetRoute/2.5 (Commercial HGV Logistics Engine; https://truck-weather-frontend-waqe.vercel.app)'
        }
        nom_resp = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': query.strip(), 'format': 'json', 'limit': 1},
            headers=nom_headers,
            timeout=8
        )
        if nom_resp.status_code == 200:
            nom_data = nom_resp.json()
            if nom_data and len(nom_data) > 0:
                first = nom_data[0]
                return {
                    'name': first.get('display_name') or query,
                    'coordinates': [float(first['lon']), float(first['lat'])]
                }, False
        return None, False
    except requests.RequestException as e:
        logger.warning(f"Nominatim fallback geocoding failed: {e}")
        return None, True
    except Exception as e:
        logger.warning(f"Nominatim fallback parsing failed: {e}")
        return None, False


def geocode_location(query: str) -> dict:
    """
    Geocodes a query string (e.g. city or address) to [lon, lat] and a display name.
    Attempts OpenRouteService first when configured; automatically falls back
    to OpenStreetMap Nominatim if ORS is unauthorized, rate-limited, or unavailable.
    Returns: {"name": str, "coordinates": [lon, lat]}
    Raises ValueError on location not found or complete geocoding failure.
    """
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Location query cannot be empty.")

    network_error = False
    api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
    if api_key:
        headers = {'Authorization': api_key}
        params = {'text': clean_query, 'size': 1}
        try:
            resp = requests.get(ORS_GEOCODE_URL, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get('features', [])
                if features:
                    first = features[0]
                    coords = first.get('geometry', {}).get('coordinates', [])
                    if len(coords) >= 2:
                        label = first.get('properties', {}).get('label') or first.get('properties', {}).get('name') or clean_query
                        return {
                            'name': label,
                            'coordinates': [float(coords[0]), float(coords[1])]
                        }
            else:
                logger.warning(f"ORS geocode returned HTTP {resp.status_code}. Attempting Nominatim fallback.")
        except requests.RequestException as e:
            logger.warning(f"ORS geocoding request failed: {e}. Attempting Nominatim fallback.")
            network_error = True

    # Resilient fallback: OpenStreetMap Nominatim
    nom_result, nom_network_error = _geocode_nominatim(clean_query)
    if nom_result:
        return nom_result

    if network_error and nom_network_error:
        raise ValueError("Geocoding service unavailable or timed out.")

    raise ValueError(f"Location not found: '{clean_query}'")


HIGHWAY_REF_PATTERNS = [
    re.compile(r'\b(A\s?\d+)\b', re.I),           # Autobahn / European Motorway
    re.compile(r'\b(B\s?\d+)\b', re.I),           # German Federal Highway (Bundesstraße)
    re.compile(r'\b(I[- ]?\d+)\b', re.I),         # US Interstate
    re.compile(r'\b(US[- ]?\d+)\b', re.I),        # US Highway
    re.compile(r'\b(NH[- ]?\d+[A-Z]?)\b', re.I),  # National Highway (India / International)
    re.compile(r'\b(SH[- ]?\d+[A-Z]?)\b', re.I),  # State Highway
    re.compile(r'\b(NE[- ]?\d+)\b', re.I),        # National Expressway
    re.compile(r'\b(NEX)\b', re.I),               # National Expressway code
    re.compile(r'\b(AH[- ]?\d+)\b', re.I),        # Asian Highway
    re.compile(r'\b(E\s?\d+)\b', re.I),           # European E-road
    re.compile(r'\b(M\s?\d+)\b', re.I),           # UK Motorway
    re.compile(r'\b(L\s?\d+)\b', re.I),           # Landesstraße
    re.compile(r'\b(K\s?\d+)\b', re.I),           # Kreisstraße
    re.compile(r'\b(State (?:Route|Hwy)\s?\d+)\b', re.I),
    re.compile(r'\b(Route\s?\d+)\b', re.I),
    re.compile(r'\b(Highway\s?\d+)\b', re.I),
]


def extract_highway_refs(name: str) -> list[str]:
    """Extracts standard highway and road reference codes (e.g. A 5, B 37, I-80, NH-44)."""
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
    if any(k in lower for k in ['autobahn', 'motorway', 'interstate', 'expressway', 'freeway', 'turnpike', 'national highway', 'express way']):
        return True
    for pat in HIGHWAY_REF_PATTERNS:
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
    Parses turn-by-turn steps from routing directions into an ordered list
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
        ref_field = (step.get('ref') or '').strip()
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
        if ref_field:
            clean_ref = ref_field.strip().upper()
            if clean_ref and clean_ref not in refs:
                refs.append(clean_ref)
            if not is_major:
                is_major = is_major_classification(clean_ref)

        if not name or name == '-':
            if cat_id in (1, 3) or is_major:
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


def _parse_osrm_route(osrm_route: dict, route_index: int, origin_coords: list, dest_coords: list) -> dict:
    """
    Converts an OpenStreetMap OSRM route response into the standard RouteItem format.
    Extracts genuine geometries, distances, durations, and turn-by-turn road segments.
    """
    meters = float(osrm_route.get('distance', 0.0))
    duration_sec = float(osrm_route.get('duration', 0.0))
    if duration_sec <= 0 and meters > 0:
        duration_sec = meters / 22.35

    geometry = osrm_route.get('geometry', {})
    legs = osrm_route.get('legs', [])
    steps = []
    for leg in legs:
        for s in leg.get('steps', []):
            name = (s.get('name') or '').strip()
            ref = (s.get('ref') or '').strip()
            if not name and ref:
                name = ref
            elif name and ref and ref not in name:
                name = f"{name} ({ref})"
            steps.append({
                'name': name,
                'distance': float(s.get('distance', 0.0)),
                'duration': float(s.get('duration', 0.0)),
                'ref': ref,
                'instruction': s.get('maneuver', {}).get('type', ''),
            })

    roads_info = parse_route_roads(
        steps=steps,
        total_distance_meters=meters
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


def _get_osrm_routes(origin_coords: list, dest_coords: list) -> list:
    """
    Fetches real routes and turn-by-turn road data from OpenStreetMap OSRM routing engine
    when OpenRouteService is unauthorized, quota-limited, or unavailable.
    Guarantees up to 3 viable distinct route alternatives.
    """
    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{origin_coords[0]},{origin_coords[1]};{dest_coords[0]},{dest_coords[1]}"
        f"?overview=full&geometries=geojson&steps=true&alternatives=true"
    )
    headers = {
        'User-Agent': 'SpotterFleetRoute/2.5 (Commercial HGV Logistics Engine; https://truck-weather-frontend-waqe.vercel.app)'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            osrm_routes = data.get('routes', [])
            if not osrm_routes:
                return []

            # If fewer than 3 routes returned, discover an additional alternative via perpendicular offset waypoint
            if len(osrm_routes) < 3:
                fastest_route = min(osrm_routes, key=lambda r: float(r.get('duration', float('inf'))))
                fastest_coords = fastest_route.get('geometry', {}).get('coordinates', [])
                if fastest_coords:
                    mid_idx = len(fastest_coords) // 2
                    mx, my = fastest_coords[mid_idx][0], fastest_coords[mid_idx][1]
                else:
                    mx = (origin_coords[0] + dest_coords[0]) / 2.0
                    my = (origin_coords[1] + dest_coords[1]) / 2.0

                dx = dest_coords[0] - origin_coords[0]
                dy = dest_coords[1] - origin_coords[1]
                dist = math.hypot(dx, dy)

                if dist > 0.05:
                    existing_sets = [
                        {(round(c[0], 3), round(c[1], 3)) for c in r.get('geometry', {}).get('coordinates', [])}
                        for r in osrm_routes
                    ]
                    for sign in [1.0, -1.0]:
                        px = mx - sign * dy * 0.08
                        py = my + sign * dx * 0.08
                        via_url = (
                            f"http://router.project-osrm.org/route/v1/driving/"
                            f"{origin_coords[0]},{origin_coords[1]};{px:.4f},{py:.4f};{dest_coords[0]},{dest_coords[1]}"
                            f"?overview=full&geometries=geojson&steps=true"
                        )
                        try:
                            via_resp = requests.get(via_url, headers=headers, timeout=8)
                            if via_resp.status_code == 200:
                                via_routes = via_resp.json().get('routes', [])
                                if via_routes:
                                    cand = via_routes[0]
                                    cand_set = {
                                        (round(c[0], 3), round(c[1], 3))
                                        for c in cand.get('geometry', {}).get('coordinates', [])
                                    }
                                    max_overlap = 0.0
                                    for ex_set in existing_sets:
                                        if ex_set:
                                            overlap = len(cand_set & ex_set) / max(len(cand_set), 1)
                                            if overlap > max_overlap:
                                                max_overlap = overlap
                                    # Deduplicate: discard if geometry overlaps >85% with an existing route
                                    if max_overlap <= 0.85:
                                        osrm_routes.append(cand)
                                        existing_sets.append(cand_set)
                                        if len(osrm_routes) >= 3:
                                            break
                        except Exception as e:
                            logger.debug(f"OSRM via route attempt error: {e}")

            parsed_routes = []
            seen_distances = set()
            for idx, r in enumerate(osrm_routes[:3]):
                parsed = _parse_osrm_route(r, idx + 1, origin_coords, dest_coords)
                if parsed['distance_miles'] not in seen_distances:
                    seen_distances.add(parsed['distance_miles'])
                    parsed_routes.append(parsed)
            return parsed_routes
        else:
            logger.warning(f"OSRM routing returned HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"OSRM fallback routing request failed: {e}")
    return []


def get_routes(origin_coords: list, dest_coords: list) -> list:
    """
    Fetches driving-hgv route(s) between origin and destination coordinates [lon, lat].
    Attempts OpenRouteService first with turn-by-turn steps and highway classification extras.
    If ORS is unauthorized (401), quota exceeded (403/429), or fails, seamlessly falls back
    to OpenStreetMap OSRM routing so service remains 100% available with genuine data.
    """
    api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
    routes = []
    seen_distances = set()
    ors_failed = False

    if api_key:
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
            elif resp.status_code in (401, 403, 429):
                logger.warning(f"ORS directions returned HTTP {resp.status_code}.")
                ors_failed = True
        except requests.RequestException as e:
            logger.warning(f"Alternative routes request failed: {e}")
            ors_failed = True

        # Fallback for >100km or when alternative_routes returns non-200 (unless ORS auth failed)
        if not ors_failed:
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
                            if parsed['distance_miles'] not in seen_distances:
                                seen_distances.add(parsed['distance_miles'])
                                routes.append(parsed)
                    elif r.status_code in (401, 403, 429):
                        ors_failed = True
                        break
                except requests.RequestException as e:
                    logger.error(f"Route query error for preference {pref}: {e}")
                    ors_failed = True
                    break
    else:
        ors_failed = True

    if len(routes) >= 3:
        return ensure_unique_corridor_names(routes)

    # If ORS failed or returned fewer than 3 routes, query OSRM routing engine with alternatives=true
    logger.info("Querying OpenStreetMap OSRM routing engine for alternative corridors...")
    osrm_routes = _get_osrm_routes(origin_coords, dest_coords)
    if len(osrm_routes) >= len(routes) and osrm_routes:
        return ensure_unique_corridor_names(osrm_routes)

    if routes:
        return ensure_unique_corridor_names(routes)

    if osrm_routes:
        return ensure_unique_corridor_names(osrm_routes)

    raise ValueError("No viable truck routes could be calculated for these locations.")
