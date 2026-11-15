"""Offline, board-rendered FrostIQ monitor."""
from datetime import datetime, timedelta, timezone
from html import escape
from math import isfinite
from pathlib import Path

from decision_adapter import decision_for_backend, settings_from_query
from decision_engine import ACTIONS
from storage import parse_time

ROOT = Path(__file__).parent


def esc(value):
    return escape(str(value))


def pretty(value, unit="", digits=1):
    return "Unavailable" if value is None else f"{value:.{digits}f}{unit}"


def page(backend):
    template = (ROOT / "monitor.html").read_text(encoding="utf-8")
    return (template.replace("{{room}}", esc(backend.args.room_id))
            .replace("{{source}}", esc(backend.args.source))
            .replace("{{simulation_hidden}}", "" if backend.args.source == "simulated" else "hidden")
            .replace("{{real_hidden}}", "" if backend.args.source == "real" else "hidden"))


def number(query, key, default, low, high):
    value = float(query.get(key, [default])[0])
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{key} must be between {low} and {high}")
    return value


def chart(samples, loads, start, end, gap, target):
    """Render temperature, open intervals and actual load markers on one UTC axis."""
    W, H = 900, 200
    values = [s["readings"]["temperature_c"] for s in samples]
    valid = [v for v in values if v is not None]
    if not valid:
        return "<p>Waiting for temperature readings in this window.</p>"
    low, high = min(valid + [target]) - .3, max(valid + [target]) + .3
    plot = []
    def x(t):
        return 48 + (W-60)*(t-start).total_seconds()/(end-start).total_seconds()
    def y(v):
        return 10 + (H-42)*(high-v)/(high-low)
    times = [parse_time(s["timestamp"]) for s in samples]
    exposure = coverage = 0.0
    for i, (t, value) in enumerate(zip(times, values)):
        if value is None:
            continue
        if i and values[i-1] is not None and 0 < (dt := (t-times[i-1]).total_seconds()) <= gap:
            previous = values[i-1]
            coverage += dt
            if previous > target and value > target:
                exposure += dt
            elif min(previous, value) <= target < max(previous, value):
                exposure += dt * (max(previous, value)-target)/abs(previous-value)
            xx = x(times[i-1])
            if samples[i-1]["derived"]["door_open"] is True:
                plot.append(f'<rect x="{xx:.2f}" y="8" width="{x(t)-xx:.2f}" height="160" fill="#d6eadd"/>')
            plot.append(f'<line x1="{xx:.2f}" y1="{y(previous):.2f}" x2="{x(t):.2f}" y2="{y(value):.2f}" stroke="#006654" stroke-width="2"/>')
        else:
            plot.append(f'<circle cx="{x(t):.2f}" cy="{y(value):.2f}" r="2" fill="#006654"/>')
    for load in loads:
        if load["actual_at"]:
            t = parse_time(load["actual_at"])
            if start <= t < end:
                plot.append(f'<path d="M{x(t):.1f} 8v160" stroke="#ad651d"><title>{esc(load["load_id"])}</title></path>')
    plot.append(f'<path d="M48 {y(target):.1f}h840" stroke="#a66330" stroke-dasharray="4 4"/>')
    for pos, label in [(16,high),(164,low)]:
        plot.append(f'<text x="4" y="{pos}">{label:.1f}°</text>')
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Temperature over time">'
            + ''.join(plot) + f'<text x="48" y="194">{start:%H:%M} UTC</text>'
            + f'<text x="816" y="194">{end:%H:%M} UTC</text></svg>'
            + f'<p>Time above {target:g} °C: <b>{exposure/60:.1f} min</b> across {coverage/60:.1f} observed minutes. '
              'Estimated between consecutive readings.</p>')


MODEL_MESSAGES = {
    "not_trained": "No model is loaded. Train one on the UNO Q (see DEPLOY_ON_UNO_Q.md) to enable cause classification.",
    "insufficient_data": "Waiting for complete inputs: door calibration and at least 10 seconds of temperature history.",
    "uncertain": "The model is not confident enough to name a cause (leaf class fraction below 0.7).",
}
ACTION_NAMES = {"continue_monitoring": "Continue monitoring", "inspect_equipment": "Inspect equipment",
                "isolate_inventory": "Isolate inventory for review"}


