from django.conf import settings

from .exceptions import InfeasibleRouteError

EPSILON = 1e-9


def plan_fuel_stops(
    candidates,
    total_distance_miles,
    max_range_miles=None,
    mpg=None,
    stop_cost_usd=None,
    reserve_miles=None,
):
    """Fuel-stop planner: exact shortest-path DP over the station graph.

    Premises (documented in README):

    - The vehicle starts the trip with a full tank (max_range_miles of range).
    - It never plans to dip below a safety reserve (reserve_miles) -- not
      between stops and not at arrival -- so the usable range per fill is
      max_range_miles - reserve_miles.
    - Every stop carries a fixed economic cost (stop_cost_usd: driver time,
      deceleration/detour, ~20-30 min per stop), so the objective minimized is
      fuel dollars + stop_cost_usd * number_of_stops.  Without that term, pure
      price-chasing recommends pocket-change top-offs at every marginally
      cheaper station -- mathematically optimal on fuel alone, not a plan a
      real driver would run.  The *reported* total_fuel_cost_usd is fuel money
      only; the stop cost is an optimization weight, not a billed amount.

    Model: at each chosen stop the truck buys exactly what it needs to reach
    the next planned stop (or the destination) with the reserve intact.  A
    cheap station is exploited by making its hop long (up to the usable
    range).  This keeps the problem a shortest-path DP over stations ordered
    by mile marker: O(n * w) where w is the number of stations within one
    usable-range window.  The one strategy this model gives up versus the
    fully general partial-fill optimum is carrying extra cheap fuel *past* a
    later mandatory stop (fill-to-full carry-over); see README limitations.

    Handy closed form used throughout: a truck coming straight off the
    initial full tank and buying at its first stop for a hop ending at mile x
    needs max(0, (x - usable_miles) / mpg) gallons -- independent of where
    that first stop sits.
    """
    max_range_miles = max_range_miles or settings.VEHICLE_MAX_RANGE_MILES
    mpg = mpg or settings.VEHICLE_MPG
    stop_cost_usd = settings.STOP_COST_USD if stop_cost_usd is None else stop_cost_usd
    reserve_miles = settings.FUEL_RESERVE_MILES if reserve_miles is None else reserve_miles

    total = total_distance_miles
    usable_miles = max_range_miles - reserve_miles
    if usable_miles <= 0:
        raise InfeasibleRouteError(
            f"The safety reserve ({reserve_miles} mi) leaves no usable range "
            f"on a {max_range_miles} mi tank."
        )

    base = {"total_gallons_needed": round(total / mpg, 2)}
    if total <= usable_miles + EPSILON:
        return {"stops": [], "total_fuel_cost_usd": 0.0, **base}

    stations = sorted(
        (c for c in candidates if 0 < c["mile_marker"] < total),
        key=lambda c: c["mile_marker"],
    )

    n = len(stations)
    miles = [c["mile_marker"] for c in stations]
    prices = [float(c["station"].retail_price) for c in stations]

    INF = float("inf")
    # cost[j]: minimum (fuel dollars + stop penalties) already paid at stops
    # strictly before j, for plans where j is NOT the first stop.  Each stop's
    # penalty and purchase are charged on its outgoing edge.  parent[j] is
    # (predecessor index, predecessor_was_first_stop).
    cost = [INF] * n
    parent = [None] * n

    window_start = 0
    for j in range(n):
        while miles[j] - miles[window_start] > usable_miles + EPSILON:
            window_start += 1
        for i in range(window_start, j):
            hop = miles[j] - miles[i]
            if hop <= EPSILON:
                continue
            if miles[i] <= usable_miles + EPSILON:
                # i as the first stop, arriving on the initial full tank.
                buy = max(0.0, (miles[j] - usable_miles) / mpg)
                c = stop_cost_usd + buy * prices[i]
                if c < cost[j]:
                    cost[j] = c
                    parent[j] = (i, True)
            if cost[i] < INF:
                # i as a later stop (arrived there with exactly the reserve).
                c = cost[i] + stop_cost_usd + (hop / mpg) * prices[i]
                if c < cost[j]:
                    cost[j] = c
                    parent[j] = (i, False)

    best = INF
    best_tail = None  # (last stop index, last_stop_was_first)
    for j in range(n):
        if total - miles[j] > usable_miles + EPSILON:
            continue
        if miles[j] <= usable_miles + EPSILON:
            buy = max(0.0, (total - usable_miles) / mpg)
            c = stop_cost_usd + buy * prices[j]
            if c < best:
                best, best_tail = c, (j, True)
        if cost[j] < INF:
            c = cost[j] + stop_cost_usd + ((total - miles[j]) / mpg) * prices[j]
            if c < best:
                best, best_tail = c, (j, False)

    if best_tail is None:
        points = [0.0] + miles + [total]
        gap_start, gap_len = 0.0, total
        for a, b in zip(points, points[1:]):
            if b - a > usable_miles + EPSILON:
                gap_start, gap_len = a, b - a
                break
        raise InfeasibleRouteError(
            f"A {gap_len:.0f}-mile stretch after mile {gap_start:.1f} has no fuel "
            f"station within the usable range ({usable_miles:.0f} mi = "
            f"{max_range_miles:.0f} mi tank range minus {reserve_miles:.0f} mi "
            f"safety reserve); the route cannot be completed with the available "
            f"fuel price data."
        )

    chain = []
    j, was_first = best_tail
    while True:
        chain.append(j)
        if was_first:
            break
        j, was_first = parent[j]
    chain.reverse()

    stops = []
    total_fuel_cost = 0.0
    for idx, si in enumerate(chain):
        next_mile = miles[chain[idx + 1]] if idx + 1 < len(chain) else total
        if idx == 0:
            gallons = max(0.0, (next_mile - usable_miles) / mpg)
        else:
            gallons = (next_mile - miles[si]) / mpg
        fuel_cost = gallons * prices[si]
        total_fuel_cost += fuel_cost
        stops.append(
            {
                "station": stations[si]["station"],
                "mile_marker": round(miles[si], 1),
                "price_per_gallon": prices[si],
                "gallons_purchased": round(gallons, 2),
                "cost_usd": round(fuel_cost, 2),
                "distance_from_route_miles": stations[si]["distance_from_route_miles"],
            }
        )

    return {"stops": stops, "total_fuel_cost_usd": round(total_fuel_cost, 2), **base}
