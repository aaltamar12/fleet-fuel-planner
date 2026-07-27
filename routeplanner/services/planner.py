from django.conf import settings

from . import corridor, geocoding, osrm
from .geo import simplify_polyline_indices
from .optimizer import plan_fuel_stops

# RDP-simplified once per request and reused for both corridor matching and
# the map preview, instead of each re-simplifying the full-resolution
# (potentially several-thousand-point) OSRM geometry from scratch.
ROUTE_SIMPLIFICATION_POINTS = 600


def plan_route(start_query=None, end_query=None, start_coords=None, end_coords=None, strategy="balanced"):
    """Orchestrates the whole flow with the minimum possible number of calls
    to external services: 0-2 Nominatim geocoding calls (skipped entirely if
    lat/lon are supplied directly) + exactly 1 OSRM routing call.

    `strategy` sets the stop-cost weight the optimizer uses (see
    settings.FUEL_STRATEGY_STOP_COSTS): cheapest_fuel chases every worthwhile
    price, fewest_stops trades fuel dollars for fewer stops, balanced sits in
    between.
    """
    start_lat, start_lon = start_coords if start_coords else geocoding.geocode_location(start_query)
    end_lat, end_lon = end_coords if end_coords else geocoding.geocode_location(end_query)

    route = osrm.get_route(start_lat, start_lon, end_lat, end_lon)

    simplified_indices = simplify_polyline_indices(route.coordinates, max_points=ROUTE_SIMPLIFICATION_POINTS)
    route_points = [route.coordinates[i] for i in simplified_indices]
    route_miles = [route.cumulative_miles[i] for i in simplified_indices]

    candidates = corridor.find_candidate_stations(
        route_points, route_miles, settings.ROUTE_CORRIDOR_BUFFER_MILES
    )

    stop_cost = settings.FUEL_STRATEGY_STOP_COSTS[strategy]
    plan = plan_fuel_stops(candidates, route.total_distance_miles, stop_cost_usd=stop_cost)

    return {
        "strategy": strategy,
        "start": {"latitude": start_lat, "longitude": start_lon},
        "end": {"latitude": end_lat, "longitude": end_lon},
        "total_distance_miles": round(route.total_distance_miles, 1),
        "total_duration_hours": round(route.total_duration_seconds / 3600, 2),
        "total_gallons_needed": plan["total_gallons_needed"],
        "total_fuel_cost_usd": plan["total_fuel_cost_usd"],
        "fuel_stops": plan["stops"],
        "route_geometry": route.coordinates,
        "route_geometry_simplified": route_points,
    }
