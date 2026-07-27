import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from stations.models import FuelStation

DEFAULT_CSV_PATH = Path(settings.BASE_DIR) / "data" / "fuel_prices_us.csv"
DEFAULT_CACHE_PATH = Path(settings.BASE_DIR) / "data" / "city_geocode_cache.json"


class Command(BaseCommand):
    help = (
        "Import fuel stations from the OPIS CSV, attaching city-centroid "
        "coordinates from the geocode cache built by scripts/geocode_cities.py. "
        "Replaces all existing FuelStation rows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH))
        parser.add_argument("--cache-path", default=str(DEFAULT_CACHE_PATH))

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"])
        cache_path = Path(options["cache_path"])

        with open(cache_path) as f:
            geocode_cache = json.load(f)

        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        stations = []
        ok = fallback = failed = 0

        for row in rows:
            city = row["City"].strip()
            state = row["State"].strip()
            key = f"{city}|{state}"
            geo = geocode_cache.get(key, {"lat": None, "lon": None, "status": FuelStation.GEOCODE_FAILED})

            status = geo["status"]
            if status == FuelStation.GEOCODE_OK:
                ok += 1
            elif status == FuelStation.GEOCODE_FALLBACK_STATE:
                fallback += 1
            else:
                failed += 1

            stations.append(
                FuelStation(
                    opis_truckstop_id=int(row["OPIS Truckstop ID"]),
                    name=row["Truckstop Name"].strip(),
                    address=row["Address"].strip(),
                    city=city,
                    state=state,
                    rack_id=row["Rack ID"].strip(),
                    retail_price=row["Retail Price"],
                    latitude=geo["lat"],
                    longitude=geo["lon"],
                    geocode_status=status,
                )
            )

        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(stations, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"Imported {len(stations)} stations"))
        self.stdout.write(f"  city-level match: {ok}")
        self.stdout.write(f"  state-centroid fallback (geocoding_failed=True): {fallback}")
        self.stdout.write(f"  no match at all (geocoding_failed=True): {failed}")
