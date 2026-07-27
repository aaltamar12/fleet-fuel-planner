# Fleet Fuel Planner

A Django REST API that, given a start and end location in the USA, returns:

- the driving route (full-resolution geometry + a link to an interactive map preview),
- the optimal (cheapest) fuel stops needed along the way given a 500-mile vehicle range, and
- the total estimated fuel cost for the trip at 10 mpg.

**Stack:** Django 5.1 + Django REST Framework, PostgreSQL, Redis (caching),
Docker/docker-compose.

## Quick start

**Option A — Docker (recommended, runs against real PostgreSQL + Redis):**

```bash
docker compose up --build
```

That's it — the `web` container runs migrations and loads the pre-geocoded
station fixture on startup, `db` is Postgres 16, `redis` backs the cache
described below.

**Option B — plain virtualenv (SQLite, in-process cache, zero external deps):**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py loaddata stations/fixtures/fuel_stations.json   # pre-geocoded station data, ships with the repo
python manage.py runserver
```

`DATABASE_URL` and `REDIS_URL` env vars select Postgres/Redis when set (which
is what `docker-compose.yml` does) and fall back to SQLite / an in-process
cache when they aren't — so both options run the exact same code path.

Then, either way:

```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Los Angeles, CA", "end": "New York, NY"}'
```

A Postman collection is included at `postman/fleet-fuel-planner.postman_collection.json`.

## API

### `POST /api/v1/route/`

Request body — either free-text places or explicit coordinates (coordinates skip
geocoding entirely, saving a network call):

```json
{ "start": "Los Angeles, CA", "end": "New York, NY" }
```

```json
{ "start_latitude": 34.05, "start_longitude": -118.24, "end_latitude": 40.71, "end_longitude": -74.0 }
```

Optional `strategy` field — what "optimal" means for this trip. Real numbers
for LA → NYC:

| strategy | stops | fuel cost | behavior |
|---|---|---|---|
| `cheapest_fuel` | 15 | $716.41 | pure price optimization; chases every worthwhile cents/gal difference, including sub-gallon top-offs |
| `balanced` (default) | 7 | $719.55 | weighs each stop at its real driver-time cost (`STOP_COST_USD`, $15) |
| `fewest_stops` | 6 | $743.31 | heavily penalizes stopping; pays more per gallon to stay on the road |

The full gap between absolute-cheapest and balanced is **$3.14 for 8 fewer
stops** — which is exactly why balanced is the default.

Response (trimmed, real output for LA → NYC):

```json
{
  "strategy": "balanced",
  "start": { "latitude": 34.05, "longitude": -118.24 },
  "end": { "latitude": 40.71, "longitude": -74.0 },
  "total_distance_miles": 2793.6,
  "total_duration_hours": 49.87,
  "total_gallons_needed": 279.36,
  "total_fuel_cost_usd": 719.55,
  "fuel_stops": [
    {
      "station_name": "Maverik #674",
      "city": "North Las Vegas", "state": "NV",
      "latitude": 36.2, "longitude": -115.12,
      "mile_marker": 271.3,
      "price_per_gallon": 3.2823,
      "gallons_purchased": 23.3,
      "cost_usd": 76.5,
      "distance_from_route_miles": 0.4
    }
    // ... 6 more stops for this route, all 16-43 gallon purchases
  ],
  "map_url": "http://localhost:8000/api/v1/route/map/?start=Los+Angeles%2C+CA&end=New+York%2C+NY",
  "route_geometry": [[34.05, -118.24], "... every point on the driving route ..."]
}
```

Opening `map_url` in a browser renders an interactive Leaflet map (OpenStreetMap
tiles, no API key) with the route drawn and each recommended stop as a clickable
marker showing its price, gallons, and cost.

Error responses: `400` (bad request shape), `422` (a place couldn't be geocoded, or
no route is completable with the available fuel data), `502` (routing service
unreachable).

## Architecture

```
Dockerfile / docker-compose.yml / docker-entrypoint.sh   # app + Postgres + Redis
routeplanner/
  services/
    geocoding.py   # Nominatim: free-text place -> (lat, lon)
    osrm.py        # OSRM: (start, end) -> route geometry + per-segment distances
    corridor.py     # which fuel stations sit near the route, and at what mile marker
    optimizer.py    # which of those stations to buy from, and how much, to minimize cost
    planner.py      # orchestrates the above, once, and reuses the simplified route for both
                     # corridor matching and the map preview
  views.py            # RoutePlanView (JSON) + RouteMapPreviewView (HTML/Leaflet)
  templates/routeplanner/map_preview.html   # Leaflet + OpenStreetMap tiles, no API key
  serializers.py / urls.py
stations/
  models.py                      # FuelStation
  management/commands/
    import_stations.py           # CSV + geocode cache -> DB
    list_geocoding_failures.py    # audit stations excluded from route matching
