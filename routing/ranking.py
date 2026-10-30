"""
Deterministic Route Ranking Engine for Weather-Aware Truck Routing.

Ranking Priority Order:
1. Fewest total miles classified as SEVERE.
2. Fewest total miles classified as HIGH (tie-breaker 1).
3. Lowest average checkpoint risk score (tie-breaker 2).
4. Shortest estimated travel duration in seconds (tie-breaker 3).
5. Route ID ascending (deterministic tie-breaker 4).

Explicit Risk Numeric Scores:
- LOW: 0.0
- MODERATE: 1.0
- HIGH: 2.0
- SEVERE: 3.0
- NO_TRAVEL: 4.0

UNKNOWN Handling:
- Missing or UNKNOWN weather data is assigned a conservative penalty score of 3.0 (equivalent to SEVERE).
- UNKNOWN is NEVER treated as LOW.
- Any route with UNKNOWN checkpoints is flagged with is_complete_analysis = False.

Safety & NO_TRAVEL Rules:
- A route containing any NO_TRAVEL checkpoint is NEVER recommended or labeled safe.
- If all routes have NO_TRAVEL conditions, no route is recommended and a clear warning is returned.
"""

from typing import Any

RISK_NUMERIC_SCORES = {
    'LOW': 0.0,
    'MODERATE': 1.0,
    'HIGH': 2.0,
    'SEVERE': 3.0,
    'NO_TRAVEL': 4.0,
}

# Conservative score penalty for UNKNOWN weather risk to avoid treating missing data as low risk
UNKNOWN_RISK_SCORE = 3.0


def calculate_represented_distances(checkpoints: list[dict[str, Any]], total_distance_miles: float) -> list[float]:
    """
    Estimates the distance represented by each checkpoint using Voronoi midpoint intervals
    along the route's cumulative distance.
    The sum of represented distances across all checkpoints exactly equals total_distance_miles.
    """
    n = len(checkpoints)
    if n == 0:
        return []
    if n == 1:
        return [round(total_distance_miles, 2)]

    distances = [float(cp.get("distance_from_origin_miles", 0.0)) for cp in checkpoints]
    represented = []

    for i in range(n):
        if i == 0:
            # Segment from start (0.0) to midpoint between cp[0] and cp[1]
            rep = (distances[1] - distances[0]) / 2.0
        elif i == n - 1:
            # Segment from midpoint between cp[n-2] and cp[n-1] to total_distance_miles
            rep = (total_distance_miles - distances[n - 1]) + (distances[n - 1] - distances[n - 2]) / 2.0
        else:
            # Segment between previous midpoint and next midpoint
            rep = (distances[i + 1] - distances[i - 1]) / 2.0

        represented.append(max(0.0, round(rep, 2)))

    return represented


def compute_route_weather_metrics(route: dict[str, Any]) -> dict[str, Any]:
    """
    Calculates severe miles, high miles, no-travel miles, average risk score,
    and analysis completeness for a single route.
    """
    checkpoints = route.get("checkpoints", [])
    total_dist = float(route.get("distance_miles", 0.0))
    n = len(checkpoints)

    rep_distances = calculate_represented_distances(checkpoints, total_dist)

    severe_miles = 0.0
    high_miles = 0.0
    no_travel_miles = 0.0
    risk_scores = []
    has_no_travel = False
    has_unknown = False

    for idx, cp in enumerate(checkpoints):
        risk = str(cp.get("final_risk", "UNKNOWN")).upper()
        rep_dist = rep_distances[idx] if idx < len(rep_distances) else 0.0

        # Accumulate mileages
        if risk == "SEVERE":
            severe_miles += rep_dist
        elif risk == "HIGH":
            high_miles += rep_dist
        elif risk == "NO_TRAVEL":
            no_travel_miles += rep_dist
            has_no_travel = True
        elif risk == "UNKNOWN":
            has_unknown = True

        # Check weather status
        if cp.get("weather_status") in ("UNKNOWN", "ERROR") or risk == "UNKNOWN":
            has_unknown = True
            risk_scores.append(UNKNOWN_RISK_SCORE)
        else:
            risk_scores.append(RISK_NUMERIC_SCORES.get(risk, UNKNOWN_RISK_SCORE))

    if n > 0:
        avg_risk = sum(risk_scores) / float(n)
    else:
        # Route has no checkpoints -> conservative penalty
        avg_risk = UNKNOWN_RISK_SCORE
        has_unknown = True

    route["severe_miles"] = round(severe_miles, 2)
    route["high_miles"] = round(high_miles, 2)
    route["no_travel_miles"] = round(no_travel_miles, 2)
    route["average_risk_score"] = round(avg_risk, 3)
    route["has_no_travel"] = has_no_travel
    route["has_unknown_weather"] = has_unknown
    route["is_complete_analysis"] = not has_unknown

    return route


