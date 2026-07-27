import math

from stations.models import FuelStation

from .geo import (
    MILES_PER_DEGREE_LAT,
    miles_to_lat_degrees,
    miles_to_lon_degrees,
    project_to_plane_miles,
    simplify_polyline_indices,
)

CORRIDOR_MAX_ROUTE_POINTS = 600

STATION_FIELDS = ("id", "name", "city", "state", "retail_price", "latitude", "longitude")


def _bounding_box(route_points, buffer_miles):
    lats = [p[0] for p in route_points]
    lons = [p[1] for p in route_points]
    mean_lat = sum(lats) / len(lats)

    lat_pad = miles_to_lat_degrees(buffer_miles)
    lon_pad = miles_to_lon_degrees(buffer_miles, mean_lat)

    return (
        min(lats) - lat_pad,
        max(lats) + lat_pad,
        min(lons) - lon_pad,
        max(lons) + lon_pad,
    )


def find_candidate_stations(coordinates, cumulative_miles, buffer_miles):
    """Return stations within `buffer_miles` of the route, each annotated
    with its projected mile-marker position along the route.

    Filter pipeline, cheapest first:
    1. RDP-simplify the route (a no-op if the caller pre-simplified).
    2. DB-level bounding-box query (indexed lat/lon columns).
    3. A coarse spatial grid over the projected route segments (cell size =
       buffer): each station only tests the handful of segments registered
       in its own cell, instead of every segment on the route. Stations
       inside the bounding box but far from the actual route land in empty
       cells and are skipped without a single distance computation -- this
       matters on a cross-country route, whose bounding box covers most of
       the continent.
    All distance math runs on a one-time planar projection in miles (pure
    arithmetic per station/segment pair, no per-pair trigonometry).
    """
    indices = simplify_polyline_indices(coordinates, max_points=CORRIDOR_MAX_ROUTE_POINTS)
    route_points = [coordinates[i] for i in indices]
    route_miles = [cumulative_miles[i] for i in indices]

    min_lat, max_lat, min_lon, max_lon = _bounding_box(route_points, buffer_miles)

    stations = FuelStation.objects.filter(
        geocode_status=FuelStation.GEOCODE_OK,
        latitude__gte=min_lat,
        latitude__lte=max_lat,
        longitude__gte=min_lon,
        longitude__lte=max_lon,
    ).only(*STATION_FIELDS)

    proj, lon_scale = project_to_plane_miles(route_points)

    cell = buffer_miles
    grid = {}
    for i in range(len(proj) - 1):
        x1, y1 = proj[i]
        x2, y2 = proj[i + 1]
        for cx in range(int(min(x1, x2) // cell) - 1, int(max(x1, x2) // cell) + 2):
            for cy in range(int(min(y1, y2) // cell) - 1, int(max(y1, y2) // cell) + 2):
                grid.setdefault((cx, cy), []).append(i)

    buffer_sq = buffer_miles * buffer_miles
    candidates = []
    for station in stations:
        sx = station.latitude * MILES_PER_DEGREE_LAT
        sy = station.longitude * lon_scale
        segment_indices = grid.get((int(sx // cell), int(sy // cell)))
        if not segment_indices:
            continue

        best_sq = None
        best_mile = None
        for i in segment_indices:
            ax, ay = proj[i]
            bx, by = proj[i + 1]
            dx, dy = bx - ax, by - ay
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                t = 0.0
            else:
                t = ((sx - ax) * dx + (sy - ay) * dy) / seg_len_sq
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            ex = sx - (ax + t * dx)
            ey = sy - (ay + t * dy)
            dist_sq = ex * ex + ey * ey
            if best_sq is None or dist_sq < best_sq:
                best_sq = dist_sq
                best_mile = route_miles[i] + t * (route_miles[i + 1] - route_miles[i])

        if best_sq is not None and best_sq <= buffer_sq:
            candidates.append(
                {
                    "station": station,
                    "mile_marker": best_mile,
                    "distance_from_route_miles": round(math.sqrt(best_sq), 2),
                }
            )

    candidates.sort(key=lambda c: c["mile_marker"])
    return candidates
