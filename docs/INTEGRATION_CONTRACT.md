# FrostIQ — Person 4 integration contract

## Person 2: send your event class using one of these exact strings

- `normal`
- `door_left_open`
- `loading_related_warming`
- `unexplained_warming`

We also accept `possible_cooling_failure` as an alias and `unknown` as a fallback. **These are candidate interpretations, not confirmed root causes.**

## Person 3: build the input payload (ALL computed on the UNO Q)

```json
{
  "predicted_event": "door_left_open",
  "temperature_c": 9.0,
  "warming_rate_c_per_min": 0.08,
  "excursion_minutes": 20,
  "risk_level": "warning"
}
```

`risk_level` must be one of `normal`, `low`, `warning`, `high`, `critical`. `excursion_minutes` must be nonnegative. `warming_rate_c_per_min` can be negative while cooling. For the MVP, compute these measurements on the board; use actual sensor data only once readings have been validated.

## Person 3: optional settings (all simulation on UNO Q)

```json
{
  "temperature_limit_c": 5.0,
  "inventory_value_usd": 10000,
  "downtime_cost_per_hour_usd": 120,
  "loss_proxy_rate_per_degree_min": 0.0002,
  "inventory_hold_cost_per_hour_fraction": 0.001
}
```

All these are **fictional demo assumptions**, not validated spoilage rates.

## Person 4 API

```python
from decision_engine import simulate_scenarios
result = simulate_scenarios(event, settings=optional_settings)
```

The result contains:
- `predicted_event`, `risk_level`, `excursion_minutes`
- `scenarios`: rows with `action`, `response_delay_min`, `modeled_temperature_at_response_c`, `additional_exposure_proxy_degree_minutes`, `exposure_cost_proxy_usd`, `downtime_cost_usd`, `inspection_cost_usd`, `inventory_hold_cost_usd`, `total_modeled_cost_usd`
- `recommended_action`, `recommendation_reason`, `assumptions`, `model_type`, `simulation_only`, `disclaimer`

Recommendations use transparent demo escalation logic, not merely lowest modeled cost. They do not automate food-safety decisions.

## Ownership

Person 1 owns Arduino IDE sensors. Person 2 owns on-board training/inference and event labels. Person 3 owns risk level, dashboard and editable assumptions. Person 4 owns decision_engine.py and scenario tests.

## Test on Uno Q only

```bash
cd person4_decision_intelligence
python3 test_on_uno_q.py
python3 run_on_uno_q.py sample_events/door_open.json
```
