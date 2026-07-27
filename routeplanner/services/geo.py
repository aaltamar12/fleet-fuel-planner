"""Small geometry helpers: great-circle distance and polyline simplification.

No third-party geo library is used since the only operations needed are a
haversine distance and a Douglas-Peucker simplification, both under ~40 lines.
"""
import math

EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE_LAT = 69.0


def miles_to_lat_degrees(miles):
    return miles / MILES_PER_DEGREE_LAT


def miles_to_lon_degrees(miles, at_latitude):
    return miles / (MILES_PER_DEGREE_LAT * max(math.cos(math.radians(at_latitude)), 0.1))


def haversine_miles(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def point_segment_distance_miles(px, py, ax, ay, bx, by):
    """Approx distance from point P to segment AB, treating lat/lon as planar
    (fine for the short segments and ~tens-of-miles buffers used here)."""
    ax_m, ay_m = ax, ay * math.cos(math.radians(ax))
    bx_m, by_m = bx, by * math.cos(math.radians(ax))
    px_m, py_m = px, py * math.cos(math.radians(ax))

    dx, dy = bx_m - ax_m, by_m - ay_m
    if dx == 0 and dy == 0:
        return haversine_miles(px, py, ax, ay), 0.0

    t = ((px_m - ax_m) * dx + (py_m - ay_m) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nearest_lat = ax + t * (bx - ax)
    nearest_lon = ay + t * (by - ay)
    return haversine_miles(px, py, nearest_lat, nearest_lon), t


def project_to_plane_miles(points):
    """Equirectangular projection of (lat, lon) points into a local plane
    measured in miles, using the mean latitude for the longitude scale.
    Cheap pure-arithmetic distances on the result are accurate to a few
    percent across a continental route -- more than enough for corridor
    buffers and polyline simplification, both of which already tolerate
    city-centroid-level imprecision."""
    mean_lat = sum(p[0] for p in points) / len(points)
    lon_scale = MILES_PER_DEGREE_LAT * math.cos(math.radians(mean_lat))
    return [(lat * MILES_PER_DEGREE_LAT, lon * lon_scale) for lat, lon in points], lon_scale


# Above this size, uniformly decimate before running RDP: raw OSRM geometry
# for a cross-country route is 30k+ points and RDP alone gets slow in Python.
DECIMATION_THRESHOLD = 5000


def simplify_polyline_indices(points, max_points=800):
    """Ramer-Douglas-Peucker simplification, returning the indices (into the
    original `points` list) of the kept vertices, always including the first
    and last point.

    Used to shrink both the map preview and the corridor-matching workload;
    the full-resolution route geometry is still returned separately in the
    API response. Distances are computed on a one-time planar projection
    (pure arithmetic per point) rather than per-point haversine calls.
    """
    n = len(points)
    if n <= max_points:
        return list(range(n))

    proj, _ = project_to_plane_miles(points)

    def perp_dist_sq(idx, start_i, end_i):
        px, py = proj[idx]
        ax, ay = proj[start_i]
        bx, by = proj[end_i]
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            ex, ey = px - ax, py - ay
            return ex * ex + ey * ey
        t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        ex, ey = px - (ax + t * dx), py - (ay + t * dy)
        return ex * ex + ey * ey

    def rdp(indices, epsilon_sq):
        if len(indices) < 3:
            return indices
        start_i, end_i = indices[0], indices[-1]
        max_dist_sq, split_at = 0.0, None
        for idx in indices[1:-1]:
            dist_sq = perp_dist_sq(idx, start_i, end_i)
            if dist_sq > max_dist_sq:
                max_dist_sq, split_at = dist_sq, idx
        if split_at is not None and max_dist_sq > epsilon_sq:
            left_indices = [i for i in indices if i <= split_at]
            right_indices = [i for i in indices if i >= split_at]
            left = rdp(left_indices, epsilon_sq)
            right = rdp(right_indices, epsilon_sq)
            return left[:-1] + right
        return [start_i, end_i]

    if n > DECIMATION_THRESHOLD:
        step = max(1, n // (4 * max_points))
        base_indices = list(range(0, n, step))
        if base_indices[-1] != n - 1:
            base_indices.append(n - 1)
    else:
        base_indices = list(range(n))

    epsilon = 0.05
    simplified = base_indices
    for _ in range(20):
        simplified = rdp(base_indices, epsilon * epsilon)
        if len(simplified) <= max_points:
            break
        epsilon *= 1.6
    return simplified


def simplify_polyline(points, max_points=800):
    indices = simplify_polyline_indices(points, max_points=max_points)
    return [points[i] for i in indices]
