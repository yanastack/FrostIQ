"""FrostIQ: offline decision-support module for the Arduino UNO Q.

This is a HACKATHON DEMONSTRATION, not a validated food-safety,
refrigeration-failure diagnostic, or inventory-release tool.

Deploy and RUN on the UNO Q's Linux processor. No external libraries,
cloud services, or laptop-side processing are required.

Input contract: Persons 2 and 3 supply a dictionary with
  predicted_event, temperature_c, warming_rate_c_per_min,
  excursion_minutes, risk_level.
Person 3 can override assumptions using the optional settings argument.
"""

from math import isfinite

# User-adjustable, purely illustrative assumptions. Not real industry rates.
DEFAULT_SETTINGS = {
    "temperature_limit_c": 5.0,
    "inventory_value_usd": 10000.0,
    "downtime_cost_per_hour_usd": 120.0,
    "loss_proxy_rate_per_degree_min": 0.0002,
    "inventory_hold_cost_per_hour_fraction": 0.001,
}

# Demonstration assumptions: the delay is how long until someone starts
# addressing the event. These are NOT validated operational response times.
ACTIONS = {
    "continue_monitoring": {
        "response_delay_min": 20.0,
        "downtime_min": 0.0,
        "inspection_cost_usd": 0.0,
        "inventory_held_fraction": 0.0,
        "hold_hours": 0.0,
    },
    "inspect_equipment": {
        "response_delay_min": 8.0,
        "downtime_min": 15.0,
        "inspection_cost_usd": 35.0,
        "inventory_held_fraction": 0.0,
        "hold_hours": 0.0,
    },
    "isolate_inventory": {
        "response_delay_min": 5.0,
        "downtime_min": 30.0,
        "inspection_cost_usd": 40.0,
        "inventory_held_fraction": 1.0,
        "hold_hours": 2.0,
    },
}

VALID_EVENTS = {
    "normal",
    "door_left_open",
    "loading_related_warming",
    "unexplained_warming",
    "possible_cooling_failure",  # Supported alias from the earlier team plan
    "unknown",
}
VALID_RISKS = {"normal", "low", "warning", "high", "critical"}
REQUIRED_EVENT_KEYS = (
    "predicted_event",
    "temperature_c",
    "warming_rate_c_per_min",
    "excursion_minutes",
    "risk_level",
)


