from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from routeplanner.services.exceptions import GeocodingError
from routeplanner.services.geocoding import geocode_location


class GeocodeLocationCachingTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _mock_response(self, lat="34.05", lon="-118.24"):
        response = MagicMock()
        response.json.return_value = [{"lat": lat, "lon": lon}]
        response.raise_for_status.return_value = None
        return response

    @patch("routeplanner.services.geocoding.requests.get")
    def test_second_call_for_same_place_hits_cache_not_network(self, mock_get):
        mock_get.return_value = self._mock_response()

        first = geocode_location("Los Angeles, CA")
        second = geocode_location("Los Angeles, CA")

        self.assertEqual(first, (34.05, -118.24))
        self.assertEqual(second, first)
        mock_get.assert_called_once()

    @patch("routeplanner.services.geocoding.requests.get")
    def test_cache_key_is_case_and_whitespace_insensitive(self, mock_get):
        mock_get.return_value = self._mock_response()

        geocode_location("Los Angeles, CA")
        geocode_location("  los angeles, ca  ")

        mock_get.assert_called_once()

    @patch("routeplanner.services.geocoding.requests.get")
    def test_different_places_both_hit_network(self, mock_get):
        mock_get.return_value = self._mock_response()

        geocode_location("Los Angeles, CA")
        geocode_location("New York, NY")

        self.assertEqual(mock_get.call_count, 2)

    @patch("routeplanner.services.geocoding.requests.get")
    def test_failed_lookup_is_not_cached(self, mock_get):
        empty_response = MagicMock()
        empty_response.json.return_value = []
        empty_response.raise_for_status.return_value = None
        mock_get.return_value = empty_response

        with self.assertRaises(GeocodingError):
            geocode_location("Nowhereville")
        with self.assertRaises(GeocodingError):
            geocode_location("Nowhereville")

        self.assertEqual(mock_get.call_count, 2)
