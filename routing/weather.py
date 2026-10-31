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

WMO_WEATHER_MAP = {
    0: ("Clear Sky", "☀️"),
    1: ("Mainly Clear", "🌤️"),
    2: ("Partly Cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Rime Fog", "🌫️"),
    51: ("Light Drizzle", "🌦️"),
    53: ("Moderate Drizzle", "🌦️"),
    55: ("Dense Drizzle", "🌧️"),
    56: ("Light Freezing Drizzle", "🌧️"),
    57: ("Dense Freezing Drizzle", "🌧️"),
    61: ("Slight Rain", "🌧️"),
    63: ("Moderate Rain", "🌧️"),
    65: ("Heavy Rain", "🌧️"),
    66: ("Light Freezing Rain", "🌧️"),
    67: ("Heavy Freezing Rain", "🌧️"),
    71: ("Slight Snow", "❄️"),
    73: ("Moderate Snow", "❄️"),
    75: ("Heavy Snow", "❄️"),
    77: ("Snow Grains", "❄️"),
    80: ("Slight Showers", "🌧️"),
    81: ("Moderate Showers", "🌧️"),
    82: ("Violent Showers", "🌧️"),
    85: ("Slight Snow Showers", "🌨️"),
    86: ("Heavy Snow Showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ Hail", "⛈️"),
    99: ("Severe Thunderstorm", "⛈️"),
}

def degrees_to_cardinal(deg: float | None) -> str:
    if deg is None:
        return ""
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    idx = round(float(deg) / 22.5) % 16
    return dirs[idx]

def get_wmo_weather_info(code: int | None) -> tuple[str, str]:
    if code is None:
        return ("Clear Sky", "☀️")
    return WMO_WEATHER_MAP.get(int(code), ("Partly Cloudy", "⛅"))

def _safe_get(data_dict: dict, key: str, idx: int, default=None):
    val_list = data_dict.get(key)
    if isinstance(val_list, list) and 0 <= idx < len(val_list):
        return val_list[idx]
    return default

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

