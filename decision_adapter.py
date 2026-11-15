"""Board-side adapter between FrostIQ's nested schema-1.1 samples and
Person 4's decision_engine.simulate_scenarios().

Runs on the UNO Q (standard library only). It never invents data:
  * no current reading        -> status "waiting"
  * temperature unavailable   -> status "unavailable"
  * model not trained / uncertain / insufficient data -> the cause is passed to
    the engine as "unknown" and the result is labeled as NOT a model
    classification.
Costs are illustrative proxies from decision_engine; nothing here is a
food-safety, spoilage, or product-release determination.
"""

from datetime import datetime, timedelta, timezone
from math import isfinite

from decision_engine import DEFAULT_SETTINGS, simulate_scenarios
from storage import parse_time

# The original model's class names -> the decision engine's names.
MODEL_TO_ENGINE = {
    "normal": "normal",
    "door_left_open": "door_left_open",
    "loading_warming": "loading_related_warming",
    "possible_cooling_failure": "possible_cooling_failure",
}

# query-string key -> (engine setting, low, high)
QUERY_SETTINGS = {
    "target": ("temperature_limit_c", -80.0, 100.0),
    "inventory": ("inventory_value_usd", 0.0, 1e9),
    "downtime": ("downtime_cost_per_hour_usd", 0.0, 1e8),
    "loss_rate": ("loss_proxy_rate_per_degree_min", 0.0, 1.0),
    "hold": ("inventory_hold_cost_per_hour_fraction", 0.0, 1.0),
}

EXCURSION_LOOKBACK_MIN = 60


def settings_from_query(query):
    """Parse operator assumptions; defaults come from decision_engine."""
    settings = {}
    for key, (name, low, high) in QUERY_SETTINGS.items():
        raw = query.get(key, [DEFAULT_SETTINGS[name]])[0]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(key + " must be a number") from None
        if not isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low:g} and {high:g}")
        settings[name] = value
    return settings


def observed_excursion_minutes(samples, limit_c, max_gap_s):
    """Continuous observed minutes above the target, ending at the newest sample.

    Returns None if the newest temperature is unknown, 0.0 if it is at or below
    the target. It is a lower bound: it stops at data gaps and at the start of
    the loaded history. It is NOT the same thing as door-open time.
    """
    if not samples:
        return None
    newest = samples[-1]["readings"]["temperature_c"]
    if newest is None:
        return None
    if newest <= limit_c:
        return 0.0
    run = 0.0
    later = None
    for sample in reversed(samples):
        temp = sample["readings"]["temperature_c"]
        if temp is None or temp <= limit_c:
            break
        moment = parse_time(sample["timestamp"])
        if later is not None:
            gap = (later - moment).total_seconds()
            if gap > max_gap_s:
                break
            run += gap
        later = moment
    return run / 60.0


def demo_risk_level(temp_c, limit_c, excursion_min):
    """Transparent DEMO heuristic for escalation wording (not a safety rule)."""
    excess = temp_c - limit_c
    if excess <= 0:
        return "normal"
    minutes = excursion_min or 0.0
    if excess >= 5.0 or minutes >= 30.0:
        return "high"
    if excess >= 2.0 or minutes >= 10.0:
        return "warning"
    return "low"


def build_decision(sample, samples, settings, max_gap_s):
    """Return a dashboard/API-ready dict. `sample` must be a FRESH sample or None."""
    if not sample:
        return {"status": "waiting", "reason": "No current readings, so no scenario comparison is shown."}
    temp = sample["readings"].get("temperature_c")
    if temp is None:
        return {"status": "unavailable", "reason": "Temperature sensor unavailable, so scenarios cannot be modeled."}

    limit = settings["temperature_limit_c"]
    rate = sample["derived"].get("temperature_rate_c_per_min")
    rate_known = rate is not None
    prediction = sample.get("prediction") or {}
    model_status = prediction.get("status", "not_trained")
    mapped = MODEL_TO_ENGINE.get(prediction.get("event")) if model_status == "predicted" else None
    from_model = mapped is not None
    excursion = observed_excursion_minutes(samples, limit, max_gap_s)
    risk = demo_risk_level(temp, limit, excursion)

    event = {
        "predicted_event": mapped or "unknown",
        "temperature_c": temp,
        "warming_rate_c_per_min": rate if rate_known else 0.0,
        "excursion_minutes": excursion if excursion is not None else 0.0,
        "risk_level": risk,
    }
    try:
        result = simulate_scenarios(event, settings)
    except ValueError as error:
        return {"status": "error", "reason": "Decision engine rejected the input: " + str(error)}

    notes = []
    if not from_model:
        notes.append(f"Cause not classified (model status: {model_status}); the engine received 'unknown'.")
        if temp <= limit:
            result["recommended_action"] = "continue_monitoring"
            result["recommendation_reason"] = (
                "Temperature is at or below the selected target and no cause classification is available. "
                "Continue observing and follow the site's established procedures."
            )
    if not rate_known:
        notes.append("Warming rate not yet available; modeled as steady (0 °C/min), so exposure may be understated.")
    if excursion is None:
        notes.append("Excursion duration unknown.")
    return {
        "status": "ok",
        "data_source": sample.get("source"),
        "basis": "model" if from_model else "no_classification",
        "model_status": model_status,
        "inputs": {
            "engine_event": event["predicted_event"],
            "temperature_c": temp,
            "warming_rate_c_per_min": rate if rate_known else None,
            "excursion_minutes": excursion,
            "excursion_is_lower_bound": True,
            "risk_level": risk,
            "risk_basis": "demo heuristic from selected target, degrees above it, and observed minutes above it",
        },
        "notes": notes,
        "result": result,
    }


def decision_for_backend(backend, query):
    """Compute the comparison from the backend's stored, board-local data."""
    settings = settings_from_query(query)
    end = datetime.now(timezone.utc)
    history = backend.history(10000, end - timedelta(minutes=EXCURSION_LOOKBACK_MIN), end)["samples"]
    latest = backend.view()
    sample = latest[-1] if latest else None
    fresh = bool(
        sample
        and sample.get("session_id") == backend.session_id
        and (end - parse_time(sample["timestamp"])).total_seconds() <= backend.max_gap_s
    )
    return build_decision(sample if fresh else None, history, settings, backend.max_gap_s)