def render_model(pred, fresh):
    if not fresh:
        return "<p>Waiting for current readings.</p>"
    status = pred.get("status", "not_trained")
    if status != "predicted":
        return f"<b>{esc(status.replace('_', ' '))}</b><p>{esc(MODEL_MESSAGES.get(status, ''))}</p>"
    items = "".join(
        f"<li>{esc(e['feature'])} = {e['value']:.3g} {esc(e['comparison'])} {e['threshold']:.3g}</li>"
        for e in pred.get("evidence", []))
    return (f"<b>{esc(pred['event'].replace('_', ' '))}</b>"
            f"<p>Leaf class fraction {pred['score']:.2f} (not a calibrated probability). "
            "This is a possible explanation from an experimental on-board classifier, not a diagnosis.</p>"
            f"<small>Decision path</small><ul>{items}</ul>")


def render_decision(decision, settings):
    status = decision.get("status")
    if status != "ok":
        return f"<p>{esc(decision.get('reason', 'Unavailable.'))}</p>"
    i, result = decision["inputs"], decision["result"]
    rows = []
    for sc in result["scenarios"]:
        mark = " (suggested for human review)" if sc["action"] == result["recommended_action"] else ""
        plan = ACTIONS[sc["action"]]
        held = "none" if not plan["inventory_held_fraction"] else f"{plan['hold_hours']:g} h"
        rows.append(
            f"<tr><td><b>{esc(ACTION_NAMES.get(sc['action'], sc['action']))}</b>{mark}</td>"
            f"<td>{sc['response_delay_min']:g} min</td><td>{sc['modeled_temperature_at_response_c']:.1f} °C</td>"
            f"<td><b>{sc['additional_exposure_proxy_degree_minutes']:.1f}</b></td>"
            f"<td>{plan['downtime_min']:g} min</td><td>{held}</td></tr>")
    rate = "unknown" if i["warming_rate_c_per_min"] is None else f"{i['warming_rate_c_per_min']:+.3f} °C/min"
    excursion = "unknown" if i["excursion_minutes"] is None else f"at least {i['excursion_minutes']:.1f} min above target"
    basis = ("Cause from on-board model" if decision["basis"] == "model"
             else "Cause not classified (no model prediction)")
    source = "Simulated readings" if decision.get("data_source") == "simulated" else "Real sensor readings"
    notes = "".join(f"<li>{esc(n)}</li>" for n in decision["notes"])
    return (f"<p><b>{esc(ACTION_NAMES.get(result['recommended_action'], result['recommended_action']))}</b>: "
            f"{esc(result['recommendation_reason'])}</p>"
            f"<p><small>{esc(source)} · {esc(basis)} · temperature {i['temperature_c']:.2f} °C vs target "
            f"{settings['temperature_limit_c']:g} °C · trend {esc(rate)} · {esc(excursion)} · demo risk level "
            f"{esc(i['risk_level'])}</small></p>"
            '<div class="scroll"><table><tr><th>Response</th><th>Assumed delay</th><th>Modeled temp then</th>'
            '<th>Extra exposure (°C·min above target)</th><th>Equipment downtime</th><th>Inventory held</th></tr>'
            + "".join(rows) + "</table></div>"
            + (f"<ul>{notes}</ul>" if notes else "")
            + "<small>Illustrative comparison of hypothetical responses, not a food-safety determination. Exposure is a "
              "simple proxy: degrees above the target times minutes until someone responds. Delays and downtimes are demo "
              "assumptions. The risk level is a demo heuristic and the target is an operator assumption, not a "
              "regulatory limit. All figures are computed on the UNO Q.</small>")


