from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timezone
import logging
import os
from django.conf import settings

from .services import geocode_location, get_routes
from .checkpoints import generate_checkpoints
from .weather import enrich_checkpoints_with_weather
from .ranking import rank_and_recommend_routes

logger = logging.getLogger(__name__)

ALLOWED_INTERVALS = [10, 25, 50]


class HealthCheckView(APIView):
    """
    GET /api/health/
    Health and readiness diagnostic check for production hosting and uptime monitors.
    """
    def get(self, request):
        has_ors_key = bool(
            getattr(settings, 'OPENROUTESERVICE_API_KEY', None) or os.getenv('OPENROUTESERVICE_API_KEY')
        )
        return Response({
            "status": "ok",
            "service": "weather-aware-truck-routing",
            "ors_configured": has_ors_key,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, status=status.HTTP_200_OK)


class RouteCalculationView(APIView):
    """
    POST /api/routes/
    Request Body:
    {
        "origin": "Heidelberg, Germany",
        "destination": "Mannheim, Germany",
        "departure_datetime": "2026-10-30T14:00:00Z",  (optional, defaults to now)
        "load_weight_lbs": 35000,                      (optional, defaults to 0)
        "sampling_interval_miles": 25                  (optional, must be 10, 25, or 50)
    }
    """

    def post(self, request):
        origin_query = str(request.data.get('origin', '')).strip()
        dest_query = str(request.data.get('destination', '')).strip()

        if not origin_query or not dest_query:
            return Response(
                {"error": "Both 'origin' and 'destination' fields are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if origin_query.lower() == dest_query.lower():
            return Response(
                {"error": "Origin and destination cannot be the same location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate departure_datetime
        raw_departure = request.data.get('departure_datetime')
        if raw_departure:
            try:
                departure_dt = datetime.fromisoformat(str(raw_departure))
                if departure_dt.tzinfo is None:
                    departure_dt = departure_dt.replace(tzinfo=timezone.utc)
                else:
                    departure_dt = departure_dt.astimezone(timezone.utc)
            except (ValueError, TypeError):
                return Response(
                    {"error": "Invalid 'departure_datetime' format. Please provide an ISO-8601 string."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            departure_dt = datetime.now(timezone.utc)

        # Validate load_weight_lbs
        raw_weight = request.data.get('load_weight_lbs', 0.0)
        try:
            load_weight_lbs = float(raw_weight)
            if load_weight_lbs < 0:
                return Response(
                    {"error": "'load_weight_lbs' cannot be negative."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "'load_weight_lbs' must be a valid number."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate sampling_interval_miles
        raw_interval = request.data.get('sampling_interval_miles', 25)
        try:
            sampling_interval = int(raw_interval)
            if sampling_interval not in ALLOWED_INTERVALS:
                return Response(
                    {"error": f"'sampling_interval_miles' must be one of {ALLOWED_INTERVALS}."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": f"'sampling_interval_miles' must be an integer: {ALLOWED_INTERVALS}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            origin_info = geocode_location(origin_query)
            dest_info = geocode_location(dest_query)

            # Check if origin and destination resolve to the same point
            from .checkpoints import haversine_distance
            if haversine_distance(origin_info['coordinates'], dest_info['coordinates']) < 0.1:
                return Response(
                    {"error": "Origin and destination resolve to the same location."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            routes = get_routes(origin_info['coordinates'], dest_info['coordinates'])

            # Generate checkpoints and enrich with weather risk analysis
            for route in routes:
                coords = route.get('geometry', {}).get('coordinates', [])
                dist_miles = route.get('distance_miles', 0.0)
                dur_sec = route.get('duration_seconds', 0.0)

                raw_checkpoints = generate_checkpoints(
                    coordinates=coords,
                    total_distance_miles=dist_miles,
                    total_duration_seconds=dur_sec,
                    departure_datetime=departure_dt,
                    sampling_interval_miles=float(sampling_interval)
                )

                enriched_checkpoints = enrich_checkpoints_with_weather(
                    checkpoints=raw_checkpoints,
                    load_weight_lbs=load_weight_lbs,
                    departure_datetime=departure_dt
                )

                route['checkpoints_count'] = len(enriched_checkpoints)
                route['checkpoints'] = enriched_checkpoints

            # Deterministic ranking and recommendation
            ranking_result = rank_and_recommend_routes(routes)

            return Response({
                "origin": origin_info,
                "destination": dest_info,
                "departure_datetime": departure_dt.isoformat(),
                "load_weight_lbs": load_weight_lbs,
                "sampling_interval_miles": sampling_interval,
                "routes_count": len(ranking_result["routes"]),
                "recommended_route_id": ranking_result["recommended_route_id"],
                "has_recommended_route": ranking_result["has_recommended_route"],
                "warning": ranking_result["warning"],
                "recommendation_rationale": ranking_result.get("recommendation_rationale", ""),
                "tradeoffs": ranking_result.get("tradeoffs", {}),
                "severe_alerts": ranking_result.get("severe_alerts", []),
                "routes": ranking_result["routes"]
            }, status=status.HTTP_200_OK)

        except ValueError as ve:
            return Response(
                {"error": str(ve)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception("Unexpected error in RouteCalculationView")
            return Response(
                {"error": "An unexpected error occurred while calculating routes and weather risks."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
