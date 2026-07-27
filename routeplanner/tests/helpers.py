from routeplanner.services.geo import haversine_miles


def build_straight_route(lat, lon_start, lon_end, num_points=11, total_miles=None):
    """A synthetic straight (fixed-latitude) route for tests.

    By default cumulative mileage is the real haversine distance between
    consecutive points. Pass `total_miles` to instead get an exact linear
    mileage split (handy when a test wants a round total distance rather
    than whatever the great-circle length of the synthetic line works out to).
    """
    lons = [lon_start + (lon_end - lon_start) * i / (num_points - 1) for i in range(num_points)]
    coordinates = [(lat, lon) for lon in lons]

    if total_miles is not None:
        cumulative = [total_miles * i / (num_points - 1) for i in range(num_points)]
    else:
        cumulative = [0.0]
        for i in range(1, len(coordinates)):
            prev, cur = coordinates[i - 1], coordinates[i]
            cumulative.append(cumulative[-1] + haversine_miles(prev[0], prev[1], cur[0], cur[1]))

    return coordinates, cumulative
