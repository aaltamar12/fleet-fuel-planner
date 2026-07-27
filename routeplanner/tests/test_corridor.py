from django.test import TestCase

from routeplanner.services.corridor import find_candidate_stations
from stations.models import FuelStation

from .helpers import build_straight_route


class FindCandidateStationsTests(TestCase):
    def setUp(self):
        self.coordinates, self.cumulative_miles = build_straight_route(0.0, 0.0, 10.0)

        self.on_route = FuelStation.objects.create(
            opis_truckstop_id=1, name="On Route", city="A", state="TX",
            retail_price="3.00", latitude=0.0, longitude=5.0,
            geocode_status=FuelStation.GEOCODE_OK,
        )
        self.off_route = FuelStation.objects.create(
            opis_truckstop_id=2, name="Off Route", city="B", state="TX",
            retail_price="3.00", latitude=5.0, longitude=5.0,
            geocode_status=FuelStation.GEOCODE_OK,
        )
        self.failed_geocode_but_close = FuelStation.objects.create(
            opis_truckstop_id=3, name="Bad Geocode", city="C", state="TX",
            retail_price="3.00", latitude=0.0, longitude=6.0,
            geocode_status=FuelStation.GEOCODE_FALLBACK_STATE,
        )
        self.also_on_route = FuelStation.objects.create(
            opis_truckstop_id=4, name="Earlier On Route", city="D", state="TX",
            retail_price="2.80", latitude=0.001, longitude=2.0,
            geocode_status=FuelStation.GEOCODE_OK,
        )

    def test_excludes_stations_far_from_route(self):
        candidates = find_candidate_stations(self.coordinates, self.cumulative_miles, buffer_miles=25)
        names = {c["station"].name for c in candidates}
        self.assertNotIn("Off Route", names)

    def test_excludes_geocoding_failed_stations(self):
        candidates = find_candidate_stations(self.coordinates, self.cumulative_miles, buffer_miles=25)
        names = {c["station"].name for c in candidates}
        self.assertNotIn("Bad Geocode", names)

    def test_includes_and_orders_on_route_stations_by_mile_marker(self):
        candidates = find_candidate_stations(self.coordinates, self.cumulative_miles, buffer_miles=25)
        names_in_order = [c["station"].name for c in candidates]
        self.assertEqual(names_in_order, ["Earlier On Route", "On Route"])

    def test_mile_marker_roughly_matches_expected_position(self):
        candidates = find_candidate_stations(self.coordinates, self.cumulative_miles, buffer_miles=25)
        on_route = next(c for c in candidates if c["station"].name == "On Route")
        # 5 degrees of the 10-degree route -> should land near the midpoint mileage.
        expected_mile = self.cumulative_miles[-1] / 2
        self.assertAlmostEqual(on_route["mile_marker"], expected_mile, delta=15)