scripts/geocode_cities.py        # one-time ETL: geocode every city/state in the CSV
```

### Why only 1–3 calls to external map/routing APIs per request

- **Geocoding (Nominatim):** at most 2 calls per request (start + end), and 0 if the
  caller passes coordinates directly.
- **Routing (OSRM):** **exactly 1 call**, requesting `overview=full` geometry plus
  `annotations=distance`. That one response gives the full route polyline *and* the
  exact distance between every pair of consecutive points, which is everything the
  optimizer needs to compute mile-marker positions — no follow-up calls.
- **Fuel station lookup:** these come from **our own database**, not a third-party
  API. The ~7,500 stations in the OPIS dataset are geocoded **once**, offline (see
  below), not per-request. A request only does a bounding-box query.

### Map preview: a self-hosted Leaflet page instead of a third-party image API

The original design returned `map_url` as a link to a free static-map-image
generator (`staticmap.openstreetmap.de`, a community-run wrapper around OSM
tiles). While verifying the full end-to-end flow before recording the demo, that
host turned out to no longer resolve at all (`Could not resolve host`) — it's
been decommissioned. Rather than depend on an unmaintained third party for a
core part of the deliverable, `map_url` now points at this API's own
`GET /api/v1/route/map/` endpoint, which renders an interactive Leaflet map
(OpenStreetMap tiles, both free, no API key, verified reachable) with the route
drawn and every recommended stop as a clickable marker — arguably a better "map
of the route" than a flat image, and one this project fully controls. That
endpoint recomputes the plan from its own query params rather than caching the
POST result server-side, so the link stays stateless and shareable on its own.

### Fuel price data → coordinates

The source CSV (`data/fuel_prices_us.csv`, filtered from the original to the 50
states + DC) gives each truck stop's name, a highway-exit description as its
"address" (e.g. `I-44, EXIT 283 & US-69`), city, state, and price — but no
coordinates, and the address isn't a geocodable street address.

**Assumption:** each station is located at its **city centroid**. This is precise
enough to decide "is this station within N miles of the route" for any reasonable
corridor width, and is the only geocodable signal the source data actually offers.

`scripts/geocode_cities.py` geocodes every *unique* (city, state) pair (3,813 of
them, not 7,531 rows) once via Nominatim, respecting its 1 req/sec usage policy,
and caches the result in `data/city_geocode_cache.json` (resumable — reruns skip
already-cached pairs).

Following the same pattern used for handling geocoding failures in a prior
production system: a failed city lookup falls back to the **state centroid**, and
if even that fails the station is kept in the database but flagged
`geocoding_failed=True` and **excluded from route matching** — it's surfaced for
audit via `python manage.py list_geocoding_failures`, not silently dropped and not
used to (incorrectly) suggest a stop that isn't really near the route.

`python manage.py import_stations` reads the CSV + the geocode cache and
(re)populates the `FuelStation` table. A fixture built from that import ships in
the repo (`stations/fixtures/fuel_stations.json`) so `loaddata` works offline —
grading doesn't require re-running the hour-long geocoding step.

### Fuel stop optimization algorithm

The planner models the problem the way fleet fuel optimizers actually do:
minimize **fuel dollars + a fixed economic cost per stop**, never planning to
dip below a safety reserve. Solved exactly (for this model) with a
shortest-path dynamic program over the station graph.

**Premises (all configurable via environment variables):**

- **Full tank at departure** (`VEHICLE_MAX_RANGE_MILES=500`, at
  `VEHICLE_MPG=10` that's a 50-gallon tank). A stop is only planned once
  continuing would violate the reserve.
- **Safety reserve** (`FUEL_RESERVE_MILES=60`): the plan never schedules the
  truck below ~1/8 tank, neither between stops nor at arrival — stations
  close, ramps back up, price data ages. Usable range per fill is therefore
  440 miles, which is why a 460-mile trip refuels once even though it fits
  the nominal 500-mile range.
- **Cost per stop** (`STOP_COST_USD=15`): pulling a truck off the highway,
  fueling, and re-entering costs 20–30 minutes of driver time. Without this
  term, pure price-chasing is mathematically optimal but operationally
  absurd — on a real Los Angeles → New York run it recommended stopping
  three times within 25 miles near Denver to buy 1.57, 0.58 and 19.69
  gallons chasing cents/gallon differences. With it, the same route plans
  **7 substantial stops (16–43 gal each)** instead of 16. The stop cost is
  an optimization weight only; `total_fuel_cost_usd` reports fuel money.
  The request's `strategy` field just moves this dial:
  `cheapest_fuel` sets it to 0 (price is everything), `fewest_stops` raises
  it to `FEWEST_STOPS_COST_USD` ($75), `balanced` uses the $15 default.

**The DP:** stations (already corridor-filtered and projected to mile
markers) are nodes ordered by mile; an edge i→j means "buy at i exactly what
is needed to arrive at j with the reserve intact" and costs
`gallons × price_i + STOP_COST_USD`, feasible when the hop fits the usable
range. Cheap stations are exploited by making their hops long. A first-stop
edge accounts for the free fuel already in the tank at departure. The
cheapest chain from start to destination is the plan — O(n × w) where w is
the number of stations within one usable-range window, ~30 ms in-process for
a coast-to-coast corridor with ~900 candidate stations.

If any stretch of the route has no station within the usable range, the API
returns a `422` naming the offending gap, rather than silently producing an
unsafe plan.

**Model trade-off (documented deliberately):** at each stop the truck buys
exactly the next hop's need. The one strategy this gives up versus the fully
general partial-fill optimum is *fill-to-full carry-over* — buying extra
cheap fuel to reduce the purchase at a later, more expensive mandatory stop.
Supporting it turns the state space per-predecessor (Khuller et al.'s "gas
station problem" structure) for a marginal saving on realistic corridors
where stations appear every 10–20 miles; noted as a follow-up.

### Performance

Measured on the real LA → New York request (33k-point OSRM geometry, ~4,000
stations inside the bounding box, 864 corridor candidates): **~0.3 s
end-to-end** with warm caches, of which ~0.17 s is in-process work. How:

- Route polyline is simplified (Ramer-Douglas-Peucker) **once per request**,
  down to ~600 points, and reused for both corridor matching and the map
  preview. RDP runs on a one-time planar projection (pure arithmetic per
  point instead of per-point haversine trigonometry), with a uniform
  decimation pre-pass for very large geometries — 3.0 s → 0.09 s on the
  cross-country route.
- Corridor matching narrows stations with a DB-level bounding-box query
  (indexed lat/lon, `.only()` to skip unused columns), then a **coarse
  spatial grid over the route segments** (cell size = buffer): each station
  tests only the handful of segments in its own cell, and stations inside
  the bounding box but far from the route are discarded without a single
  distance computation. 3.9 s → 0.06 s.
- The DP optimizer itself is ~30 ms for ~900 candidates.
- Everything else (geocoding, routing) is at most 3 sequential HTTP calls,
  all cached (below), so a repeat or map-preview request does zero external
  calls.

### Caching (Redis)

Geocoding results and OSRM routes are cached (`django.core.cache`, Redis via
`REDIS_URL` in Docker, in-process locmem otherwise):

- **Geocoding** (`services/geocoding.py`): a place's coordinates don't change,
  so the cache key is a hash of the normalized query with a 30-day TTL. This is
  the caching that matters most here — it's the same lever as passing explicit
  `start_latitude`/`start_longitude` to skip geocoding, just automatic for any
  repeated place name, which directly reduces load on the free, rate-limited
  Nominatim service.
- **Routing** (`services/osrm.py`): keyed on coordinates rounded to ~11m
  precision, 1-hour TTL. This also means `POST /api/v1/route/` and the
  `GET /api/v1/route/map/` link it returns for the *same* trip share one OSRM
  call instead of two, since the map preview recomputes the plan independently
  (see below).

Verified against the real stack (`docker compose up`, not mocked): a request
for Dallas → Chicago populates `geocode:*` and `osrm_route:*` keys in Redis,
and a repeat of the same request returns without hitting Nominatim/OSRM again.

## Testing

```bash
python manage.py test
```

38 tests cover: the DP optimizer (reserve forcing a stop before nominal
range, cheaper-station selection, no micro-stops for marginal price
differences, the stop cost flipping a plan, the penalty staying out of the
billed fuel cost, and the infeasible-gap case), the corridor
matching/mile-marker projection, the geometry helpers, the import command's
geocoding-failure handling, both API views (JSON route endpoint + HTML map
preview), the `strategy` field (validation, echo, propagation into the map
link), and the geocoding/routing cache behavior (repeat calls hit the
cache, not the network; failures aren't cached; different inputs both hit
the network) — all fully mocked against Nominatim and OSRM, so the suite
runs offline and fast regardless of which cache backend is configured.

## Deployment notes (GCP)

Not deployed for this exercise, but the container-first setup maps directly onto
Cloud Run: `docker build` the same `Dockerfile`, push to Artifact Registry, and
run it on Cloud Run with `DATABASE_URL` pointing at Cloud SQL for Postgres
(via the Cloud SQL Auth Proxy sidecar, or a private-IP VPC connector) and
`REDIS_URL` pointing at Memorystore for Redis on the same VPC connector.
`ALLOWED_HOSTS`/`DJANGO_DEBUG`/`DJANGO_SECRET_KEY` are already environment-driven
(`config/settings.py`), so no code changes would be needed for that move — only
Cloud Run env vars and a VPC connector for the two managed services.

## Known limitations / possible follow-ups

- Station coordinates are city-centroid approximations, not exact station
  locations — acceptable for a corridor-matching use case, not for turn-by-turn
  "take this exact exit" guidance.
- The DP buys exactly the next hop's need at each stop; fill-to-full
  carry-over past a mandatory expensive stop (the fully general partial-fill
  optimum) is a known refinement, as are in-network/negotiated fuel prices
  and IFTA per-state tax effects, which real fleet optimizers layer on top
  of this same station-graph model.
- OSRM's public demo server and Nominatim's public instance are both free but
  rate-limited/best-effort; a production deployment would run self-hosted
  instances (or pay for e.g. Mapbox/Google) instead.