def rank_and_recommend_routes(routes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Ranks routes by:
    1. Fewest severe miles
    2. Fewest high miles
    3. Lowest average risk score
    4. Shortest travel duration (seconds)
    5. Route ID (stable tie-breaker)

    Applies strict safety rules:
    - Never recommends routes with NO_TRAVEL conditions.
    - Emits a clear warning if all routes contain NO_TRAVEL conditions.
    """
    if not routes:
        return {
            "routes": [],
            "recommended_route_id": None,
            "has_recommended_route": False,
            "warning": "No route options available."
        }

    # Step 1: Compute metrics for each route
    processed_routes = [compute_route_weather_metrics(dict(r)) for r in routes]

    # Step 2: Sort deterministically
    def sort_key(r: dict[str, Any]) -> tuple:
        return (
            r.get("severe_miles", 0.0),
            r.get("high_miles", 0.0),
            r.get("average_risk_score", 0.0),
            float(r.get("duration_seconds", 0.0)),
            str(r.get("id", ""))
        )

    ranked_routes = sorted(processed_routes, key=sort_key)

    # Step 3: Assign ranking position (1-based)
    for rank_idx, r in enumerate(ranked_routes):
        r["rank"] = rank_idx + 1

    # Step 4: Identify best eligible route (no NO_TRAVEL conditions)
    eligible_routes = [r for r in ranked_routes if not r.get("has_no_travel", False)]

    recommended_route_id = None
    warning_message = None

    if eligible_routes:
        best_route = eligible_routes[0]
        recommended_route_id = best_route["id"]

        for r in ranked_routes:
            if r["id"] == recommended_route_id:
                r["is_recommended"] = True
                r["recommendation_status"] = "RECOMMENDED"
                if r.get("has_unknown_weather"):
                    r["recommendation_label"] = "Recommended Route (Incomplete Weather Data)"
                else:
                    r["recommendation_label"] = "Recommended Safest Route"
            elif r.get("has_no_travel"):
                r["is_recommended"] = False
                r["recommendation_status"] = "NO_TRAVEL_WARNING"
                r["recommendation_label"] = "Unsafe for Travel (Severe / No Travel Conditions)"
            else:
                r["is_recommended"] = False
                r["recommendation_status"] = "ALTERNATIVE"
                r["recommendation_label"] = "Alternative Route"
    else:
        # ALL routes contain NO_TRAVEL conditions
        warning_message = "DANGER: All route alternatives contain NO_TRAVEL weather conditions. Travel is not recommended."
        for r in ranked_routes:
            r["is_recommended"] = False
            r["recommendation_status"] = "NO_TRAVEL_WARNING"
            r["recommendation_label"] = "Unsafe for Travel (NO_TRAVEL Conditions)"

    return {
        "routes": ranked_routes,
        "recommended_route_id": recommended_route_id,
        "has_recommended_route": recommended_route_id is not None,
        "warning": warning_message
    }

