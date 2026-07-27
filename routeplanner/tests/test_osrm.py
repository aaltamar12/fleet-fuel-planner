from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from routeplanner.services.osrm import get_route


def make_osrm_payload():
    return {
        "code": "Ok",
        "routes": [
            {
                "geometry": {"coordinates": [[-118.24, 34.05], [-118.0, 34.1], [-117.5, 34.2]]},
                "legs": [{"annotation": {"distance": [1000.0, 2000.0]}}],
                "distance": 3000.0,
                "duration": 200.0,
            }
        ],
    }


class GetRouteCachingTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _mock_response(self):
        response = MagicMock()
        response.json.return_value = make_osrm_payload()
        response.raise_for_status.return_value = None
        return response

    @patch("routeplanner.services.osrm.requests.get")
    def test_second_call_for_same_points_hits_cache_not_network(self, mock_get):
        mock_get.return_value = self._mock_response()

        first = get_route(34.05, -118.24, 34.2, -117.5)
        second = get_route(34.05, -118.24, 34.2, -117.5)

        self.assertEqual(first.total_distance_miles, second.total_distance_miles)
        mock_get.assert_called_once()

    @patch("routeplanner.services.osrm.requests.get")
    def test_different_points_both_hit_network(self, mock_get):
        mock_get.return_value = self._mock_response()

        get_route(34.05, -118.24, 34.2, -117.5)
        get_route(40.0, -100.0, 41.0, -101.0)

        self.assertEqual(mock_get.call_count, 2)
