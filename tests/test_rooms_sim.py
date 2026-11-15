import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rooms_sim as rs


class RoomsSimTests(unittest.TestCase):
    def setUp(self):
        self.sim = rs.simulate()
        self.findings = rs.analyze(self.sim)

    def test_deterministic(self):
        self.assertEqual(self.sim, rs.simulate())

    def test_exactly_one_problem_loading(self):
        self.assertEqual(len(self.findings), 1)
        load = self.findings[0]["loading"]
        self.assertEqual((load["room_id"], load["load_id"]), ("4417", "103"))
        self.assertGreater(load["temp_peak_c"], load["limit_c"])

    def test_cause_is_door(self):
        self.assertIn("door_left_open", self.findings[0]["causes"])

    def test_fixes_actually_work(self):
        f = self.findings[0]
        load, room = f["loading"], f["room"]
        for fix in f["fixes"]:
            if fix["kind"] == "limit_open_time":
                peak = load["temp_before_c"] + room["rise_per_open_min"] * fix["value"] \
                    + room["rise_per_opening"] * load["openings"]
                self.assertLessEqual(peak, load["limit_c"])
            if fix["kind"] == "change_setpoint":
                shift = fix["value"] - room["setpoint_c"]
                self.assertLessEqual(load["temp_peak_c"] + shift, load["limit_c"])
            if fix["kind"] == "move_item":
                other = rs.room_by_id(self.sim["rooms"], fix["value"])
                headroom, _ = rs.room_headroom(self.sim["rooms"], self.sim["loadings"], other, load["limit_c"])
                self.assertGreaterEqual(headroom, rs.MARGIN_C)

    def test_alert_wording(self):
        text = rs.alert_text(self.sim, self.findings[0])
        for part in ("Storage room 4417", "Monday", "#103", "frozen fish", "14 minutes", "9 times"):
            self.assertIn(part, text)

    def test_html_marked_simulated(self):
        self.assertIn("SIMULATED", rs.render_html(self.sim, self.findings))


if __name__ == "__main__":
    unittest.main()
