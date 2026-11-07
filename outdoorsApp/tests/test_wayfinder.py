"""Behavior checks for the local trip-planning prototype."""

import os
import unittest

# Test against the curated samples only, not whatever is in a local places cache.
os.environ["WAYFINDER_SAMPLE_ONLY"] = "1"

from outdoorsApp.outdoorsApp import State  # noqa: E402
from outdoorsApp.place_data import BY_ID, compute, date_error, saved_ids, trip_months


class TripPlanningTests(unittest.TestCase):
    def setUp(self):
        self.state = State(_reflex_internal_init=True)
        self.state.arrive = "2027-01-15"
        self.state.leave = "2027-01-18"

    def test_cross_month_scores_weight_each_day(self):
        months = trip_months("2027-01-31", "2027-02-02")
        self.assertEqual(months, [0, 1, 1])
        stats = compute(BY_ID["snowbird"], months, (40.7608, -111.891))
        self.assertEqual(stats.score, round((98 + 100 + 100) / 3))

    def test_invalid_dates_show_no_misleading_results(self):
        for arrive, leave in [("", "2027-01-01"), ("2027-02-30", "2027-03-01"),
                              ("2027-02-01", "2027-01-01"), ("2027-01-01", "2029-01-01")]:
            with self.subTest(arrive=arrive, leave=leave):
                self.state.arrive, self.state.leave = arrive, leave
                self.assertTrue(self.state.date_warning)
                self.assertEqual(self.state.results, [])
        self.assertEqual(date_error("2027-12-31", "2028-01-02"), "")

    def test_comparison_is_selected_only_and_survives_filters(self):
        self.state.toggle_place("zion")
        self.state.toggle_place("snowbird")
        self.state.toggle_filter("type:Ski Resort")
        self.assertEqual([p["id"] for p in self.state.comparison], ["zion", "snowbird"])
        self.state.toggle_place("zion")
        self.assertEqual([p["id"] for p in self.state.comparison], ["snowbird"])
        self.state.clear_comparison()
        self.assertEqual(self.state.comparison, [])

    def test_comparison_limit_and_unknown_ids(self):
        for place_id in ["zion", "arches", "snowbird", "bryce", "unknown"]:
            self.state.toggle_place(place_id)
        self.assertEqual(self.state.selected_places, ["zion", "arches", "snowbird"])
        self.state.toggle_place("arches")
        self.state.toggle_place("bryce")
        self.assertEqual(self.state.selected_places, ["zion", "snowbird", "bryce"])

    def test_favorites_round_trip_and_saved_filter(self):
        self.state.toggle_favorite("zion")
        self.state.toggle_favorite("snowbird")
        other = State(_reflex_internal_init=True)
        other.favorite_storage = self.state.favorite_storage
        other.toggle_filter("saved")
        self.assertEqual({p["id"] for p in other.results}, {"zion", "snowbird"})
        other.toggle_favorite("zion")
        self.assertEqual([p["id"] for p in other.results], ["snowbird"])
        self.assertEqual(saved_ids('["zion", "zion", "missing", null, {}]'), ["zion"])
        self.assertEqual(saved_ids("not json"), [])
        self.assertEqual(saved_ids('{"zion": true}'), [])

    def test_filters_combine_types_activities_and_access(self):
        for token in ["type:National Park", "type:State Park", "activity:Hiking", "access:wheelchair", "family"]:
            self.state.toggle_filter(token)
        self.assertGreater(len(self.state.results), 0)
        for view in self.state.results:
            place = BY_ID[view["id"]]
            self.assertIn(place["Type"], {"National Park", "State Park"})
            self.assertIn("Hiking", place["Activities"])
            self.assertTrue(place["Access"]["wheelchair"])
            self.assertTrue(place["FamilyFriendly"])

    def test_city_radius_and_sort_update_results(self):
        self.state.resolve_location("Moab, UT")
        self.state.set_radius("25")
        self.state.set_sort_by("drive")
        self.assertIn("arches", [p["id"] for p in self.state.results])
        distances = [self.state._stats(BY_ID[p["id"]]).miles for p in self.state.results]
        self.assertTrue(all(d <= 25 for d in distances))
        self.assertEqual(distances, sorted(distances))
        self.state.resolve_location("Unknown city")
        self.assertEqual(self.state.origin_name, "Moab, UT")
        self.assertIn("Still using", self.state.location_note)

    def test_units_update_details_and_comparison(self):
        self.state.open_details("zion")
        self.state.toggle_place("zion")
        self.assertEqual(self.state.detail["weather"], "54°F")
        self.state.set_units(True)
        self.assertEqual(self.state.detail["weather"], "12°C")
        self.assertIn("km", self.state.comparison[0]["drive_full"])
        self.assertEqual(self.state.detail["elevation"], "1,219 m")

    def test_packing_and_seasonal_scores_change_with_dates(self):
        self.state.open_details("snowbird")
        winter_score = int(self.state.detail["score"])
        self.assertIn("Ski goggles and a waterproof jacket", self.state.detail_packing)
        self.state.arrive, self.state.leave = "2027-07-15", "2027-07-18"
        self.assertLess(int(self.state.detail["score"]), winter_score)
        self.assertNotIn("Ski goggles and a waterproof jacket", self.state.detail_packing)

    def test_clear_filters_keeps_favorites_and_comparison(self):
        self.state.toggle_favorite("zion")
        self.state.toggle_place("zion")
        self.state.toggle_filter("saved")
        self.state.set_radius("25")
        self.state.set_min_rating("4.7")
        self.state.set_max_drive("1")
        self.state.clear_filters()
        self.assertEqual(self.state.filter_count, 0)
        self.assertEqual(len(self.state.results), 20)
        self.assertEqual(self.state.favorites, ["zion"])
        self.assertEqual(self.state.selected_places, ["zion"])

    def test_geolocation_failure_retains_current_origin(self):
        self.state.receive_location({"error": "Location permission denied"})
        self.assertEqual(self.state.origin_name, "Salt Lake City, UT")
        self.assertFalse(self.state.locating)
        self.state.receive_location({"lat": 38.5733, "lon": -109.5498})
        self.assertEqual(self.state.origin_name, "Your location")
        self.assertEqual(self.state.origin_lat, 38.5733)

    def test_city_suggestions_can_be_selected(self):
        self.state.set_location_text("mo")
        self.assertEqual(self.state.location_suggestions, ["Moab, UT"])
        self.assertTrue(self.state.location_suggestions_open)
        self.state.choose_location_suggestion("Moab, UT")
        self.assertEqual(self.state.origin_name, "Moab, UT")
        self.assertFalse(self.state.location_suggestions_open)


if __name__ == "__main__":
    unittest.main()
