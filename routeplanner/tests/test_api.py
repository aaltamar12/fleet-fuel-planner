from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from routeplanner.services.exceptions import GeocodingError
from routeplanner.services.osrm import RouteResult
from stations.models import FuelStation

from .helpers import build_straight_route


def make_fake_route(lat, lon_start, lon_end, num_points=21, total_miles=600.0):
    coordinates, cumulative = build_straight_route(lat, lon_start, lon_end, num_points, total_miles=total_miles)
    return RouteResult(
        coordinates=coordinates,
        cumulative_miles=cumulative,
        total_distance_miles=total_miles,
        total_duration_seconds=total_miles / 60 * 3600,
    )


class RoutePlanViewTests(APITestCase):
    def setUp(self):
        self.url = reverse("route-plan")
        FuelStation.objects.create(
            opis_truckstop_id=1, name="Cheap Stop", city="Midway", state="TX",
            retail_price="2.75", latitude=0.0, longitude=5.0,
            geocode_status=FuelStation.GEOCODE_OK,
        )

    @patch("routeplanner.services.planner.osrm.get_route")
    @patch("routeplanner.services.planner.geocoding.geocode_location")
    def test_route_by_place_name(self, mock_geocode, mock_get_route):
        mock_geocode.side_effect = [(0.0, 0.0), (0.0, 10.0)]
        mock_get_route.return_value = make_fake_route(0.0, 0.0, 10.0)

        response = self.client.post(self.url, {"start": "Origin, TX", "end": "Destination, TX"}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_distance_miles"], 600.0)
        self.assertEqual(body["total_gallons_needed"], 60.0)
        self.assertGreaterEqual(len(body["fuel_stops"]), 1)
        self.assertIn("map_url", body)
        self.assertIn(reverse("route-map-preview"), body["map_url"])
        self.assertIn("start=", body["map_url"])
        self.assertEqual(mock_geocode.call_count, 2)

    @patch("routeplanner.services.planner.osrm.get_route")
    @patch("routeplanner.services.planner.geocoding.geocode_location")
    def test_explicit_coordinates_skip_geocoding(self, mock_geocode, mock_get_route):
        mock_get_route.return_value = make_fake_route(0.0, 0.0, 10.0)

        response = self.client.post(
            self.url,
            {
                "start_latitude": 0.0, "start_longitude": 0.0,
                "end_latitude": 0.0, "end_longitude": 10.0,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        mock_geocode.assert_not_called()

    def test_missing_start_and_end_is_400(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_invalid_strategy_is_400(self):
        response = self.client.post(
            self.url,
            {"start": "Origin, TX", "end": "Destination, TX", "strategy": "teleport"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("routeplanner.services.planner.osrm.get_route")
    @patch("routeplanner.services.planner.geocoding.geocode_location")
    def test_strategy_is_echoed_and_carried_into_the_map_url(self, mock_geocode, mock_get_route):
        mock_geocode.side_effect = [(0.0, 0.0), (0.0, 10.0)]
        mock_get_route.return_value = make_fake_route(0.0, 0.0, 10.0)

        response = self.client.post(
            self.url,
            {"start": "Origin, TX", "end": "Destination, TX", "strategy": "fewest_stops"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["strategy"], "fewest_stops")
        self.assertIn("strategy=fewest_stops", body["map_url"])

    @patch("routeplanner.services.planner.geocoding.geocode_location")
    def test_geocoding_failure_is_422(self, mock_geocode):
        mock_geocode.side_effect = GeocodingError("Could not find a US location matching 'Nowhereville'")

        response = self.client.post(self.url, {"start": "Nowhereville", "end": "Destination, TX"}, format="json")

        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())


class RouteMapPreviewViewTests(APITestCase):
    def setUp(self):
        self.url = reverse("route-map-preview")
        FuelStation.objects.create(
            opis_truckstop_id=1, name="Cheap Stop", city="Midway", state="TX",
            retail_price="2.75", latitude=0.0, longitude=5.0,
            geocode_status=FuelStation.GEOCODE_OK,
        )

    @patch("routeplanner.services.planner.osrm.get_route")
    @patch("routeplanner.services.planner.geocoding.geocode_location")
    def test_renders_map_page(self, mock_geocode, mock_get_route):
        mock_geocode.side_effect = [(0.0, 0.0), (0.0, 10.0)]
        mock_get_route.return_value = make_fake_route(0.0, 0.0, 10.0)

        response = self.client.get(self.url, {"start": "Origin, TX", "end": "Destination, TX"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        content = response.content.decode()
        self.assertIn("leaflet", content.lower())
        self.assertIn("Cheap Stop", content)
        # Must stay embeddable in an <iframe> -- that's the point of a
        # shareable map_url -- unlike Django's clickjacking-safe default.
        self.assertNotIn("X-Frame-Options", response)

    def test_missing_params_is_400(self):
        response = self.client.get(self.url, {})
        self.assertEqual(response.status_code, 400)

    @patch("routeplanner.services.planner.geocoding.geocode_location")
    def test_geocoding_failure_renders_error_page(self, mock_geocode):
        mock_geocode.side_effect = GeocodingError("Could not find a US location matching 'Nowhereville'")

        response = self.client.get(self.url, {"start": "Nowhereville", "end": "Destination, TX"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("Nowhereville", response.content.decode())
