"""
One-time ETL script: geocode every unique (city, state) pair found in the fuel
prices CSV using Nominatim (OpenStreetMap), respecting the 1 req/sec usage
policy. Resumable: re-running skips pairs already present in the cache file.

Each truck stop's street address is a highway-exit description (e.g. "I-44,
EXIT 283 & US-69"), not a geocodable postal address, so stations are located
at their city centroid instead. If the city-level lookup fails, we fall back
to the state centroid and mark the pair as a fallback so the importer can
flag those stations as geocoding_failed=True (excluded from route matching,
kept in the DB for later correction) -- same pattern used for geocoding
failures in a prior production system.
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

CSV_PATH = "data/fuel_prices_us.csv"
CACHE_PATH = "data/city_geocode_cache.json"
USER_AGENT = "FleetFuelPlanner/1.0 (contact: alfonso.altamar@tesote.com)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
SLEEP_SECONDS = 1.1


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_cache(cache):
    tmp_path = CACHE_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    os.replace(tmp_path, CACHE_PATH)


def query_nominatim(params):
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


def geocode_pair(city, state):
    try:
        result = query_nominatim(
            {"city": city, "state": state, "country": "USA", "format": "json", "limit": 1}
        )
    except Exception as exc:
        print(f"  ERROR city lookup {city}, {state}: {exc}", file=sys.stderr)
        result = None

    if result:
        return {"lat": result[0], "lon": result[1], "status": "ok"}

    time.sleep(SLEEP_SECONDS)
    try:
        result = query_nominatim(
            {"state": state, "country": "USA", "format": "json", "limit": 1}
        )
    except Exception as exc:
        print(f"  ERROR state fallback {state}: {exc}", file=sys.stderr)
        result = None

    if result:
        return {"lat": result[0], "lon": result[1], "status": "failed_fallback_state"}

    return {"lat": None, "lon": None, "status": "failed"}


def main():
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        pairs = sorted({(row["City"].strip(), row["State"].strip()) for row in reader})

    cache = load_cache()
    total = len(pairs)
    done = sum(1 for c, s in pairs if f"{c}|{s}" in cache)
    print(f"{done}/{total} pairs already cached")

    for i, (city, state) in enumerate(pairs, start=1):
        key = f"{city}|{state}"
        if key in cache:
            continue

        entry = geocode_pair(city, state)
        cache[key] = entry

        if i % 25 == 0 or entry["status"] != "ok":
            save_cache(cache)

        status_note = "" if entry["status"] == "ok" else f" [{entry['status']}]"
        print(f"[{i}/{total}] {city}, {state}{status_note}")

        time.sleep(SLEEP_SECONDS)

    save_cache(cache)
    ok = sum(1 for v in cache.values() if v["status"] == "ok")
    fallback = sum(1 for v in cache.values() if v["status"] == "failed_fallback_state")
    failed = sum(1 for v in cache.values() if v["status"] == "failed")
    print(f"\nDone. ok={ok} fallback_state={fallback} failed={failed} total={len(cache)}")


if __name__ == "__main__":
    main()
