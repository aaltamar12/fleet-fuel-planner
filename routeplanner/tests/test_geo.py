from django.test import SimpleTestCase

from routeplanner.services.geo import haversine_miles, point_segment_distance_miles, simplify_polyline


class HaversineTests(SimpleTestCase):
    def test_known_distance_nyc_to_la(self):
        # NYC (40.7128, -74.0060) to LA (34.0522, -118.2437) is ~2,445 miles great-circle.
        dist = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(dist, 2445, delta=15)

    def test_zero_distance(self):
        self.assertAlmostEqual(haversine_miles(40.0, -90.0, 40.0, -90.0), 0.0, places=6)


class PointSegmentDistanceTests(SimpleTestCase):
    def test_point_on_segment_is_zero(self):
        # Midpoint of a straight segment along the equator.
        dist, t = point_segment_distance_miles(0.0, 5.0, 0.0, 0.0, 0.0, 10.0)
        self.assertAlmostEqual(dist, 0.0, delta=0.5)
        self.assertAlmostEqual(t, 0.5, delta=0.05)

    def test_point_off_segment_has_positive_distance(self):
        dist, t = point_segment_distance_miles(1.0, 5.0, 0.0, 0.0, 0.0, 10.0)
        self.assertGreater(dist, 0)
        self.assertGreaterEqual(t, 0.0)
        self.assertLessEqual(t, 1.0)

    def test_degenerate_segment(self):
        dist, t = point_segment_distance_miles(1.0, 1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertGreater(dist, 0)


class SimplifyPolylineTests(SimpleTestCase):
    def test_short_list_unchanged(self):
        points = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        self.assertEqual(simplify_polyline(points, max_points=10), points)

    def test_long_straight_line_reduces_to_endpoints_ish(self):
        points = [(0.0, i * 0.01) for i in range(1000)]
        simplified = simplify_polyline(points, max_points=50)
        self.assertLessEqual(len(simplified), 50)
        self.assertEqual(simplified[0], points[0])
        self.assertEqual(simplified[-1], points[-1])

    def test_preserves_sharp_corner(self):
        # An L-shaped path: the corner point must survive simplification.
        points = [(0.0, i * 0.01) for i in range(200)] + [(i * 0.01, 2.0) for i in range(200)]
        simplified = simplify_polyline(points, max_points=10)
        corner = (0.0, 2.0)
        self.assertIn(corner, simplified)
