from django.test import TestCase
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timezone, timedelta
import requests

from .risk_engine import (
    calculate_wind_risk,
    calculate_rain_risk,
    calculate_snow_risk,
    apply_load_wind_rule,
    calculate_combined_risk,
    LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL, UNKNOWN
)
from .checkpoints import generate_checkpoints, haversine_distance
from .weather import _find_closest_forecast_hour, enrich_checkpoints_with_weather
from .ranking import rank_and_recommend_routes, calculate_represented_distances, compute_route_weather_metrics


class RiskEngineTests(TestCase):
    def test_wind_thresholds_and_boundaries(self):
        # Boundary: Below 25 mph: LOW
        self.assertEqual(calculate_wind_risk(None), UNKNOWN)
        self.assertEqual(calculate_wind_risk(0.0), LOW)
        self.assertEqual(calculate_wind_risk(24.9), LOW)

        # Boundary: 25 to below 35 mph: MODERATE
        self.assertEqual(calculate_wind_risk(25.0), MODERATE)
        self.assertEqual(calculate_wind_risk(34.99), MODERATE)

        # Boundary: 35 to below 45 mph: HIGH
        self.assertEqual(calculate_wind_risk(35.0), HIGH)
        self.assertEqual(calculate_wind_risk(44.99), HIGH)

        # Boundary: 45 to below 55 mph: SEVERE
        self.assertEqual(calculate_wind_risk(45.0), SEVERE)
        self.assertEqual(calculate_wind_risk(54.99), SEVERE)

        # Boundary: 55 mph or above: NO_TRAVEL
        self.assertEqual(calculate_wind_risk(55.0), NO_TRAVEL)
        self.assertEqual(calculate_wind_risk(75.0), NO_TRAVEL)

    def test_rain_thresholds_and_boundaries(self):
        # Boundary: Below 0.10 in/hr: LOW
        self.assertEqual(calculate_rain_risk(None), UNKNOWN)
        self.assertEqual(calculate_rain_risk(0.0), LOW)
        self.assertEqual(calculate_rain_risk(0.099), LOW)

        # Boundary: 0.10 to below 0.25 in/hr: MODERATE
        self.assertEqual(calculate_rain_risk(0.10), MODERATE)
        self.assertEqual(calculate_rain_risk(0.249), MODERATE)

        # Boundary: 0.25 to below 0.50 in/hr: HIGH
        self.assertEqual(calculate_rain_risk(0.25), HIGH)
        self.assertEqual(calculate_rain_risk(0.499), HIGH)

        # Boundary: 0.50 to 1.00 in/hr: SEVERE (1.00 exactly is SEVERE)
        self.assertEqual(calculate_rain_risk(0.50), SEVERE)
        self.assertEqual(calculate_rain_risk(0.999), SEVERE)
        self.assertEqual(calculate_rain_risk(1.00), SEVERE)

        # Boundary: Above 1.00 in/hr: NO_TRAVEL
        self.assertEqual(calculate_rain_risk(1.001), NO_TRAVEL)
        self.assertEqual(calculate_rain_risk(2.50), NO_TRAVEL)

    def test_snow_thresholds_and_boundaries(self):
        # Boundary: Below 0.5 in/hr: LOW
        self.assertEqual(calculate_snow_risk(None), UNKNOWN)
        self.assertEqual(calculate_snow_risk(0.0), LOW)
        self.assertEqual(calculate_snow_risk(0.499), LOW)

        # Boundary: 0.5 to below 1.0 in/hr: MODERATE
        self.assertEqual(calculate_snow_risk(0.50), MODERATE)
        self.assertEqual(calculate_snow_risk(0.999), MODERATE)

        # Boundary: 1.0 to below 2.0 in/hr: HIGH
        self.assertEqual(calculate_snow_risk(1.00), HIGH)
        self.assertEqual(calculate_snow_risk(1.999), HIGH)

        # Boundary: 2.0 to 3.0 in/hr: SEVERE (3.0 exactly is SEVERE)
        self.assertEqual(calculate_snow_risk(2.00), SEVERE)
        self.assertEqual(calculate_snow_risk(2.999), SEVERE)
        self.assertEqual(calculate_snow_risk(3.00), SEVERE)

        # Boundary: Above 3.0 in/hr: NO_TRAVEL
        self.assertEqual(calculate_snow_risk(3.001), NO_TRAVEL)
        self.assertEqual(calculate_snow_risk(4.50), NO_TRAVEL)

    def test_load_based_wind_rules(self):
        # Rule 1: Wind >= 55 mph -> NO_TRAVEL for any load
        self.assertEqual(apply_load_wind_rule(55.0, 10000, NO_TRAVEL), NO_TRAVEL)
        self.assertEqual(apply_load_wind_rule(60.0, 30000, NO_TRAVEL), NO_TRAVEL)
        self.assertEqual(apply_load_wind_rule(55.0, 45000, NO_TRAVEL), NO_TRAVEL)

        # Rule 2: Wind 45–54 mph and load > 30,000 lb -> NO_TRAVEL
        # Exactly 30,000 lb (not strictly greater than) -> remains SEVERE
        self.assertEqual(apply_load_wind_rule(50.0, 30000, SEVERE), SEVERE)
        # Just above 30,000 lb -> NO_TRAVEL
        self.assertEqual(apply_load_wind_rule(50.0, 30001, SEVERE), NO_TRAVEL)
        # Low load -> remains SEVERE
        self.assertEqual(apply_load_wind_rule(48.0, 25000, SEVERE), SEVERE)

        # Rule 3: Wind 35–44 mph and load > 40,000 lb -> SEVERE
        # Exactly 40,000 lb (not strictly greater than) -> remains HIGH
        self.assertEqual(apply_load_wind_rule(40.0, 40000, HIGH), HIGH)
        # Just above 40,000 lb -> SEVERE
        self.assertEqual(apply_load_wind_rule(40.0, 40001, HIGH), SEVERE)
        # Lower load -> remains HIGH
        self.assertEqual(apply_load_wind_rule(38.0, 35000, HIGH), HIGH)

        # Lower wind: load should not elevate below threshold
        self.assertEqual(apply_load_wind_rule(30.0, 45000, MODERATE), MODERATE)

        # Unknown wind stays UNKNOWN
        self.assertEqual(apply_load_wind_rule(None, 45000, UNKNOWN), UNKNOWN)

    def test_combined_risk_logic(self):
        # All LOW -> LOW
        self.assertEqual(calculate_combined_risk(LOW, LOW, LOW), LOW)
        # One MODERATE -> MODERATE
        self.assertEqual(calculate_combined_risk(LOW, MODERATE, LOW), MODERATE)
        # One HIGH -> HIGH
        self.assertEqual(calculate_combined_risk(LOW, HIGH, MODERATE), HIGH)
        # One SEVERE -> SEVERE
        self.assertEqual(calculate_combined_risk(LOW, SEVERE, MODERATE), SEVERE)
        # One NO_TRAVEL -> NO_TRAVEL
        self.assertEqual(calculate_combined_risk(LOW, NO_TRAVEL, HIGH), NO_TRAVEL)

        # Missing data handling: never treat missing as LOW
        self.assertEqual(calculate_combined_risk(UNKNOWN, LOW, LOW), UNKNOWN)
        self.assertEqual(calculate_combined_risk(LOW, UNKNOWN, MODERATE), UNKNOWN)

        # Known SEVERE or NO_TRAVEL persists even if another hazard is UNKNOWN
        self.assertEqual(calculate_combined_risk(UNKNOWN, SEVERE, LOW), SEVERE)
        self.assertEqual(calculate_combined_risk(UNKNOWN, NO_TRAVEL, LOW), NO_TRAVEL)


