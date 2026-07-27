import json
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import FuelStopSerializer, RoutePlanRequestSerializer, RoutePlanResponseSerializer
from .services.exceptions import RoutePlannerError
from .services.planner import plan_route


def _coords_from_validated_data(data):
    """Shared by both views below: pull optional explicit lat/lon pairs out
    of a validated RoutePlanRequestSerializer payload."""
    start_coords = None
    if "start_latitude" in data and "start_longitude" in data:
        start_coords = (data["start_latitude"], data["start_longitude"])

    end_coords = None
    if "end_latitude" in data and "end_longitude" in data:
        end_coords = (data["end_latitude"], data["end_longitude"])

    return start_coords, end_coords


class RoutePlanView(APIView):
    """POST /api/v1/route/

    Body: {"start": "Los Angeles, CA", "end": "New York, NY"}
    (or start_latitude/start_longitude + end_latitude/end_longitude to skip
    geocoding entirely).

    Returns the full-resolution route geometry, a link to an interactive map
    preview, the optimal (cheapest) fuel stops needed given the vehicle's
    500-mile range, and the total estimated fuel cost for the trip at 10 mpg.
    """

    def post(self, request):
        request_serializer = RoutePlanRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data
        start_coords, end_coords = _coords_from_validated_data(data)

        try:
            result = plan_route(
                start_query=data.get("start"),
                end_query=data.get("end"),
                start_coords=start_coords,
                end_coords=end_coords,
                strategy=data["strategy"],
            )
        except RoutePlannerError as exc:
            return Response({"error": str(exc)}, status=exc.status_code)

        result["map_url"] = request.build_absolute_uri(
            f"{reverse('route-map-preview')}?{urlencode(data)}"
        )

        response_serializer = RoutePlanResponseSerializer(instance=result)
        return Response(response_serializer.data, status=200)


@method_decorator(xframe_options_exempt, name="get")
class RouteMapPreviewView(APIView):
    """GET /api/v1/route/map/?start=...&end=...

    Renders an interactive Leaflet map (OpenStreetMap tiles, no API key,
    both free) of the route and its recommended fuel stops -- this is the
    link returned as `map_url` by POST /api/v1/route/. Recomputes the plan
    from the query params rather than caching the POST result server-side,
    so the link is stateless and shareable on its own.

    Exempted from Django's default X-Frame-Options: DENY -- this page is
    designed to be a shareable/embeddable link (that's the whole point of
    returning it as `map_url`), so it's fine to allow framing, unlike the
    rest of the app.
    """

    def get(self, request):
        request_serializer = RoutePlanRequestSerializer(data=request.query_params)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data
        start_coords, end_coords = _coords_from_validated_data(data)

        try:
            result = plan_route(
                start_query=data.get("start"),
                end_query=data.get("end"),
                start_coords=start_coords,
                end_coords=end_coords,
                strategy=data["strategy"],
            )
        except RoutePlannerError as exc:
            return render(request, "routeplanner/map_error.html", {"error": str(exc)}, status=exc.status_code)

        context = {
            "route_geometry_json": json.dumps(result["route_geometry_simplified"]),
            "stops_json": json.dumps(FuelStopSerializer(result["fuel_stops"], many=True).data),
            "start_json": json.dumps(result["start"]),
            "end_json": json.dumps(result["end"]),
            "total_distance_miles": result["total_distance_miles"],
            "total_fuel_cost_usd": result["total_fuel_cost_usd"],
            "total_gallons_needed": result["total_gallons_needed"],
        }
        return render(request, "routeplanner/map_preview.html", context)
