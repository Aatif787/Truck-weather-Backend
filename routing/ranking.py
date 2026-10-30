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

# Baseline commercial Class 8 HGV fuel consumption assumptions
DEFAULT_DIESEL_PRICE_USD = 3.85
DEFAULT_HGV_MPG = 6.5


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
    Calculates severe miles, high miles, moderate miles, low miles, average risk score,
    composite safety score, estimated fuel cost, and analysis completeness for a single route.
    """
    checkpoints = route.get("checkpoints", [])
    total_dist = float(route.get("distance_miles", 0.0))
    n = len(checkpoints)

    rep_distances = calculate_represented_distances(checkpoints, total_dist)

    low_miles = 0.0
    moderate_miles = 0.0
    high_miles = 0.0
    severe_miles = 0.0
    no_travel_miles = 0.0
    risk_scores = []
    has_no_travel = False
    has_unknown = False

    for idx, cp in enumerate(checkpoints):
        risk = str(cp.get("final_risk", "UNKNOWN")).upper()
        rep_dist = rep_distances[idx] if idx < len(rep_distances) else 0.0

        # Accumulate mileages
        if risk == "LOW":
            low_miles += rep_dist
        elif risk == "MODERATE":
            moderate_miles += rep_dist
        elif risk == "HIGH":
            high_miles += rep_dist
        elif risk == "SEVERE":
            severe_miles += rep_dist
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

    # Deterministic Safety Score Calculation (0.0 to 100.0)
    # Severe weather miles deduct 10 pts/mi; High risk miles deduct 4 pts/mi; Avg risk deducts 12 pts/point
    if has_no_travel:
        safety_score = 0.0
    else:
        penalty = (severe_miles * 10.0) + (high_miles * 4.0) + (avg_risk * 12.0)
        safety_score = max(5.0, round(100.0 - penalty, 1))

    # Baseline commercial fuel estimation (Class 8 standard: 6.5 MPG, $3.85/gal)
    fuel_gallons = round(total_dist / DEFAULT_HGV_MPG, 1) if DEFAULT_HGV_MPG > 0 else 0.0
    fuel_cost_est = round(fuel_gallons * DEFAULT_DIESEL_PRICE_USD, 2)

    route["low_miles"] = round(low_miles, 2)
    route["moderate_miles"] = round(moderate_miles, 2)
    route["severe_miles"] = round(severe_miles, 2)
    route["high_miles"] = round(high_miles, 2)
    route["no_travel_miles"] = round(no_travel_miles, 2)
    route["average_risk_score"] = round(avg_risk, 3)
    route["safety_score"] = safety_score
    route["estimated_fuel_gallons"] = fuel_gallons
    route["estimated_fuel_cost"] = fuel_cost_est
    route["has_no_travel"] = has_no_travel
    route["has_unknown_weather"] = has_unknown
    route["is_complete_analysis"] = not has_unknown

    return route


def rank_and_recommend_routes(routes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Ranks candidate routes using a multi-criteria safety evaluation:
    1. Fewest severe miles
    2. Fewest high miles
    3. Lowest average risk score
    4. Shortest travel duration (seconds)
    5. Route ID (stable tie-breaker)

    Applies strict safety rules:
    - Never recommends routes with NO_TRAVEL conditions.
    - Emits a clear warning if all routes contain NO_TRAVEL conditions.
    - Generates transparent algorithmic rationale and trade-off comparison.
    """
    if not routes:
        return {
            "routes": [],
            "recommended_route_id": None,
            "has_recommended_route": False,
            "warning": "No route options available.",
            "recommendation_rationale": "No routes available to analyze.",
            "tradeoffs": {},
            "severe_alerts": [],
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

    # Step 5: Identify Shortest & Fastest routes for trade-off analysis
    shortest_route = min(ranked_routes, key=lambda r: float(r.get("distance_miles", 0.0))) if ranked_routes else None
    fastest_route = min(ranked_routes, key=lambda r: float(r.get("duration_seconds", 0.0))) if ranked_routes else None

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

        # Construct transparent, rule-based algorithmic rationale
        dist_diff = round(float(best_route.get("distance_miles", 0)) - float(shortest_route.get("distance_miles", 0)), 1) if shortest_route else 0
        time_diff_mins = round((float(best_route.get("duration_seconds", 0)) - float(fastest_route.get("duration_seconds", 0))) / 60) if fastest_route else 0

        best_name = best_route.get('name', f"Route {best_route.get('id', '')}")
        shortest_name = shortest_route.get('name', f"Route {shortest_route.get('id', '')}") if shortest_route else ""
        fastest_name = fastest_route.get('name', f"Route {fastest_route.get('id', '')}") if fastest_route else ""

        rationale_items = [
            f"{best_name} is selected by our deterministic multi-criteria safety evaluation "
            f"because it minimizes commercial hazard exposure with {best_route.get('severe_miles', 0.0)} severe-weather miles "
            f"and {best_route.get('high_miles', 0.0)} high-risk miles (Safety Score: {best_route.get('safety_score', 0)}/100)."
        ]

        if shortest_route and shortest_route['id'] != best_route['id']:
            rationale_items.append(
                f"The shortest alternative ({shortest_name}) saves {abs(dist_diff)} miles, "
                f"but carries {shortest_route.get('severe_miles', 0.0)} severe miles and {shortest_route.get('high_miles', 0.0)} high-risk miles."
            )
        elif shortest_route and shortest_route['id'] == best_route['id']:
            rationale_items.append("It is simultaneously the shortest direct highway path.")

        if fastest_route and fastest_route['id'] != best_route['id']:
            rationale_items.append(
                f"The fastest alternative ({fastest_name}) is {abs(time_diff_mins)} min quicker, "
                f"but exposes cargo to higher meteorological risk."
            )
        elif fastest_route and fastest_route['id'] == best_route['id'] and (not shortest_route or shortest_route['id'] != best_route['id']):
            rationale_items.append("It also provides the fastest transit duration.")

        recommendation_rationale = " ".join(rationale_items)

    else:
        # ALL routes contain NO_TRAVEL conditions
        warning_message = "DANGER: All route alternatives contain NO_TRAVEL weather conditions. Travel is not recommended."
        recommendation_rationale = (
            "NO DISPATCH RECOMMENDED: Every evaluated highway alternative crosses hazardous weather exceeding "
            "safe Class 8 commercial operating thresholds (NO_TRAVEL conditions encountered)."
        )
        for r in ranked_routes:
            r["is_recommended"] = False
            r["recommendation_status"] = "NO_TRAVEL_WARNING"
            r["recommendation_label"] = "Unsafe for Travel (NO_TRAVEL Conditions)"

    # Step 6: Extract Severe Weather Alerts across all evaluated checkpoints
    severe_alerts = []
    for r in ranked_routes:
        for cp in r.get("checkpoints", []):
            risk = str(cp.get("final_risk", "")).upper()
            if risk in ("SEVERE", "NO_TRAVEL"):
                if risk == "NO_TRAVEL":
                    rec_action = (
                        "SUSPEND TRANSIT: Conditions exceed safe tractor-trailer operating parameters. "
                        "Hold at current depot or seek designated safe parking until squall clears."
                    )
                else:
                    rec_action = (
                        "EXERCISE EXTREME CAUTION: Reduce highway speed to ≤45 mph, maintain 8+ seconds headway, "
                        "and anticipate sudden localized crosswind gusts."
                    )

                severe_alerts.append({
                    "route_id": r.get("id"),
                    "route_name": r.get("name"),
                    "checkpoint_index": cp.get("checkpoint_index"),
                    "distance_from_origin_miles": cp.get("distance_from_origin_miles"),
                    "coordinates": cp.get("coordinates"),
                    "estimated_arrival_time": cp.get("estimated_arrival_time"),
                    "risk": risk,
                    "wind_speed_mph": cp.get("wind_speed_mph"),
                    "rain_intensity_in_hr": cp.get("rain_intensity_in_hr"),
                    "snow_intensity_in_hr": cp.get("snow_intensity_in_hr"),
                    "load_adjusted_wind_risk": cp.get("load_adjusted_wind_risk"),
                    "recommended_action": rec_action,
                })

    tradeoffs = {
        "safest_route_id": recommended_route_id,
        "shortest_route_id": shortest_route["id"] if shortest_route else None,
        "fastest_route_id": fastest_route["id"] if fastest_route else None,
    }

    return {
        "routes": ranked_routes,
        "recommended_route_id": recommended_route_id,
        "has_recommended_route": recommended_route_id is not None,
        "warning": warning_message,
        "recommendation_rationale": recommendation_rationale,
        "tradeoffs": tradeoffs,
        "severe_alerts": severe_alerts,
    }