def _finite_number(value, name, *, minimum=None):
    """Convert numerical input safely; reject NaN, infinity, and invalid values."""
    if isinstance(value, bool):
        raise ValueError(name + " must be a number, not a Boolean")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(name + " must be numeric") from None
    if not isfinite(number):
        raise ValueError(name + " must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(name + " must be >= " + str(minimum))
    return number


def _normalize_event(event):
    if not isinstance(event, dict):
        raise ValueError("event must be a dictionary")
    missing = [key for key in REQUIRED_EVENT_KEYS if key not in event]
    if missing:
        raise ValueError("Missing event fields: " + ", ".join(missing))

    predicted = str(event["predicted_event"]).strip().lower()
    risk = str(event["risk_level"]).strip().lower()
    if predicted not in VALID_EVENTS:
        # Unknown labels should not silently be classified as safe.
        predicted = "unknown"
    if risk not in VALID_RISKS:
        raise ValueError("risk_level must be one of: " + ", ".join(sorted(VALID_RISKS)))

    return {
        "predicted_event": predicted,
        "temperature_c": _finite_number(event["temperature_c"], "temperature_c"),
        "warming_rate_c_per_min": _finite_number(
            event["warming_rate_c_per_min"], "warming_rate_c_per_min"
        ),
        "excursion_minutes": _finite_number(
            event["excursion_minutes"], "excursion_minutes", minimum=0.0
        ),
        "risk_level": risk,
    }


def _normalize_settings(settings):
    merged = dict(DEFAULT_SETTINGS)
    if settings is not None:
        if not isinstance(settings, dict):
            raise ValueError("settings must be a dictionary")
        unknown = set(settings) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
        merged.update(settings)
    return {
        key: _finite_number(value, key, minimum=0.0)
        for key, value in merged.items()
    }


def _additional_exposure(temp_c, warming_rate, limit_c, delay_min):
    """Illustrative area above a configurable threshold in degree-minutes.

    Not a prediction of microbial growth, spoilage, compliance, or product safety.
    """
    exposure = 0.0
    elapsed = 0.0
    while elapsed < delay_min:
        step = min(1.0, delay_min - elapsed)
        midpoint_temp = temp_c + warming_rate * (elapsed + step / 2.0)
        exposure += max(0.0, midpoint_temp - limit_c) * step
        elapsed += step
    return exposure


def _operator_suggestion(event, settings):
    """Transparent DEMO escalation guidance, not automatic food disposition."""
    cause = event["predicted_event"]
    risk = event["risk_level"]
    temp = event["temperature_c"]

    if risk in ("high", "critical") or cause in (
        "unexplained_warming", "possible_cooling_failure", "unknown"
    ):
        return (
            "isolate_inventory",
            "Escalate for human review and appropriate inventory verification; "
            "the underlying cause or risk is not established.",
        )
    if cause == "door_left_open" or temp > settings["temperature_limit_c"]:
        return (
            "inspect_equipment",
            "Check door position and cooling equipment, then verify product "
            "temperatures with an appropriate method.",
        )
    if cause == "loading_related_warming":
        return (
            "inspect_equipment",
            "Review the recent loading event and temperature trend; "
            "confirm conditions before making inventory decisions.",
        )
    return (
        "continue_monitoring",
        "No immediate escalation suggested by the demo logic; "
        "continue observing and follow the site's established procedures.",
    )


def simulate_scenarios(event, settings=None):
    """Compare three modeled responses and return dashboard-ready JSON data.

    This intentionally does not choose the cheapest action automatically.
    Recommendations are conservative demonstration rules, not safety advice.
    """
    e = _normalize_event(event)
    config = _normalize_settings(settings)
    inventory_value = config["inventory_value_usd"]
    modeled_scenarios = []

    for name, action in ACTIONS.items():
        delay = action["response_delay_min"]
        exposure = _additional_exposure(
            e["temperature_c"],
            e["warming_rate_c_per_min"],
            config["temperature_limit_c"],
            delay,
        )
        exposure_cost = min(
            inventory_value,
            inventory_value * config["loss_proxy_rate_per_degree_min"] * exposure,
        )
        downtime_cost = (
            action["downtime_min"] / 60.0
        ) * config["downtime_cost_per_hour_usd"]
        hold_cost = (
            inventory_value
            * action["inventory_held_fraction"]
            * config["inventory_hold_cost_per_hour_fraction"]
            * action["hold_hours"]
        )
        total = exposure_cost + downtime_cost + hold_cost + action["inspection_cost_usd"]

        modeled_scenarios.append({
            "action": name,
            "response_delay_min": delay,
            "modeled_temperature_at_response_c": round(
                e["temperature_c"] + e["warming_rate_c_per_min"] * delay, 2
            ),
            "additional_exposure_proxy_degree_minutes": round(exposure, 2),
            "exposure_cost_proxy_usd": round(exposure_cost, 2),
            "downtime_cost_usd": round(downtime_cost, 2),
            "inspection_cost_usd": action["inspection_cost_usd"],
            "inventory_hold_cost_usd": round(hold_cost, 2),
            "total_modeled_cost_usd": round(total, 2),
        })

    recommendation, explanation = _operator_suggestion(e, config)
    return {
        "predicted_event": e["predicted_event"],
        "risk_level": e["risk_level"],
        "excursion_minutes": e["excursion_minutes"],
        "scenarios": modeled_scenarios,
        "recommended_action": recommendation,
        "recommendation_reason": explanation,
        "assumptions": config,
        "model_type": "illustrative_counterfactual_cost_proxy",
        "simulation_only": True,
        "disclaimer": (
            "Hypothetical scenario comparison only. Cost and thermal exposure "
            "proxies are not validated forecasts or food-safety measurements. "
            "Do not use for automatic equipment control, disposal, or product release."
        ),
    }


if __name__ == "__main__":
    # For an easy FIRST TEST executed only ON THE UNO Q:
    import json

    example = {
        "predicted_event": "door_left_open",
        "temperature_c": 9.0,
        "warming_rate_c_per_min": 0.08,
        "excursion_minutes": 20,
        "risk_level": "warning",
    }
    print(json.dumps(simulate_scenarios(example), indent=2))