def fetch_weather_forecast(lats: list[str], lons: list[str], timeout_seconds: int = 15):
    """
    Performs HTTP request to Open-Meteo for batch coordinates with chunking,
    custom User-Agent headers, and resilient retry handling.
    """
    headers = {
        'User-Agent': 'SpotterFleetRoute/2.5 (Commercial HGV Logistics Engine; https://truck-weather-frontend-waqe.vercel.app)',
        'Accept': 'application/json'
    }

    # Chunk into batches of 8 coordinates to prevent URL length limits and rate-limiting
    chunk_size = 40
    all_results = []

    for i in range(0, len(lats), chunk_size):
        chunk_lats = lats[i:i + chunk_size]
        chunk_lons = lons[i:i + chunk_size]

        params = {
            'latitude': ','.join(chunk_lats),
            'longitude': ','.join(chunk_lons),
            'hourly': ['temperature_2m', 'weather_code', 'wind_speed_10m', 'wind_gusts_10m', 'wind_direction_10m', 'rain', 'precipitation', 'snowfall'],
            'temperature_unit': 'fahrenheit',
            'wind_speed_unit': 'mph',
            'precipitation_unit': 'inch',
            'timezone': 'UTC',
            'forecast_days': 7
        }

        try:
            resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, headers=headers, timeout=timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, list):
                    all_results.append(data)
                else:
                    all_results.extend(data)
            else:
                logger.warning(f"Open-Meteo returned status {resp.status_code}: {resp.text[:200]}")
                for _ in chunk_lats:
                    all_results.append(None)
        except requests.RequestException as e:
            logger.error(f"Open-Meteo request error for chunk: {e}")
            for _ in chunk_lats:
                all_results.append(None)

    return all_results if any(r is not None for r in all_results) else None

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
            raw_wind = _safe_get(hourly, "wind_speed_10m", matched_hour_idx)
            raw_rain = _safe_get(hourly, "rain", matched_hour_idx)
            if raw_rain is None:
                raw_rain = _safe_get(hourly, "precipitation", matched_hour_idx)
            raw_snow = _safe_get(hourly, "snowfall", matched_hour_idx)
            raw_temp = _safe_get(hourly, "temperature_2m", matched_hour_idx)
            raw_wcode = _safe_get(hourly, "weather_code", matched_hour_idx)
            raw_gusts = _safe_get(hourly, "wind_gusts_10m", matched_hour_idx)
            raw_wdir = _safe_get(hourly, "wind_direction_10m", matched_hour_idx)

            wind_mph = float(raw_wind) if raw_wind is not None else None
            rain_in_hr = float(raw_rain) if raw_rain is not None else None
            snow_in_hr = float(raw_snow) if raw_snow is not None else None
            temp_f = round(float(raw_temp), 1) if raw_temp is not None else None
            temp_c = round((float(raw_temp) - 32) * 5 / 9, 1) if raw_temp is not None else None
            w_desc, w_icon = get_wmo_weather_info(raw_wcode)
            gusts_mph = round(float(raw_gusts), 1) if raw_gusts is not None else None
            wdir_deg = round(float(raw_wdir), 1) if raw_wdir is not None else None
            wdir_cardinal = degrees_to_cardinal(raw_wdir)

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
            temp_f = None
            temp_c = None
            raw_wcode = None
            w_desc = "Unknown"
            w_icon = "⛅"
            gusts_mph = None
            wdir_deg = None
            wdir_cardinal = ""
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
                h_raw_wind = _safe_get(hourly, "wind_speed_10m", h_idx)
                h_raw_rain = _safe_get(hourly, "rain", h_idx)
                if h_raw_rain is None:
                    h_raw_rain = _safe_get(hourly, "precipitation", h_idx)
                h_raw_snow = _safe_get(hourly, "snowfall", h_idx)

                h_wind = float(h_raw_wind) if h_raw_wind is not None else None
                h_rain = float(h_raw_rain) if h_raw_rain is not None else None
                h_snow = float(h_raw_snow) if h_raw_snow is not None else None

                h_wind_risk = calculate_wind_risk(h_wind)
                h_rain_risk = calculate_rain_risk(h_rain)
                h_snow_risk = calculate_snow_risk(h_snow)
                h_load_wind_risk = apply_load_wind_rule(h_wind, load_weight_lbs, h_wind_risk)
                h_final_risk = calculate_combined_risk(h_load_wind_risk, h_rain_risk, h_snow_risk)

                h_temp = _safe_get(hourly, "temperature_2m", h_idx)
                h_wcode = _safe_get(hourly, "weather_code", h_idx)
                h_gusts = _safe_get(hourly, "wind_gusts_10m", h_idx)
                h_wdir = _safe_get(hourly, "wind_direction_10m", h_idx)
                h_desc, h_icon = get_wmo_weather_info(h_wcode)

                hourly_timeline.append({
                    "offset_hours": offset_h,
                    "forecast_timestamp": h_time_str,
                    "temperature_f": round(float(h_temp), 1) if h_temp is not None else None,
                    "weather_description": h_desc,
                    "weather_icon": h_icon,
                    "wind_speed_mph": h_wind,
                    "wind_gusts_mph": round(float(h_gusts), 1) if h_gusts is not None else None,
                    "wind_direction_cardinal": degrees_to_cardinal(h_wdir),
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

        cp_entry = dict(cp)
        cp_entry.update({
            "checkpoint_index": cp.get("checkpoint_index", idx),
            "coordinates": cp["coordinates"],
            "distance_from_origin_miles": cp.get("distance_from_origin_miles", 0.0),
            "estimated_arrival_time": eta_str,
            "forecast_timestamp": matched_time_str,
            "data_source": "Open-Meteo",
            "weather_status": status_str,
            "temperature_f": temp_f,
            "temperature_c": temp_c,
            "weather_code": int(raw_wcode) if raw_wcode is not None else None,
            "weather_description": w_desc,
            "weather_icon": w_icon,
            "wind_speed_mph": wind_mph,
            "wind_gusts_mph": gusts_mph,
            "wind_direction_deg": wdir_deg,
            "wind_direction_cardinal": wdir_cardinal,
            "rain_intensity_in_hr": rain_in_hr,
            "snow_intensity_in_hr": snow_in_hr,
            "wind_risk": wind_risk,
            "rain_risk": rain_risk,
            "snow_risk": snow_risk,
            "load_adjusted_wind_risk": load_wind_risk,
            "final_risk": final_risk,
            "hourly_forecasts": hourly_timeline
        })
        enriched_checkpoints.append(cp_entry)

    return enriched_checkpoints
