import csv
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from stations.models import FuelStation


class ImportStationsCommandTests(TestCase):
    def test_import_marks_geocoding_failed_appropriately(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fuel.csv"
            cache_path = Path(tmp) / "cache.json"

            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Rack ID", "Retail Price"]
                )
                writer.writerow(["1", "Good Stop", "I-10, EXIT 1", "Ok City", "TX", "100", "3.10"])
                writer.writerow(["2", "State Fallback Stop", "I-10, EXIT 2", "Fallback City", "TX", "100", "3.20"])
                writer.writerow(["3", "No Match Stop", "I-10, EXIT 3", "Nowhere City", "TX", "100", "3.30"])

            with open(cache_path, "w") as f:
                json.dump(
                    {
                        "Ok City|TX": {"lat": 30.0, "lon": -97.0, "status": "ok"},
                        "Fallback City|TX": {"lat": 31.0, "lon": -100.0, "status": "failed_fallback_state"},
                        "Nowhere City|TX": {"lat": None, "lon": None, "status": "failed"},
                    },
                    f,
                )

            call_command("import_stations", csv_path=str(csv_path), cache_path=str(cache_path))

        self.assertEqual(FuelStation.objects.count(), 3)

        good = FuelStation.objects.get(opis_truckstop_id=1)
        self.assertFalse(good.geocoding_failed)
        self.assertEqual(good.latitude, 30.0)

        fallback = FuelStation.objects.get(opis_truckstop_id=2)
        self.assertTrue(fallback.geocoding_failed)
        self.assertEqual(fallback.geocode_status, FuelStation.GEOCODE_FALLBACK_STATE)

        no_match = FuelStation.objects.get(opis_truckstop_id=3)
        self.assertTrue(no_match.geocoding_failed)
        self.assertIsNone(no_match.latitude)

    def test_reimport_replaces_existing_rows(self):
        FuelStation.objects.create(
            opis_truckstop_id=999, name="Stale", city="X", state="TX", retail_price="1.00"
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fuel.csv"
            cache_path = Path(tmp) / "cache.json"
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Rack ID", "Retail Price"]
                )
                writer.writerow(["1", "Fresh Stop", "I-10, EXIT 1", "Ok City", "TX", "100", "3.10"])
            with open(cache_path, "w") as f:
                json.dump({"Ok City|TX": {"lat": 30.0, "lon": -97.0, "status": "ok"}}, f)

            call_command("import_stations", csv_path=str(csv_path), cache_path=str(cache_path))

        self.assertEqual(FuelStation.objects.count(), 1)
        self.assertFalse(FuelStation.objects.filter(opis_truckstop_id=999).exists())
