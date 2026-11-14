"""Basic tests: RUN THIS FILE ON THE UNO Q, not on your Mac.

Commands on the Uno Q:
  python3 test_on_uno_q.py

No third-party packages or cloud calls. Tests do not train an AI model.
"""
from decision_engine import simulate_scenarios

BASE = {
    "predicted_event": "door_left_open",
    "temperature_c": 9.0,
    "warming_rate_c_per_min": 0.08,
    "excursion_minutes": 20,
    "risk_level": "warning",
}


def run_checks():
    result = simulate_scenarios(BASE)
    assert len(result["scenarios"]) == 3
    assert result["recommended_action"] == "inspect_equipment"
    assert result["simulation_only"] is True
    assert set(s["action"] for s in result["scenarios"]) == {
        "continue_monitoring", "inspect_equipment", "isolate_inventory"
    }
    assert all(s["total_modeled_cost_usd"] >= 0 for s in result["scenarios"])

    extreme = dict(BASE, predicted_event="unexplained_warming", risk_level="high")
    assert simulate_scenarios(extreme)["recommended_action"] == "isolate_inventory"

    normal = dict(BASE, predicted_event="normal", risk_level="normal", temperature_c=4)
    assert simulate_scenarios(normal)["recommended_action"] == "continue_monitoring"

    adjusted = simulate_scenarios(BASE, {"inventory_value_usd": 25000})
    assert adjusted["assumptions"]["inventory_value_usd"] == 25000

    try:
        simulate_scenarios({"predicted_event": "normal"})
        raise AssertionError("Expected incomplete event to raise ValueError")
    except ValueError:
        pass

    try:
        simulate_scenarios(BASE, {"inventory_value_usd": -1})
        raise AssertionError("Expected negative inventory value to raise ValueError")
    except ValueError:
        pass

    print("PASS: Person 4 decision engine checks completed on Uno Q")


if __name__ == "__main__":
    run_checks()
