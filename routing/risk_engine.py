"""
Risk Calculation Engine for Weather-Aware Truck Routing.

Risk Levels:
- LOW
- MODERATE
- HIGH
- SEVERE
- NO_TRAVEL
- UNKNOWN
"""

LOW = "LOW"
MODERATE = "MODERATE"
HIGH = "HIGH"
SEVERE = "SEVERE"
NO_TRAVEL = "NO_TRAVEL"
UNKNOWN = "UNKNOWN"

# Severity order: higher index means higher severity
SEVERITY_ORDER = {
    UNKNOWN: -1,
    LOW: 1,
    MODERATE: 2,
    HIGH: 3,
    SEVERE: 4,
    NO_TRAVEL: 5,
}

def calculate_wind_risk(wind_mph: float | None) -> str:
    """
    Wind thresholds:
    - Below 25 mph: LOW.
    - 25 to below 35 mph: MODERATE.
    - 35 to below 45 mph: HIGH.
    - 45 to below 55 mph: SEVERE.
    - 55 mph or above: NO_TRAVEL.
    """
    if wind_mph is None:
        return UNKNOWN
    if wind_mph < 25.0:
        return LOW
    if wind_mph < 35.0:
        return MODERATE
    if wind_mph < 45.0:
        return HIGH
    if wind_mph < 55.0:
        return SEVERE
    return NO_TRAVEL

def calculate_rain_risk(rain_in_hr: float | None) -> str:
    """
    Rain thresholds:
    - Below 0.10 in/hr: LOW.
    - 0.10 to below 0.25 in/hr: MODERATE.
    - 0.25 to below 0.50 in/hr: HIGH.
    - 0.50 to 1.00 in/hr: SEVERE. (Exactly 1.00 in/hr belongs to SEVERE)
    - Above 1.00 in/hr: NO_TRAVEL.
    """
    if rain_in_hr is None:
        return UNKNOWN
    if rain_in_hr < 0.10:
        return LOW
    if rain_in_hr < 0.25:
        return MODERATE
    if rain_in_hr < 0.50:
        return HIGH
    if rain_in_hr <= 1.00:
        return SEVERE
    return NO_TRAVEL

def calculate_snow_risk(snow_in_hr: float | None) -> str:
    """
    Snow thresholds:
    - Below 0.5 in/hr: LOW.
    - 0.5 to below 1.0 in/hr: MODERATE.
    - 1.0 to below 2.0 in/hr: HIGH.
    - 2.0 to 3.0 in/hr: SEVERE. (Exactly 3.0 in/hr belongs to SEVERE)
    - Above 3.0 in/hr: NO_TRAVEL.
    """
    if snow_in_hr is None:
        return UNKNOWN
    if snow_in_hr < 0.50:
        return LOW
    if snow_in_hr < 1.00:
        return MODERATE
    if snow_in_hr < 2.00:
        return HIGH
    if snow_in_hr <= 3.00:
        return SEVERE
    return NO_TRAVEL

def apply_load_wind_rule(wind_mph: float | None, load_weight_lbs: float, base_wind_risk: str) -> str:
    """
    Load-based wind rules:
    1. Wind >= 55 mph -> NO_TRAVEL for any load.
    2. Wind 45–54 mph and load > 30,000 lb -> NO_TRAVEL.
    3. Wind 35–44 mph and load > 40,000 lb -> SEVERE.

    Use strict greater-than comparisons for load limits.
    Do not lower the risk level assigned by the weather rules.
    """
    if wind_mph is None or base_wind_risk == UNKNOWN:
        return UNKNOWN

    # Rule 1: Wind >= 55 mph -> NO_TRAVEL for any load
    if wind_mph >= 55.0:
        return NO_TRAVEL

    # Rule 2: Wind 45 to below 55 mph and load > 30,000 lb -> NO_TRAVEL
    if 45.0 <= wind_mph < 55.0 and load_weight_lbs > 30000:
        return NO_TRAVEL

    # Rule 3: Wind 35 to below 45 mph and load > 40,000 lb -> SEVERE
    if 35.0 <= wind_mph < 45.0 and load_weight_lbs > 40000:
        return SEVERE

    return base_wind_risk

def calculate_combined_risk(load_wind_risk: str, rain_risk: str, snow_risk: str) -> str:
    """
    Combines individual hazard risks using the highest applicable risk level.
    If weather data is missing for any hazard:
    - If any known hazard is NO_TRAVEL or SEVERE, returns at least that level.
    - Otherwise, returns UNKNOWN to ensure missing data is never treated as LOW.
    """
    risks = [load_wind_risk, rain_risk, snow_risk]

    # If any hazard is explicitly NO_TRAVEL, the checkpoint cannot be traveled
    if NO_TRAVEL in risks:
        return NO_TRAVEL

    # If any hazard is SEVERE, the checkpoint is at least SEVERE
    if SEVERE in risks:
        return SEVERE

    # If any hazard is UNKNOWN and no severe/no-travel condition exists, return UNKNOWN
    if UNKNOWN in risks:
        return UNKNOWN

    # Otherwise, pick the maximum known risk level
    return max(risks, key=lambda r: SEVERITY_ORDER.get(r, 0))