class CheckpointGenerationTests(TestCase):
    def test_haversine_distance(self):
        # Known coords: NYC to Philadelphia is ~80.5 miles
        nyc = [-74.006, 40.7128]
        philly = [-75.1652, 39.9526]
        d = haversine_distance(nyc, philly)
        self.assertAlmostEqual(d, 80.5, delta=1.5)

    def test_checkpoint_generation_and_etas(self):
        # 3 points along a line of 60 miles, duration 3600 seconds (1 hour)
        coords = [[0.0, 0.0], [0.0, 0.435], [0.0, 0.87]]
        total_dist = 60.0
        total_dur = 3600.0
        departure = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Interval: 25 miles
        cps = generate_checkpoints(coords, total_dist, total_dur, departure, sampling_interval_miles=25.0)

        # Expected checkpoints: 0.0 mi, 25.0 mi, 50.0 mi, 60.0 mi (destination)
        self.assertEqual(len(cps), 4)
        self.assertEqual(cps[0]['distance_from_origin_miles'], 0.0)
        self.assertEqual(cps[0]['estimated_arrival_time'], "2026-10-30T12:00:00+00:00")

        self.assertEqual(cps[1]['distance_from_origin_miles'], 25.0)
        # ETA at 25 miles = 25/60 * 3600 = 1500s = 25 mins -> 12:25:00
        self.assertEqual(cps[1]['estimated_arrival_time'], "2026-10-30T12:25:00+00:00")

        self.assertEqual(cps[2]['distance_from_origin_miles'], 50.0)
        # ETA at 50 miles = 50/60 * 3600 = 3000s = 50 mins -> 12:50:00
        self.assertEqual(cps[2]['estimated_arrival_time'], "2026-10-30T12:50:00+00:00")

        self.assertEqual(cps[3]['distance_from_origin_miles'], 60.0)
        self.assertEqual(cps[3]['estimated_arrival_time'], "2026-10-30T13:00:00+00:00")

    def test_avoids_duplicate_near_destination(self):
        # 50.4 miles with 25 mile interval: 0, 25, 50 -> 50.4 is within 1 mile of 50.0
        coords = [[0.0, 0.0], [0.0, 0.72]]
        total_dist = 50.4
        total_dur = 3600.0
        departure = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        cps = generate_checkpoints(coords, total_dist, total_dur, departure, sampling_interval_miles=25.0)
        # Should merge the last checkpoint into destination (50.4) instead of having 50.0 and 50.4
        self.assertEqual(len(cps), 3)
        self.assertEqual(cps[0]['distance_from_origin_miles'], 0.0)
        self.assertEqual(cps[1]['distance_from_origin_miles'], 25.0)
        self.assertEqual(cps[2]['distance_from_origin_miles'], 50.4)


class WeatherMatchingTests(TestCase):
    def test_closest_forecast_hour_matching(self):
        times = ["2026-10-30T12:00", "2026-10-30T13:00", "2026-10-30T14:00"]

        # ETA at 12:20 -> closest is 12:00
        eta1 = datetime(2026, 10, 30, 12, 20, tzinfo=timezone.utc)
        idx, t_str = _find_closest_forecast_hour(eta1, times)
        self.assertEqual(idx, 0)
        self.assertEqual(t_str, "2026-10-30T12:00")

        # ETA at 12:45 -> closest is 13:00
        eta2 = datetime(2026, 10, 30, 12, 45, tzinfo=timezone.utc)
        idx, t_str = _find_closest_forecast_hour(eta2, times)
        self.assertEqual(idx, 1)
        self.assertEqual(t_str, "2026-10-30T13:00")

    def test_eta_outside_forecast_horizon(self):
        times = ["2026-10-30T12:00", "2026-10-30T13:00"]
        # Far future (10 days later)
        eta_future = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        idx, t_str = _find_closest_forecast_hour(eta_future, times)
        self.assertIsNone(idx)
        self.assertIsNone(t_str)

        # Past (1 year before)
        eta_past = datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc)
        idx, t_str = _find_closest_forecast_hour(eta_past, times)
        self.assertIsNone(idx)


class RouteCalculationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_origin_or_destination(self):
        resp = self.client.post('/api/routes/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", resp.data)

        resp = self.client.post('/api/routes/', {'origin': '   ', 'destination': 'Boston'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_input_validations(self):
        # Invalid departure_datetime
        resp = self.client.post('/api/routes/', {
            'origin': 'New York',
            'destination': 'Boston',
            'departure_datetime': 'invalid-date'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("departure_datetime", resp.data['error'])

        # Negative load weight
        resp = self.client.post('/api/routes/', {
            'origin': 'New York',
            'destination': 'Boston',
            'load_weight_lbs': -500
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("negative", resp.data['error'])

        # Invalid sampling interval (not 10, 25, or 50)
        resp = self.client.post('/api/routes/', {
            'origin': 'New York',
            'destination': 'Boston',
            'sampling_interval_miles': 15
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sampling_interval_miles", resp.data['error'])

    @patch('routing.services.requests.get')
    def test_geocoding_failure_handles_gracefully(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"features": []}
        mock_get.return_value = mock_resp

        resp = self.client.post('/api/routes/', {'origin': 'NonexistentPlaceXYZ123', 'destination': 'Boston'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Location not found", resp.data['error'])

    @patch('routing.weather.fetch_weather_forecast')
    @patch('routing.services.requests.post')
    @patch('routing.services.requests.get')
    def test_full_analysis_with_weather_mocked(self, mock_geo_get, mock_dirs_post, mock_weather_fetch):
        # 1. Geocode response
        mock_geo = MagicMock()
        mock_geo.status_code = 200
        mock_geo.json.side_effect = [
            {"features": [{"geometry": {"coordinates": [8.68, 49.41]}, "properties": {"label": "Heidelberg"}}]},
            {"features": [{"geometry": {"coordinates": [8.46, 49.48]}, "properties": {"label": "Mannheim"}}]}
        ]
        mock_geo_get.return_value = mock_geo

        # 2. Directions response (20 miles, 1800 seconds)
        mock_dirs = MagicMock()
        mock_dirs.status_code = 200
        mock_dirs.json.return_value = {
            "features": [{
                "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.57, 49.45], [8.46, 49.48]]},
                "properties": {"summary": {"distance": 32186.8, "duration": 1800.0}} # 20.0 miles
            }]
        }
        mock_dirs_post.return_value = mock_dirs

        # 3. Weather response (2 checkpoints: start & end with 25 mile interval)
        mock_weather_fetch.return_value = [
            {
                "hourly": {
                    "time": ["2026-10-30T12:00", "2026-10-30T13:00"],
                    "wind_speed_10m": [28.0, 30.0],  # MODERATE wind
                    "precipitation": [0.05, 0.05],    # LOW rain
                    "snowfall": [0.0, 0.0]            # LOW snow
                }
            },
            {
                "hourly": {
                    "time": ["2026-10-30T12:00", "2026-10-30T13:00"],
                    "wind_speed_10m": [40.0, 42.0],  # HIGH wind (if load > 40k -> SEVERE)
                    "precipitation": [0.60, 0.60],    # SEVERE rain (0.50 - 1.00)
                    "snowfall": [0.0, 0.0]
                }
            }
        ]

        payload = {
            "origin": "Heidelberg",
            "destination": "Mannheim",
            "departure_datetime": "2026-10-30T12:00:00Z",
            "load_weight_lbs": 42000,  # > 40,000 lbs triggers load rule on 35-44 mph wind
            "sampling_interval_miles": 25
        }

        resp = self.client.post('/api/routes/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['routes_count'], 1)

        route = resp.data['routes'][0]
        self.assertIn("checkpoints", route)
        cps = route['checkpoints']
        self.assertEqual(len(cps), 2)

        # Checkpoint 0: Origin
        cp0 = cps[0]
        self.assertEqual(cp0['distance_from_origin_miles'], 0.0)
        self.assertEqual(cp0['wind_speed_mph'], 28.0)
        self.assertEqual(cp0['wind_risk'], MODERATE)
        self.assertEqual(cp0['load_adjusted_wind_risk'], MODERATE)
        self.assertEqual(cp0['rain_risk'], LOW)
        self.assertEqual(cp0['final_risk'], MODERATE)

        # Checkpoint 1: Destination
        cp1 = cps[1]
        self.assertEqual(cp1['distance_from_origin_miles'], 20.0)
        self.assertEqual(cp1['wind_speed_mph'], 40.0)
        self.assertEqual(cp1['wind_risk'], HIGH)
        # Load rule: wind 35-44 mph + load 42,000 lb (>40,000) -> SEVERE
        self.assertEqual(cp1['load_adjusted_wind_risk'], SEVERE)
        self.assertEqual(cp1['rain_risk'], SEVERE)  # 0.60 in/hr
        self.assertEqual(cp1['final_risk'], SEVERE)

    @patch('routing.weather.fetch_weather_forecast')
    @patch('routing.services.requests.post')
    @patch('routing.services.requests.get')
    def test_weather_provider_timeout_handles_gracefully(self, mock_geo_get, mock_dirs_post, mock_weather_fetch):
        # Mock geocode & dirs success
        mock_geo = MagicMock()
        mock_geo.status_code = 200
        mock_geo.json.side_effect = [
            {"features": [{"geometry": {"coordinates": [8.68, 49.41]}, "properties": {"label": "Heidelberg"}}]},
            {"features": [{"geometry": {"coordinates": [8.46, 49.48]}, "properties": {"label": "Mannheim"}}]}
        ]
        mock_geo_get.return_value = mock_geo

        mock_dirs = MagicMock()
        mock_dirs.status_code = 200
        mock_dirs.json.return_value = {
            "features": [{
                "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.46, 49.48]]},
                "properties": {"summary": {"distance": 20000.0, "duration": 1800.0}}
            }]
        }
        mock_dirs_post.return_value = mock_dirs

        # Weather timeout
        mock_weather_fetch.side_effect = requests.Timeout("Open-Meteo connection timed out")

        payload = {"origin": "Heidelberg", "destination": "Mannheim"}
        resp = self.client.post('/api/routes/', payload, format='json')

        # Request succeeds with route data, checkpoints marked with UNKNOWN risk
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        route = resp.data['routes'][0]
        for cp in route['checkpoints']:
            self.assertEqual(cp['weather_status'], "ERROR")
            self.assertEqual(cp['final_risk'], UNKNOWN)
            self.assertIsNone(cp['wind_speed_mph'])


class RouteRankingTests(TestCase):
    def test_ranking_by_severe_risk_miles(self):
        # Route 1 has 15 severe miles, Route 2 has 0 severe miles
        r1 = {
            "id": "route-1",
            "distance_miles": 50.0,
            "duration_seconds": 3600.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 25.0, "final_risk": "SEVERE"},
                {"distance_from_origin_miles": 50.0, "final_risk": "LOW"},
            ]
        }
        r2 = {
            "id": "route-2",
            "distance_miles": 50.0,
            "duration_seconds": 3600.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 25.0, "final_risk": "HIGH"},
                {"distance_from_origin_miles": 50.0, "final_risk": "LOW"},
            ]
        }

        result = rank_and_recommend_routes([r1, r2])
        # Route 2 has 0 severe miles, so it must rank 1st over Route 1 (which has severe miles)
        self.assertEqual(result["routes"][0]["id"], "route-2")
        self.assertEqual(result["routes"][0]["rank"], 1)
        self.assertEqual(result["routes"][1]["id"], "route-1")
        self.assertEqual(result["routes"][1]["rank"], 2)
        self.assertEqual(result["recommended_route_id"], "route-2")

    def test_ranking_by_high_risk_miles_when_severe_tied(self):
        # Both routes have 0 severe miles, but Route 1 has more high miles than Route 2
        r1 = {
            "id": "route-1",
            "distance_miles": 60.0,
            "duration_seconds": 3600.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "HIGH"},
                {"distance_from_origin_miles": 30.0, "final_risk": "HIGH"},
                {"distance_from_origin_miles": 60.0, "final_risk": "LOW"},
            ]
        }
        r2 = {
            "id": "route-2",
            "distance_miles": 60.0,
            "duration_seconds": 3600.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 30.0, "final_risk": "HIGH"},
                {"distance_from_origin_miles": 60.0, "final_risk": "LOW"},
            ]
        }

        result = rank_and_recommend_routes([r1, r2])
        self.assertEqual(result["routes"][0]["id"], "route-2")
        self.assertEqual(result["recommended_route_id"], "route-2")
        self.assertLess(result["routes"][0]["high_miles"], result["routes"][1]["high_miles"])

    def test_ranking_by_average_risk_when_severe_and_high_tied(self):
        # Both routes have 0 severe and 0 high miles, but Route 2 has lower average risk
        r1 = {
            "id": "route-1",
            "distance_miles": 40.0,
            "duration_seconds": 3000.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "MODERATE"},
                {"distance_from_origin_miles": 40.0, "final_risk": "MODERATE"},
            ]
        }
        r2 = {
            "id": "route-2",
            "distance_miles": 40.0,
            "duration_seconds": 3000.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 40.0, "final_risk": "LOW"},
            ]
        }

        result = rank_and_recommend_routes([r1, r2])
        self.assertEqual(result["routes"][0]["id"], "route-2")
        self.assertEqual(result["routes"][0]["average_risk_score"], 0.0)
        self.assertEqual(result["routes"][1]["average_risk_score"], 1.0)

    def test_ranking_by_duration_when_all_earlier_tied(self):
        # Both routes have identical severe, high, and avg risk, but Route 2 has shorter duration
        r1 = {
            "id": "route-1",
            "distance_miles": 40.0,
            "duration_seconds": 3600.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 40.0, "final_risk": "LOW"},
            ]
        }
        r2 = {
            "id": "route-2",
            "distance_miles": 38.0,
            "duration_seconds": 2900.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 38.0, "final_risk": "LOW"},
            ]
        }

        result = rank_and_recommend_routes([r1, r2])
        self.assertEqual(result["routes"][0]["id"], "route-2")
        self.assertEqual(result["recommended_route_id"], "route-2")

    def test_no_travel_route_never_recommended(self):
        # Route 1 is fast (1000s) but has NO_TRAVEL. Route 2 is slow (5000s) with LOW risk.
        r1 = {
            "id": "route-1",
            "distance_miles": 20.0,
            "duration_seconds": 1000.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 20.0, "final_risk": "NO_TRAVEL"},
            ]
        }
        r2 = {
            "id": "route-2",
            "distance_miles": 50.0,
            "duration_seconds": 5000.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 50.0, "final_risk": "LOW"},
            ]
        }

        result = rank_and_recommend_routes([r1, r2])
        self.assertEqual(result["recommended_route_id"], "route-2")

        # Verify Route 1 is marked unsafe
        r1_res = next(r for r in result["routes"] if r["id"] == "route-1")
        self.assertFalse(r1_res["is_recommended"])
        self.assertEqual(r1_res["recommendation_status"], "NO_TRAVEL_WARNING")
        self.assertIn("Unsafe", r1_res["recommendation_label"])

    def test_all_routes_no_travel_emits_warning(self):
        r1 = {
            "id": "route-1",
            "distance_miles": 30.0,
            "duration_seconds": 1800.0,
            "checkpoints": [{"distance_from_origin_miles": 0.0, "final_risk": "NO_TRAVEL"}]
        }
        r2 = {
            "id": "route-2",
            "distance_miles": 35.0,
            "duration_seconds": 2100.0,
            "checkpoints": [{"distance_from_origin_miles": 0.0, "final_risk": "NO_TRAVEL"}]
        }

        result = rank_and_recommend_routes([r1, r2])
        self.assertFalse(result["has_recommended_route"])
        self.assertIsNone(result["recommended_route_id"])
        self.assertIsNotNone(result["warning"])
        self.assertIn("NO_TRAVEL", result["warning"])

    def test_unknown_weather_not_treated_as_low(self):
        r_unknown = {
            "id": "route-unknown",
            "distance_miles": 30.0,
            "duration_seconds": 1800.0,
            "checkpoints": [{"distance_from_origin_miles": 0.0, "final_risk": "UNKNOWN"}]
        }
        r_low = {
            "id": "route-low",
            "distance_miles": 30.0,
            "duration_seconds": 1800.0,
            "checkpoints": [{"distance_from_origin_miles": 0.0, "final_risk": "LOW"}]
        }

        result = rank_and_recommend_routes([r_unknown, r_low])
        # route-low must rank 1st because route-unknown is penalized with score 3.0
        self.assertEqual(result["routes"][0]["id"], "route-low")
        self.assertEqual(result["routes"][0]["average_risk_score"], 0.0)

        r_u_res = next(r for r in result["routes"] if r["id"] == "route-unknown")
        self.assertEqual(r_u_res["average_risk_score"], 3.0)
        self.assertTrue(r_u_res["has_unknown_weather"])
        self.assertFalse(r_u_res["is_complete_analysis"])

    def test_checkpoint_distance_weighting(self):
        # 4 checkpoints at 0, 20, 40, 60 miles along 60 mile route
        cps = [
            {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
            {"distance_from_origin_miles": 20.0, "final_risk": "SEVERE"},
            {"distance_from_origin_miles": 40.0, "final_risk": "HIGH"},
            {"distance_from_origin_miles": 60.0, "final_risk": "LOW"},
        ]
        rep_dists = calculate_represented_distances(cps, 60.0)
        # Expected:
        # cp 0: (20 - 0)/2 = 10.0 mi
        # cp 1: (40 - 0)/2 = 20.0 mi
        # cp 2: (60 - 20)/2 = 20.0 mi
        # cp 3: (60 - 40)/2 = 10.0 mi
        self.assertEqual(rep_dists, [10.0, 20.0, 20.0, 10.0])
        self.assertEqual(sum(rep_dists), 60.0)

        route = compute_route_weather_metrics({"distance_miles": 60.0, "checkpoints": cps})
        self.assertEqual(route["severe_miles"], 20.0)
        self.assertEqual(route["high_miles"], 20.0)

    def test_route_with_no_checkpoints_or_missing_fields(self):
        r_empty = {
            "id": "route-empty",
            "distance_miles": 50.0,
            "duration_seconds": 3600.0,
            "checkpoints": []
        }
        res = compute_route_weather_metrics(r_empty)
        self.assertEqual(res["severe_miles"], 0.0)
        self.assertEqual(res["average_risk_score"], 3.0)  # Conservative UNKNOWN penalty
        self.assertTrue(res["has_unknown_weather"])
        self.assertFalse(res["is_complete_analysis"])

    def test_safety_score_and_fuel_metrics(self):
        # Clean route (100 miles, all LOW risk)
        cps_clean = [
            {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
            {"distance_from_origin_miles": 50.0, "final_risk": "LOW"},
            {"distance_from_origin_miles": 100.0, "final_risk": "LOW"},
        ]
        clean_route = compute_route_weather_metrics({"distance_miles": 100.0, "checkpoints": cps_clean})
        self.assertGreaterEqual(clean_route["safety_score"], 90.0)
        expected_gallons = round(100.0 / 6.5, 1)
        expected_cost = round(expected_gallons * 3.85, 2)
        self.assertEqual(clean_route["estimated_fuel_gallons"], expected_gallons)
        self.assertEqual(clean_route["estimated_fuel_cost"], expected_cost)

        # Risky route with severe miles
        cps_risky = [
            {"distance_from_origin_miles": 0.0, "final_risk": "SEVERE"},
            {"distance_from_origin_miles": 50.0, "final_risk": "SEVERE"},
            {"distance_from_origin_miles": 100.0, "final_risk": "SEVERE"},
        ]
        risky_route = compute_route_weather_metrics({"distance_miles": 100.0, "checkpoints": cps_risky})
        self.assertLess(risky_route["safety_score"], clean_route["safety_score"])

        # NO_TRAVEL route
        cps_no_travel = [
            {"distance_from_origin_miles": 0.0, "final_risk": "NO_TRAVEL"},
            {"distance_from_origin_miles": 100.0, "final_risk": "LOW"},
        ]
        no_travel_route = compute_route_weather_metrics({"distance_miles": 100.0, "checkpoints": cps_no_travel})
        self.assertEqual(no_travel_route["safety_score"], 0.0)

    def test_tradeoffs_and_rationale_generation(self):
        # Route 1: Safe but slightly longer
        r1 = {
            "id": "r1",
            "name": "Northern Bypass",
            "distance_miles": 120.0,
            "duration_seconds": 7200.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "LOW"},
                {"distance_from_origin_miles": 120.0, "final_risk": "LOW"},
            ]
        }
        # Route 2: Shortest and fastest, but high risk
        r2 = {
            "id": "r2",
            "name": "Direct Highway",
            "distance_miles": 100.0,
            "duration_seconds": 6000.0,
            "checkpoints": [
                {"distance_from_origin_miles": 0.0, "final_risk": "HIGH"},
                {"distance_from_origin_miles": 100.0, "final_risk": "HIGH"},
            ]
        }

        result = rank_and_recommend_routes([r1, r2])
        self.assertEqual(result["recommended_route_id"], "r1")
        self.assertEqual(result["tradeoffs"]["safest_route_id"], "r1")
        self.assertEqual(result["tradeoffs"]["shortest_route_id"], "r2")
        self.assertEqual(result["tradeoffs"]["fastest_route_id"], "r2")
        self.assertIn("Northern Bypass", result["recommendation_rationale"])
        self.assertIn("Direct Highway", result["recommendation_rationale"])

    def test_severe_alerts_extraction(self):
        r_severe = {
            "id": "r-alert",
            "name": "I-80 Corridor",
            "distance_miles": 50.0,
            "duration_seconds": 3600.0,
            "checkpoints": [
                {
                    "checkpoint_index": 1,
                    "distance_from_origin_miles": 25.0,
                    "coordinates": [-88.0, 41.5],
                    "estimated_arrival_time": "2026-10-30T15:00:00Z",
                    "final_risk": "SEVERE",
                    "wind_speed_mph": 48.0,
                    "rain_intensity_in_hr": 0.1,
                    "snow_intensity_in_hr": 0.0,
                },
                {
                    "checkpoint_index": 2,
                    "distance_from_origin_miles": 50.0,
                    "coordinates": [-88.5, 41.5],
                    "estimated_arrival_time": "2026-10-30T16:00:00Z",
                    "final_risk": "NO_TRAVEL",
                    "wind_speed_mph": 65.0,
                    "rain_intensity_in_hr": 0.0,
                    "snow_intensity_in_hr": 1.5,
                }
            ]
        }
        result = rank_and_recommend_routes([r_severe])
        alerts = result.get("severe_alerts", [])
        self.assertEqual(len(alerts), 2)
        self.assertEqual(alerts[0]["risk"], "SEVERE")
        self.assertIn("EXERCISE EXTREME CAUTION", alerts[0]["recommended_action"])
        self.assertEqual(alerts[1]["risk"], "NO_TRAVEL")
        self.assertIn("SUSPEND TRANSIT", alerts[1]["recommended_action"])


class RoutingAndForecastEdgeCaseTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_same_origin_and_destination_string_rejected(self):
        resp = self.client.post('/api/routes/', {
            'origin': 'Chicago, IL',
            'destination': 'chicago, il'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("same location", resp.data['error'])

    @patch('routing.services.requests.get')
    def test_geocoded_same_location_rejected(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Both origin and destination resolve to identical coordinates
        mock_resp.json.return_value = {
            "features": [{
                "geometry": {"coordinates": [8.681495, 49.41461]},
                "properties": {"label": "Same City Center"}
            }]
        }
        mock_get.return_value = mock_resp

        resp = self.client.post('/api/routes/', {
            'origin': 'Location A',
            'destination': 'Location B'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("resolve to the same location", resp.data['error'])

    @patch('routing.weather.fetch_weather_forecast')
    @patch('routing.services.requests.post')
    @patch('routing.services.requests.get')
    def test_only_one_route_returned(self, mock_geo_get, mock_dirs_post, mock_weather_fetch):
        # Geocode success
        mock_geo = MagicMock()
        mock_geo.status_code = 200
        mock_geo.json.side_effect = [
            {"features": [{"geometry": {"coordinates": [8.68, 49.41]}, "properties": {"label": "Origin"}}]},
            {"features": [{"geometry": {"coordinates": [8.46, 49.48]}, "properties": {"label": "Dest"}}]}
        ]
        mock_geo_get.return_value = mock_geo

        # ORS returns exactly 1 feature
        mock_dirs = MagicMock()
        mock_dirs.status_code = 200
        mock_dirs.json.return_value = {
            "features": [{
                "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.46, 49.48]]},
                "properties": {"summary": {"distance": 20000.0, "duration": 1500.0}}
            }]
        }
        mock_dirs_post.return_value = mock_dirs
        mock_weather_fetch.return_value = []

        resp = self.client.post('/api/routes/', {'origin': 'A', 'destination': 'B'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['routes_count'], 1)
        self.assertEqual(len(resp.data['routes']), 1)
        self.assertEqual(resp.data['recommended_route_id'], 'route-1')

    @patch('routing.weather.fetch_weather_forecast')
    @patch('routing.services.requests.post')
    @patch('routing.services.requests.get')
    def test_two_routes_returned(self, mock_geo_get, mock_dirs_post, mock_weather_fetch):
        mock_geo = MagicMock()
        mock_geo.status_code = 200
        mock_geo.json.side_effect = [
            {"features": [{"geometry": {"coordinates": [8.68, 49.41]}, "properties": {"label": "Origin"}}]},
            {"features": [{"geometry": {"coordinates": [8.46, 49.48]}, "properties": {"label": "Dest"}}]}
        ]
        mock_geo_get.return_value = mock_geo

        # Exactly 2 routes returned
        mock_dirs = MagicMock()
        mock_dirs.status_code = 200
        mock_dirs.json.return_value = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.46, 49.48]]},
                    "properties": {"summary": {"distance": 20000.0, "duration": 1500.0}}
                },
                {
                    "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.50, 49.44], [8.46, 49.48]]},
                    "properties": {"summary": {"distance": 22000.0, "duration": 1700.0}}
                }
            ]
        }
        mock_dirs_post.return_value = mock_dirs
        mock_weather_fetch.return_value = []

        resp = self.client.post('/api/routes/', {'origin': 'A', 'destination': 'B'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['routes_count'], 2)
        self.assertEqual(len(resp.data['routes']), 2)

    @patch('routing.services.requests.post')
    @patch('routing.services.requests.get')
    def test_no_routes_returned_handles_gracefully(self, mock_geo_get, mock_dirs_post):
        mock_geo = MagicMock()
        mock_geo.status_code = 200
        mock_geo.json.side_effect = [
            {"features": [{"geometry": {"coordinates": [8.68, 49.41]}, "properties": {"label": "Origin"}}]},
            {"features": [{"geometry": {"coordinates": [8.46, 49.48]}, "properties": {"label": "Dest"}}]}
        ]
        mock_geo_get.return_value = mock_geo

        # ORS returns empty features across all attempts
        mock_dirs = MagicMock()
        mock_dirs.status_code = 200
        mock_dirs.json.return_value = {"features": []}
        mock_dirs_post.return_value = mock_dirs

        resp = self.client.post('/api/routes/', {'origin': 'A', 'destination': 'B'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No viable truck routes", resp.data['error'])

    @patch('routing.weather.fetch_weather_forecast')
    @patch('routing.services.requests.post')
    @patch('routing.services.requests.get')
    def test_duplicate_routes_deduplicated(self, mock_geo_get, mock_dirs_post, mock_weather_fetch):
        mock_geo = MagicMock()
        mock_geo.status_code = 200
        mock_geo.json.side_effect = [
            {"features": [{"geometry": {"coordinates": [8.68, 49.41]}, "properties": {"label": "Origin"}}]},
            {"features": [{"geometry": {"coordinates": [8.46, 49.48]}, "properties": {"label": "Dest"}}]}
        ]
        mock_geo_get.return_value = mock_geo

        # 2 identical features returned by ORS
        mock_dirs = MagicMock()
        mock_dirs.status_code = 200
        mock_dirs.json.return_value = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.46, 49.48]]},
                    "properties": {"summary": {"distance": 20000.0, "duration": 1500.0}}
                },
                {
                    "geometry": {"type": "LineString", "coordinates": [[8.68, 49.41], [8.46, 49.48]]},
                    "properties": {"summary": {"distance": 20000.0, "duration": 1500.0}}
                }
            ]
        }
        mock_dirs_post.return_value = mock_dirs
        mock_weather_fetch.return_value = []

        resp = self.client.post('/api/routes/', {'origin': 'A', 'destination': 'B'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Should deduplicate to 1 route
        self.assertEqual(resp.data['routes_count'], 1)

    @patch('routing.services.requests.get')
    def test_routing_provider_failure_handles_gracefully(self, mock_geo_get):
        mock_geo_get.side_effect = requests.RequestException("ORS Network Error")

        resp = self.client.post('/api/routes/', {'origin': 'A', 'destination': 'B'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unavailable or timed out", resp.data['error'])

    def test_malformed_route_geometry_in_checkpoints(self):
        # Empty coordinates list
        cps_empty = generate_checkpoints([], 50.0, 3600.0, datetime.now(timezone.utc))
        self.assertEqual(cps_empty, [])

        # Single coordinate point
        cps_single = generate_checkpoints([[8.68, 49.41]], 0.0, 0.0, datetime.now(timezone.utc))
        self.assertEqual(len(cps_single), 1)
        self.assertEqual(cps_single[0]['distance_from_origin_miles'], 0.0)

    def test_missing_or_invalid_route_duration_fallback(self):
        # 50 miles with duration = 0 -> calculates fallback duration (1 hour = 3600s)
        coords = [[0.0, 0.0], [0.0, 0.72]]
        cps = generate_checkpoints(coords, 50.0, 0.0, datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc), sampling_interval_miles=25)
        self.assertGreater(len(cps), 1)
        # Final checkpoint ETA should be approximately 1 hour after departure
        self.assertEqual(cps[-1]['estimated_arrival_time'], "2026-10-30T13:00:00+00:00")

    def test_forecast_slider_hourly_timeline_and_unavailable_time(self):
        dep = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        checkpoints = [{
            "checkpoint_index": 0,
            "coordinates": [8.68, 49.41],
            "distance_from_origin_miles": 0.0,
            "estimated_arrival_time": dep.isoformat()
        }]

        # Mock Open-Meteo with only 24 hours of data (hours 0 to 23)
        mock_times = [(dep + timedelta(hours=i)).strftime('%Y-%m-%dT%H:00') for i in range(24)]
        mock_wind = [15.0] * 24
        mock_rain = [0.0] * 24
        mock_snow = [0.0] * 24

        with patch('routing.weather.fetch_weather_forecast') as mock_fetch:
            mock_fetch.return_value = [{
                "hourly": {
                    "time": mock_times,
                    "wind_speed_10m": mock_wind,
                    "rain": mock_rain,
                    "snowfall": mock_snow
                }
            }]

            enriched = enrich_checkpoints_with_weather(checkpoints, load_weight_lbs=30000, departure_datetime=dep)
            self.assertEqual(len(enriched), 1)
            timeline = enriched[0].get("hourly_forecasts", [])
            # Must contain 49 hours (0h to 48h)
            self.assertEqual(len(timeline), 49)

            # Hour 0 (+0h): within available horizon
            self.assertEqual(timeline[0]["offset_hours"], 0)
            self.assertEqual(timeline[0]["weather_status"], "AVAILABLE")
            self.assertEqual(timeline[0]["wind_speed_mph"], 15.0)

            # Hour 36 (+36h): outside 24h horizon -> must be UNAVAILABLE and UNKNOWN
            self.assertEqual(timeline[36]["offset_hours"], 36)
            self.assertEqual(timeline[36]["weather_status"], "UNAVAILABLE")
            self.assertEqual(timeline[36]["final_risk"], "UNKNOWN")
            self.assertIsNone(timeline[36]["wind_speed_mph"])

    def test_health_check_endpoint(self):
        client = APIClient()
        response = client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertEqual(response.data["service"], "weather-aware-truck-routing")
        self.assertIn("ors_configured", response.data)
        self.assertIn("timestamp", response.data)


class RoadExtractionAndHighwayTests(TestCase):
    def test_parse_route_roads_with_named_and_major_roads(self):
        from routing.services import parse_route_roads

        steps = [
            {"name": "Wielandtstraße", "distance": 142.0, "duration": 30.0, "way_points": [0, 5], "instruction": "Turn left"},
            {"name": "Vangerowstraße, B 37", "distance": 360.0, "duration": 40.0, "way_points": [5, 15], "instruction": "Turn left onto B 37"},
            {"name": "B 37", "distance": 15000.0, "duration": 600.0, "way_points": [15, 100], "instruction": "Keep left onto B 37"},
            {"name": "A 5 Autobahn", "distance": 25000.0, "duration": 900.0, "way_points": [100, 200], "instruction": "Merge onto A 5"},
            {"name": "Main Street", "distance": 500.0, "duration": 60.0, "way_points": [200, 220], "instruction": "Turn right"},
        ]

        waycategory_summary = [
            {"value": 1.0, "distance": 25000.0, "amount": 61.0},
            {"value": 0.0, "distance": 16002.0, "amount": 39.0},
        ]
        tollways_summary = [
            {"value": 0.0, "distance": 41002.0, "amount": 100.0},
        ]

        result = parse_route_roads(
            steps=steps,
            waycategory_summary=waycategory_summary,
            tollways_summary=tollways_summary,
            total_distance_meters=41002.0,
        )

        self.assertEqual(result["total_roads_count"], 5)
        self.assertEqual(result["roads_travel_order"], [
            "Wielandtstraße",
            "Vangerowstraße, B 37",
            "B 37",
            "A 5 Autobahn",
            "Main Street",
        ])

        # Major roads identified
        major_names = [r["name"] for r in result["major_roads"]]
        self.assertIn("Vangerowstraße, B 37", major_names)
        self.assertIn("B 37", major_names)
        self.assertIn("A 5 Autobahn", major_names)
        self.assertNotIn("Wielandtstraße", major_names)
        self.assertNotIn("Main Street", major_names)

        # Highway references extracted
        b37_road = next(r for r in result["roads"] if r["name"] == "B 37")
        self.assertIn("B 37", b37_road["highway_refs"])

        a5_road = next(r for r in result["roads"] if r["name"] == "A 5 Autobahn")
        self.assertIn("A 5", a5_road["highway_refs"])
        self.assertEqual(a5_road["road_type"], "motorway")

        # Highway and Toll summary
        self.assertGreater(result["highway_distance_miles"], 15.0)
        self.assertEqual(result["toll_distance_miles"], 0.0)
        self.assertFalse(result["has_toll_roads"])

    def test_parse_route_roads_unnamed_and_missing_instructions(self):
        from routing.services import parse_route_roads

        # Test empty steps
        empty_res = parse_route_roads([])
        self.assertEqual(empty_res["roads"], [])
        self.assertEqual(empty_res["roads_travel_order"], [])
        self.assertEqual(empty_res["total_roads_count"], 0)

        # Test None steps
        none_res = parse_route_roads(None)
        self.assertEqual(none_res["roads"], [])

        # Test unnamed roads
        steps = [
            {"name": "-", "distance": 400.0, "duration": 25.0, "way_points": [0, 10]},
            {"name": "", "distance": 200.0, "duration": 15.0, "way_points": [10, 20]},
            {"name": None, "distance": 3000.0, "duration": 120.0, "way_points": [20, 50]},
        ]
        # Coordinates 20 to 50 are inside waycategory 1 (Motorway)
        waycategory_values = [[0, 20, 0], [20, 50, 1]]

        result = parse_route_roads(steps=steps, waycategory_values=waycategory_values)

        # First two unnamed roads are local/unclassified -> "Road name unavailable"
        # and they are consecutive so they get merged!
        self.assertEqual(result["roads"][0]["name"], "Road name unavailable")
        self.assertEqual(result["roads"][0]["distance_meters"], 600.0)
        self.assertFalse(result["roads"][0]["is_major_road"])

        # Third step is inside motorway waycategory -> classified as Motorway / Highway
        self.assertEqual(result["roads"][1]["name"], "Motorway / Highway (Name unassigned)")
        self.assertTrue(result["roads"][1]["is_major_road"])
        self.assertEqual(result["roads"][1]["road_type"], "motorway")

    def test_parse_route_roads_consecutive_duplicates_deduplication(self):
        from routing.services import parse_route_roads

        steps = [
            {"name": "Route 66", "distance": 100.0, "duration": 10.0},
            {"name": "Route 66", "distance": 200.0, "duration": 20.0},
            {"name": "Route 66", "distance": 300.0, "duration": 30.0},
            {"name": "Elm Street", "distance": 50.0, "duration": 5.0},
            {"name": "Route 66", "distance": 400.0, "duration": 40.0},
        ]

        result = parse_route_roads(steps)

        # 3 consecutive "Route 66" merged into 1, then "Elm Street", then non-consecutive "Route 66"
        self.assertEqual(result["total_roads_count"], 3)
        self.assertEqual(result["roads_travel_order"], ["Route 66", "Elm Street", "Route 66"])
        self.assertEqual(result["roads"][0]["distance_meters"], 600.0)
        self.assertEqual(result["roads"][0]["duration_seconds"], 60.0)
        self.assertEqual(result["roads"][2]["distance_meters"], 400.0)

    def test_parse_route_roads_with_tollways_and_highways(self):
        from routing.services import parse_route_roads

        steps = [
            {"name": "I-95 Tollway", "distance": 16093.4, "duration": 600.0},
        ]
        waycategory_summary = [{"value": 3.0, "distance": 16093.4, "amount": 100.0}]
        tollways_summary = [{"value": 1.0, "distance": 16093.4, "amount": 100.0}]

        result = parse_route_roads(
            steps=steps,
            waycategory_summary=waycategory_summary,
            tollways_summary=tollways_summary,
            total_distance_meters=16093.4,
        )

        self.assertEqual(result["highway_distance_miles"], 10.0)
        self.assertEqual(result["highway_percentage"], 100.0)
        self.assertEqual(result["toll_distance_miles"], 10.0)
        self.assertEqual(result["toll_percentage"], 100.0)
        self.assertTrue(result["has_toll_roads"])
        self.assertIn("I-95", result["roads"][0]["highway_refs"])

    @patch('routing.services.requests.get')
    def test_geocode_location_ors_auth_failure_falls_back_to_nominatim(self, mock_get):
        from routing.services import geocode_location
        # First call is to ORS: returns 401 Unauthorized
        mock_ors_resp = MagicMock()
        mock_ors_resp.status_code = 401

        # Second call is to Nominatim: returns 200 with coordinates
        mock_nom_resp = MagicMock()
        mock_nom_resp.status_code = 200
        mock_nom_resp.json.return_value = [
            {"display_name": "Delhi, India", "lon": "77.2169", "lat": "28.6664"}
        ]

        mock_get.side_effect = [mock_ors_resp, mock_nom_resp]

        result = geocode_location("Delhi")
        self.assertEqual(result["name"], "Delhi, India")
        self.assertAlmostEqual(result["coordinates"][0], 77.2169)
        self.assertAlmostEqual(result["coordinates"][1], 28.6664)

    @patch('routing.services.requests.get')
    @patch('routing.services.requests.post')
    def test_get_routes_ors_auth_failure_falls_back_to_osrm(self, mock_post, mock_get):
        from routing.services import get_routes
        # ORS POST returns 401 Unauthorized
        mock_ors_resp = MagicMock()
        mock_ors_resp.status_code = 401
        mock_post.return_value = mock_ors_resp

        # OSRM GET returns 200 OK with route
        mock_osrm_resp = MagicMock()
        mock_osrm_resp.status_code = 200
        mock_osrm_resp.json.return_value = {
            "code": "Ok",
            "routes": [{
                "distance": 500000.0,
                "duration": 20000.0,
                "geometry": {"type": "LineString", "coordinates": [[77.2, 28.6], [80.9, 26.8]]},
                "legs": [{
                    "steps": [
                        {"name": "Ganga Expressway", "ref": "NEX", "distance": 400000.0, "duration": 15000.0, "maneuver": {"type": "depart"}},
                        {"name": "Local Road", "ref": "", "distance": 100000.0, "duration": 5000.0, "maneuver": {"type": "turn"}}
                    ]
                }]
            }]
        }
        mock_get.return_value = mock_osrm_resp

        routes = get_routes([77.2, 28.6], [80.9, 26.8])
        self.assertEqual(len(routes), 1)
        self.assertIn("NEX", routes[0]["name"])
        self.assertIn("Ganga Expressway", routes[0]["roads_used"][0]["name"])
        self.assertEqual(len(routes[0]["roads_used"]), 2)
        self.assertEqual(routes[0]["roads_travel_order"], ["Ganga Expressway (NEX)", "Local Road"])
        self.assertGreater(routes[0]["distance_miles"], 300.0)

