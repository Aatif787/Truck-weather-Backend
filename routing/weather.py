import requests
import logging
from datetime import datetime, timezone, timedelta
from .risk_engine import (
    calculate_wind_risk,
    calculate_rain_risk,
    calculate_snow_risk,
    apply_load_wind_rule,
    calculate_combined_risk,
    UNKNOWN
)

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT_SECONDS = 12

def _find_closest_forecast_hour(target_dt: datetime, time_strings: list[str]) -> tuple[int | None, str | None]:
    """
    Finds index of the forecast hour closest to the target datetime.
    Returns (index, timestamp_str) or (None, None) if outside forecast horizon.
    """
    if not time_strings:
        return None, None

    # Parse boundaries
    first_dt = datetime.fromisoformat(time_strings[0]).replace(tzinfo=timezone.utc)
    last_dt = datetime.fromisoformat(time_strings[-1]).replace(tzinfo=timezone.utc)

    # Outside horizon (allowing +/- 60 minutes margin)
    if target_dt < (first_dt - timedelta(minutes=60)) or target_dt > (last_dt + timedelta(minutes=60)):
        return None, None

    best_idx = None
    min_diff = None

    for idx, t_str in enumerate(time_strings):
        t_dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        diff = abs((target_dt - t_dt).total_seconds())
        if min_diff is None or diff < min_diff:
            min_diff = diff
            best_idx = idx

    if best_idx is not None and min_diff is not None and min_diff <= 3600:
        return best_idx, time_strings[best_idx]

    return None, None

def fetch_weather_forecast(lats: list[str], lons: list[str], timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
    """
    Performs the HTTP request to Open-Meteo for batch coordinates.
    Queries wind_speed_10m (mph), rain (inch), precipitation (inch), and snowfall (inch).
    In Open-Meteo:
    - rain / precipitation: accumulation over 1 hour interval in inches, representing in/hr rate.
    - snowfall: depth of new snow accumulated over 1 hour interval in inches, representing in/hr rate.
    Returns list of forecast dicts or None on non-200.
    """
    params = {
        'latitude': ','.join(lats),
        'longitude': ','.join(lons),
        'hourly': ['wind_speed_10m', 'rain', 'precipitation', 'snowfall'],
        'wind_speed_unit': 'mph',
        'precipitation_unit': 'inch',
        'timezone': 'UTC',
        'forecast_days': 7
    }

    resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=timeout_seconds)
    if resp.status_code == 200:
        data = resp.json()
        if not isinstance(data, list):
            return [data]
        return data
    else:
        logger.warning(f"Open-Meteo returned status {resp.status_code}: {resp.text[:200]}")
        return None

