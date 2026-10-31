import math
from datetime import datetime, timedelta, timezone

EARTH_RADIUS_MILES = 3958.7613
METERS_TO_MILES = 0.000621371

def haversine_distance(coord1: list[float], coord2: list[float]) -> float:
    """
    Computes great-circle distance between two [lon, lat] points in miles.
    """
    lon1, lat1 = math.radians(coord1[0]), math.radians(coord1[1])
    lon2, lat2 = math.radians(coord2[0]), math.radians(coord2[1])

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    c = 2.0 * math.asin(math.sqrt(a))
    return c * EARTH_RADIUS_MILES

def generate_checkpoints(
    coordinates: list[list[float]],
    total_distance_miles: float,
    total_duration_seconds: float,
    departure_datetime: datetime,
    sampling_interval_miles: float = 25.0,
    roads_used: list[dict] | None = None
) -> list[dict]:
    """
    Generates route checkpoints sampled along the route geometry.
    - Checkpoint 0 is at origin (0.0 miles, departure time).
    - Samples every sampling_interval_miles (10, 25, or 50 miles).
    - Guarantees the destination is included.
    - Avoids duplicate checkpoints if destination is within 1.0 mile of the last sample.
    - Calculates distance from origin, ETA, and road/corridor name for each checkpoint.
    """
    if not coordinates:
        return []

    # Map cumulative distances to roads if roads_used provided
    road_intervals = []
    if roads_used:
        cum_mi = 0.0
        for r in roads_used:
            dist_mi = float(r.get('distance_meters', 0.0)) * METERS_TO_MILES
            if dist_mi <= 0 and 'distance_miles' in r:
                dist_mi = float(r['distance_miles'])
            start_d = cum_mi
            end_d = cum_mi + dist_mi
            cum_mi = end_d
            road_intervals.append({
                'name': r.get('name', 'Corridor Route'),
                'highway_refs': r.get('highway_refs', []),
                'is_major': r.get('is_major_road', False),
                'start_miles': start_d,
                'end_miles': end_d,
            })

    # Ensure departure datetime is timezone-aware UTC
    if departure_datetime.tzinfo is None:
        dep_time = departure_datetime.replace(tzinfo=timezone.utc)
    else:
        dep_time = departure_datetime.astimezone(timezone.utc)

    # Fallback duration if missing or invalid
    if total_duration_seconds is None or total_duration_seconds <= 0:
        total_duration_seconds = (total_distance_miles / 50.0) * 3600.0 if total_distance_miles > 0 else 0.0

    if len(coordinates) == 1 or total_distance_miles <= 0:
        first_road = road_intervals[0]['name'] if road_intervals else "Origin Point"
        first_refs = road_intervals[0]['highway_refs'] if road_intervals else []
        return [{
            "checkpoint_index": 0,
            "coordinates": [round(coordinates[0][0], 6), round(coordinates[0][1], 6)],
            "distance_from_origin_miles": 0.0,
            "estimated_arrival_time": dep_time.isoformat(),
            "road_name": first_road,
            "highway_refs": first_refs,
        }]

    # Step 1: Compute cumulative distances along the raw polyline
    seg_distances = []
    cum_distances = [0.0]
    for i in range(len(coordinates) - 1):
        d = haversine_distance(coordinates[i], coordinates[i + 1])
        seg_distances.append(d)
        cum_distances.append(cum_distances[-1] + d)

    raw_total_geo_miles = cum_distances[-1]
    scale_factor = (total_distance_miles / raw_total_geo_miles) if raw_total_geo_miles > 0 else 1.0
    scaled_cum_distances = [c * scale_factor for c in cum_distances]

    # Step 2: Determine target distances along the route
    target_distances = [0.0]
    next_dist = float(sampling_interval_miles)
    while next_dist < total_distance_miles:
        target_distances.append(round(next_dist, 2))
        next_dist += sampling_interval_miles

    # Avoid duplicate checkpoint if destination is within 1.0 mile of the last sample
    distance_to_dest = total_distance_miles - target_distances[-1]
    if distance_to_dest > 1.0:
        target_distances.append(round(total_distance_miles, 2))
    elif len(target_distances) > 1:
        # Replace the last sample with the exact destination
        target_distances[-1] = round(total_distance_miles, 2)
    else:
        # If route is very short (< 1.0 mile), include both start and destination
        target_distances.append(round(total_distance_miles, 2))

    # Step 3: Interpolate coordinates and ETA for each target distance
    checkpoints = []
    seg_idx = 0
    num_segments = len(coordinates) - 1

    for idx, target_d in enumerate(target_distances):
        # Progress along segments until we find the segment enclosing target_d
        while seg_idx < num_segments - 1 and scaled_cum_distances[seg_idx + 1] < target_d:
            seg_idx += 1

        d_start = scaled_cum_distances[seg_idx]
        d_end = scaled_cum_distances[seg_idx + 1]
        p_start = coordinates[seg_idx]
        p_end = coordinates[seg_idx + 1]

        if d_end > d_start:
            fraction = max(0.0, min(1.0, (target_d - d_start) / (d_end - d_start)))
        else:
            fraction = 0.0

        interp_lon = p_start[0] + fraction * (p_end[0] - p_start[0])
        interp_lat = p_start[1] + fraction * (p_end[1] - p_start[1])

        # Exact bounds handling
        if idx == 0:
            interp_lon, interp_lat = coordinates[0][0], coordinates[0][1]
        elif idx == len(target_distances) - 1:
            interp_lon, interp_lat = coordinates[-1][0], coordinates[-1][1]

        # Calculate ETA based on progress along total distance
        if total_distance_miles > 0:
            progress_ratio = target_d / total_distance_miles
        else:
            progress_ratio = 0.0

        elapsed_sec = progress_ratio * total_duration_seconds
        eta = dep_time + timedelta(seconds=elapsed_sec)

        # Match road for this target distance
        assigned_road = None
        for r_int in road_intervals:
            if r_int['start_miles'] <= target_d <= r_int['end_miles'] + 0.1:
                assigned_road = r_int
                break
        if not assigned_road and road_intervals:
            assigned_road = road_intervals[-1] if target_d >= road_intervals[-1]['end_miles'] else road_intervals[0]

        road_name = assigned_road['name'] if assigned_road else "Corridor Route"
        highway_refs = assigned_road['highway_refs'] if assigned_road else []

        checkpoints.append({
            "checkpoint_index": idx,
            "coordinates": [round(interp_lon, 6), round(interp_lat, 6)],
            "distance_from_origin_miles": round(target_d, 2),
            "estimated_arrival_time": eta.isoformat(),
            "road_name": road_name,
            "highway_refs": highway_refs,
        })

    return checkpoints

