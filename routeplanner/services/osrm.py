from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import RoutingError


@dataclass
class RouteResult:
    coordinates: list  # [(lat, lon), ...] in travel order
    cumulative_miles: list  # cumulative distance in miles at each coordinate
    total_distance_miles: float
    total_duration_seconds: float


def _cache_key(start_lat, start_lon, end_lat, end_lon) -> str:
    # Rounded to ~11m precision: repeat requests for "the same" two points
    # (e.g. identical geocoded cities) hit the cache instead of OSRM again.
    return "osrm_route:{:.4f},{:.4f}:{:.4f},{:.4f}".format(start_lat, start_lon, end_lat, end_lon)


def get_route(start_lat, start_lon, end_lat, end_lon) -> RouteResult:
    """Single call to the public OSRM demo server for the driving route
    between two points. Requests full geometry + per-segment distance
    annotations so mile-marker positions can be computed without any further
    network calls.

    Cached (Redis in production, in-process locmem otherwise) with a short
    TTL: identical repeat route requests (e.g. the POST /route/ call and the
    GET /route/map/ preview it links to, for the same trip) reuse this
    instead of hitting OSRM again.
    """
    cache_key = _cache_key(start_lat, start_lon, end_lat, end_lon)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "distance",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RoutingError(f"Routing service unavailable: {exc}") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(f"No route found between the given points ({data.get('code')})")

    route = data["routes"][0]
    geometry_coords = route["geometry"]["coordinates"]  # [lon, lat] pairs
    coordinates = [(lat, lon) for lon, lat in geometry_coords]

    segment_distances_m = route["legs"][0]["annotation"]["distance"]

    cumulative_miles = [0.0]
    running_m = 0.0
    for seg_m in segment_distances_m:
        running_m += seg_m
        cumulative_miles.append(running_m / 1609.344)

    total_distance_miles = route["distance"] / 1609.344

    result = RouteResult(
        coordinates=coordinates,
        cumulative_miles=cumulative_miles,
        total_distance_miles=total_distance_miles,
        total_duration_seconds=route["duration"],
    )
    cache.set(cache_key, result, timeout=settings.ROUTE_CACHE_TTL_SECONDS)
    return result
