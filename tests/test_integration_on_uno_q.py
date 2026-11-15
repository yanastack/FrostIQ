"""Integration checks for decision_adapter. RUN ON THE UNO Q (not a laptop).

    cd FrostIQ && python3 -m unittest tests.test_integration_on_uno_q -v

Standard library only. Does not start the server, touch sensors, or train anything.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_adapter import build_decision, observed_excursion_minutes, settings_from_query  # noqa: E402

T0 = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)


def stamp(seconds):
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def sample(temp=9.0, rate=0.08, status="not_trained", event=None, seconds=0, source="real"):
    return {
        "source": source,
        "timestamp": stamp(seconds),
        "readings": {"temperature_c": temp, "distance_cm": 5.0, "motion_detected": None},
        "derived": {"temperature_rate_c_per_min": rate, "door_open": False, "door_open_duration_s": 0.0},
        "prediction": {"status": status, "event": event, "score": None, "evidence": []},
    }


SETTINGS = settings_from_query({})  # engine defaults, target 5 C


class AdapterTests(unittest.TestCase):
    def test_no_current_reading_is_waiting(self):
        self.assertEqual(build_decision(None, [], SETTINGS, 5)["status"], "waiting")

    def test_missing_temperature_is_unavailable(self):
        self.assertEqual(build_decision(sample(temp=None), [], SETTINGS, 5)["status"], "unavailable")

    def test_untrained_below_target_does_not_escalate(self):
        s = sample(temp=4.0)
        d = build_decision(s, [s], SETTINGS, 5)
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["basis"], "no_classification")
        self.assertEqual(d["result"]["recommended_action"], "continue_monitoring")

    def test_untrained_above_target_is_conservative_and_labeled(self):
        s = sample(temp=9.0)
        d = build_decision(s, [s], SETTINGS, 5)
        self.assertEqual(d["basis"], "no_classification")
        self.assertEqual(d["result"]["recommended_action"], "isolate_inventory")
        self.assertTrue(any("not classified" in n for n in d["notes"]))

    def test_loading_class_name_is_mapped(self):
        s = sample(status="predicted", event="loading_warming")
        d = build_decision(s, [s], SETTINGS, 5)
        self.assertEqual(d["basis"], "model")
        self.assertEqual(d["inputs"]["engine_event"], "loading_related_warming")

    def test_uncertain_model_is_not_used(self):
        s = sample(status="uncertain", event=None)
        self.assertEqual(build_decision(s, [s], SETTINGS, 5)["basis"], "no_classification")

    def test_unknown_rate_is_flagged_not_hidden(self):
        s = sample(rate=None)
        d = build_decision(s, [s], SETTINGS, 5)
        self.assertIsNone(d["inputs"]["warming_rate_c_per_min"])
        self.assertTrue(any("Warming rate" in n for n in d["notes"]))

    def test_excursion_minutes_stop_at_gaps(self):
        old = [sample(temp=9.0, seconds=s) for s in (0, 10, 20)]
        recent = [sample(temp=9.0, seconds=s) for s in (100, 110, 120)]  # 80 s gap before these
        self.assertAlmostEqual(observed_excursion_minutes(old + recent, 5.0, 15.0), 20 / 60)

    def test_excursion_is_zero_when_newest_is_at_target(self):
        rows = [sample(temp=9.0, seconds=0), sample(temp=5.0, seconds=10)]
        self.assertEqual(observed_excursion_minutes(rows, 5.0, 5.0), 0.0)

    def test_bad_settings_are_rejected_and_freezer_target_allowed(self):
        with self.assertRaises(ValueError):
            settings_from_query({"target": ["abc"]})
        with self.assertRaises(ValueError):
            settings_from_query({"inventory": ["-1"]})
        s = sample(temp=-10.0)
        d = build_decision(s, [s], settings_from_query({"target": ["-18"]}), 5)
        self.assertEqual(d["status"], "ok")


if __name__ == "__main__":
    unittest.main()