def panel(b, query):
    minutes = number(query, 'minutes', 20, 1, 120)
    settings = settings_from_query(query)
    target = settings["temperature_limit_c"]
    end = datetime.now(timezone.utc)
    start = end-timedelta(minutes=minutes)
    history = b.history(10000, start, end)
    samples = history["samples"]
    loads = b.loads()
    latest = b.view()
    sample = latest[-1] if latest else {}
    fresh = bool(sample and sample.get('session_id') == b.session_id and
                 (end-parse_time(sample['timestamp'])).total_seconds() <= b.max_gap_s)
    r = sample.get("readings", {}) if fresh else {}
    d = sample.get("derived", {}) if fresh else {}
    pred = sample.get("prediction", {}) if fresh else {}
    door = {True:"Open", False:"Closed", None:"Unavailable"}[d.get("door_open")]
    status = "Receiving readings" if fresh else "Waiting for current readings"
    calibration = ""
    if b.args.source == "real" and b.detector is None and b.args.door_open_above_cm is None and d.get("door_open") is None:
        calibration = f"<p>Hold door closed for calibration · {len(b.calibration)}/15 valid distance readings</p>"
    cards = [("Temperature",pretty(r.get("temperature_c")," °C",2)),("Door",door),
             ("Temperature trend",pretty(d.get("temperature_rate_c_per_min")," °C/min")),
             ("Motion",{True:"Detected",False:"None detected",None:"Unavailable"}[r.get("motion_detected")])]
    tiles = ''.join(f'<article><small>{name}</small><strong>{value}</strong></article>' for name,value in cards)
    decision = decision_for_backend(b, query)
    source_label = "Real sensors" if b.args.source == "real" else "SIMULATED data"
    model_label = {"ready": "model loaded"}.get(b.model.status, "model not trained")
    recording = ""
    if b.args.source == "real":
        recording = ("<p><small>" + (f"RECORDING · {esc(b.recording_label)}" if b.recording_active else "Not recording")
                     + "</small></p>")
    events = b.door_events(start,end,10000)
    openings = sum(e["event_type"] == "opened" for e in events["events"])
    arrivals = sum(bool(l["actual_at"] and start <= parse_time(l["actual_at"]) < end) for l in loads)
    def temperature_near(t):
        near = [row for row in samples if row["readings"]["temperature_c"] is not None
                and abs((parse_time(row["timestamp"])-t).total_seconds()) <= b.max_gap_s]
        if not near:
            return None
        row = min(near, key=lambda row: abs((parse_time(row["timestamp"])-t).total_seconds()))
        return row["readings"]["temperature_c"]

    rows = []
    for load in loads:
        arrival = parse_time(load["actual_at"]) if load["actual_at"] else None
        change = "—"
        if arrival:
            followup = arrival + timedelta(minutes=1)
            before = temperature_near(arrival)
            after = temperature_near(followup)
            if followup > end:
                change = "Pending"
            elif before is not None and after is not None:
                change = f"{after-before:+.2f} °C"
            else:
                change = "Insufficient readings"
        fields = [load[k] or "—" for k in ("load_id","item","scheduled_at","actual_at")]
        rows.append("<tr>"+"".join(f"<td>{esc(v)}</td>" for v in fields + [change])+"</tr>")
    rows = "".join(rows)
    return (f'<p class="stamp">{esc(status)} · {esc(source_label)} · {esc(model_label)} · Last sample {esc(sample.get("timestamp","—"))}</p>'
            + calibration + recording + f'<div class="tiles">{tiles}</div><section><h2>Temperature history</h2>'
            + f'<p>{minutes:g} minutes · {openings} observed openings · {arrivals} recorded arrivals</p>'
            + chart(samples,loads,start,end,b.max_gap_s,target)
            + '<small>Green shading: door open · Vertical markers: load arrivals · Dashed line: selected target</small>'
            + ('<p>History incomplete: shorten the window.</p>' if history['truncated'] or events['truncated'] else '')
            + f'</section><section><h2>Model event</h2>{render_model(pred, fresh)}</section>'
            + f'<section><h2>Response comparison (illustrative)</h2>{render_decision(decision, settings)}</section>'
            + '<section><h2>Load records</h2><div class="scroll"><table><tr><th>ID</th><th>Item</th><th>Scheduled (UTC)</th><th>Actual (UTC)</th><th>1-min change</th></tr>'
            + (rows or '<tr><td colspan="5">No loads recorded.</td></tr>') + f'</table></div><small>Change uses the nearest temperature within {b.max_gap_s:g} seconds of arrival and one minute later in this window.</small></section>')
