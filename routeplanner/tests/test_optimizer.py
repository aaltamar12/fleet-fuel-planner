from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from routeplanner.services.exceptions import InfeasibleRouteError
from routeplanner.services.optimizer import plan_fuel_stops


def make_station(price, name="Station", lat=0.0, lon=0.0):
    return SimpleNamespace(retail_price=Decimal(str(price)), name=name, city="City", state="ST", latitude=lat, longitude=lon)


def candidate(mile, price, name="Station"):
    return {
        "station": make_station(price, name=name),
        "mile_marker": mile,
        "distance_from_route_miles": 1.0,
    }


# Defaults in every test unless overridden: 500 mi tank, 10 mpg, 60 mi
# reserve -> 440 mi of usable range per fill, $15 stop cost.
class PlanFuelStopsTests(SimpleTestCase):
    def test_no_stop_needed_within_usable_range(self):
        candidates = [candidate(200, 3.00, "A"), candidate(380, 2.50, "B")]
        result = plan_fuel_stops(candidates, total_distance_miles=400)

        self.assertEqual(result["stops"], [])
        self.assertEqual(result["total_fuel_cost_usd"], 0.0)
        self.assertEqual(result["total_gallons_needed"], 40.0)

    def test_reserve_forces_a_stop_before_nominal_range(self):
        # 460 mi fits the nominal 500 mi range but not the 440 mi usable
        # range: the plan must refuel rather than gamble the reserve.
        candidates = [candidate(250, 3.00, "A")]
        result = plan_fuel_stops(candidates, total_distance_miles=460)

        self.assertEqual(len(result["stops"]), 1)
        self.assertEqual(result["stops"][0]["gallons_purchased"], 2.0)

    def test_single_stop_buys_exact_hop_plus_reserve(self):
        candidates = [candidate(400, 3.00, "A")]
        result = plan_fuel_stops(candidates, total_distance_miles=800)

        self.assertEqual(len(result["stops"]), 1)
        stop = result["stops"][0]
        # Coming off the initial full tank, the purchase needed to end a hop
        # at mile 800 is (800 - 440 usable) / 10 mpg = 36 gallons.
        self.assertEqual(stop["gallons_purchased"], 36.0)
        self.assertEqual(stop["cost_usd"], 108.0)
        self.assertEqual(result["total_fuel_cost_usd"], 108.0)

    def test_prefers_cheaper_first_stop_and_skips_expensive_ones(self):
        candidates = [
            candidate(300, 4.00, "A"),
            candidate(430, 2.50, "B"),
            candidate(850, 5.00, "C"),
        ]
        result = plan_fuel_stops(candidates, total_distance_miles=1000)

        names = [s["station"].name for s in result["stops"]]
        self.assertEqual(names, ["B", "C"])

        b_stop, c_stop = result["stops"]
        self.assertEqual(b_stop["gallons_purchased"], 41.0)  # (850 - 440) / 10
        self.assertEqual(c_stop["gallons_purchased"], 15.0)  # (1000 - 850) / 10
        self.assertEqual(result["total_fuel_cost_usd"], 102.5 + 75.0)

    def test_no_micro_stop_to_chase_a_marginally_cheaper_price(self):
        # Both stations can single-handedly cover the trip; stopping at both
        # to save a few cents/gal costs an extra stop and is never chosen.
        candidates = [candidate(400, 2.80, "A"), candidate(430, 2.75, "B")]
        result = plan_fuel_stops(candidates, total_distance_miles=820)

        self.assertEqual(len(result["stops"]), 1)
        stop = result["stops"][0]
        self.assertEqual(stop["station"].name, "B")
        self.assertEqual(stop["gallons_purchased"], 38.0)

    def test_stop_cost_decides_whether_an_extra_cheap_stop_pays_off(self):
        # A and B are mandatory (no single station covers the 940 mi trip).
        # D would shave well under $15 of fuel cost: worth a third stop only
        # when stops are free.
        candidates = [
            candidate(400, 2.50, "A"),
            candidate(500, 3.00, "B"),
            candidate(870, 2.90, "D"),
        ]
        default_plan = plan_fuel_stops(candidates, total_distance_miles=940)
        free_stops_plan = plan_fuel_stops(candidates, total_distance_miles=940, stop_cost_usd=0)

        self.assertEqual([s["station"].name for s in default_plan["stops"]], ["A", "B"])
        self.assertEqual([s["station"].name for s in free_stops_plan["stops"]], ["A", "B", "D"])
        self.assertLess(
            free_stops_plan["total_fuel_cost_usd"], default_plan["total_fuel_cost_usd"]
        )

    def test_stop_penalty_is_not_billed_in_fuel_cost(self):
        candidates = [candidate(400, 3.00, "A")]
        result = plan_fuel_stops(candidates, total_distance_miles=800)

        stop = result["stops"][0]
        self.assertEqual(
            result["total_fuel_cost_usd"],
            round(stop["gallons_purchased"] * stop["price_per_gallon"], 2),
        )

    def test_infeasible_when_gap_exceeds_usable_range(self):
        candidates = [candidate(430, 3.00, "A")]  # 570 mi gap from A to the end
        with self.assertRaises(InfeasibleRouteError):
            plan_fuel_stops(candidates, total_distance_miles=1000)

    def test_multiple_stops_for_long_haul(self):
        candidates = [candidate(m, 3.00 + (m % 3) * 0.1, f"S{m}") for m in range(400, 2000, 400)]
        result = plan_fuel_stops(candidates, total_distance_miles=2000)

        self.assertGreaterEqual(len(result["stops"]), 3)
        for stop in result["stops"]:
            self.assertGreater(stop["gallons_purchased"], 0)