def enrich_checkpoints_with_weather(
    checkpoints: list[dict],
    load_weight_lbs: float = 0.0,
    departure_datetime: datetime | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> list[dict]:
    """
    Enriches a list of checkpoint dictionaries with real weather data from Open-Meteo:
    1. Checkpoint ETA weather (used for trip route risk & ranking).
    2. 0-48 Hour timeline (hourly_forecasts) for the interactive forecast time slider.
    """
    if not checkpoints:
        return []

    if departure_datetime is None:
        departure_datetime = datetime.now(timezone.utc)
    elif departure_datetime.tzinfo is None:
        departure_datetime = departure_datetime.replace(tzinfo=timezone.utc)

    # Prepare batch coordinate lists
    lats = [f"{cp['coordinates'][1]:.4f}" for cp in checkpoints]
    lons = [f"{cp['coordinates'][0]:.4f}" for cp in checkpoints]

    try:
        forecast_results = fetch_weather_forecast(lats, lons, timeout_seconds)
    except requests.RequestException as e:
        logger.error(f"Open-Meteo request failed or timed out: {e}")
        forecast_results = None

    enriched_checkpoints = []

    for idx, cp in enumerate(checkpoints):
        eta_str = cp.get("estimated_arrival_time")
        if eta_str:
            eta = datetime.fromisoformat(eta_str).replace(tzinfo=timezone.utc)
        else:
            eta = departure_datetime

        forecast_data = forecast_results[idx] if (forecast_results and idx < len(forecast_results)) else None

        times = []
        if forecast_data and "hourly" in forecast_data:
            times = forecast_data["hourly"].get("time", [])

        # 1. Match Checkpoint ETA Weather
        matched_hour_idx, matched_time_str = _find_closest_forecast_hour(eta, times)

        if matched_hour_idx is not None and forecast_data:
            hourly = forecast_data["hourly"]
            raw_wind = hourly.get("wind_speed_10m", [None])[matched_hour_idx]
            # Use 'rain' (pure rainfall) with fallback to 'precipitation'
            raw_rain = (hourly.get("rain") or hourly.get("precipitation", [None]))[matched_hour_idx]
            raw_snow = hourly.get("snowfall", [None])[matched_hour_idx]

            wind_mph = float(raw_wind) if raw_wind is not None else None
            rain_in_hr = float(raw_rain) if raw_rain is not None else None
            snow_in_hr = float(raw_snow) if raw_snow is not None else None

            wind_risk = calculate_wind_risk(wind_mph)
            rain_risk = calculate_rain_risk(rain_in_hr)
            snow_risk = calculate_snow_risk(snow_in_hr)
            load_wind_risk = apply_load_wind_rule(wind_mph, load_weight_lbs, wind_risk)
            final_risk = calculate_combined_risk(load_wind_risk, rain_risk, snow_risk)

            status_str = "AVAILABLE"
        else:
            wind_mph = None
            rain_in_hr = None
            snow_in_hr = None
            wind_risk = UNKNOWN
            rain_risk = UNKNOWN
            snow_risk = UNKNOWN
            load_wind_risk = UNKNOWN
            final_risk = UNKNOWN
            status_str = "UNKNOWN" if forecast_results is not None else "ERROR"

        # 2. Build 0-48 Hour Forecast Timeline for the Time Slider
        hourly_timeline = []
        for offset_h in range(49):
            target_dt = departure_datetime + timedelta(hours=offset_h)
            h_idx, h_time_str = _find_closest_forecast_hour(target_dt, times)

            if h_idx is not None and forecast_data:
                hourly = forecast_data["hourly"]
                h_raw_wind = hourly.get("wind_speed_10m", [None])[h_idx]
                h_raw_rain = (hourly.get("rain") or hourly.get("precipitation", [None]))[h_idx]
                h_raw_snow = hourly.get("snowfall", [None])[h_idx]

                h_wind = float(h_raw_wind) if h_raw_wind is not None else None
                h_rain = float(h_raw_rain) if h_raw_rain is not None else None
                h_snow = float(h_raw_snow) if h_raw_snow is not None else None

                h_wind_risk = calculate_wind_risk(h_wind)
                h_rain_risk = calculate_rain_risk(h_rain)
                h_snow_risk = calculate_snow_risk(h_snow)
                h_load_wind_risk = apply_load_wind_rule(h_wind, load_weight_lbs, h_wind_risk)
                h_final_risk = calculate_combined_risk(h_load_wind_risk, h_rain_risk, h_snow_risk)

                hourly_timeline.append({
                    "offset_hours": offset_h,
                    "forecast_timestamp": h_time_str,
                    "wind_speed_mph": h_wind,
                    "rain_intensity_in_hr": h_rain,
                    "snow_intensity_in_hr": h_snow,
                    "wind_risk": h_wind_risk,
                    "rain_risk": h_rain_risk,
                    "snow_risk": h_snow_risk,
                    "load_adjusted_wind_risk": h_load_wind_risk,
                    "final_risk": h_final_risk,
                    "weather_status": "AVAILABLE"
                })
            else:
                hourly_timeline.append({
                    "offset_hours": offset_h,
                    "forecast_timestamp": None,
                    "wind_speed_mph": None,
                    "rain_intensity_in_hr": None,
                    "snow_intensity_in_hr": None,
                    "wind_risk": UNKNOWN,
                    "rain_risk": UNKNOWN,
                    "snow_risk": UNKNOWN,
                    "load_adjusted_wind_risk": UNKNOWN,
                    "final_risk": UNKNOWN,
                    "weather_status": "UNAVAILABLE"
                })

        enriched_checkpoints.append({
            "checkpoint_index": cp.get("checkpoint_index", idx),
            "coordinates": cp["coordinates"],
            "distance_from_origin_miles": cp.get("distance_from_origin_miles", 0.0),
            "estimated_arrival_time": eta_str,
            "forecast_timestamp": matched_time_str,
            "data_source": "Open-Meteo",
            "weather_status": status_str,
            "wind_speed_mph": wind_mph,
            "rain_intensity_in_hr": rain_in_hr,
            "snow_intensity_in_hr": snow_in_hr,
            "wind_risk": wind_risk,
            "rain_risk": rain_risk,
            "snow_risk": snow_risk,
            "load_adjusted_wind_risk": load_wind_risk,
            "final_risk": final_risk,
            "hourly_forecasts": hourly_timeline
        })

    return enriched_checkpoints
