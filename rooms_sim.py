"""FrostIQ multi-room what-if simulator. SIMULATED DATA ONLY. Run on the UNO Q.

Three invented storage rooms, a Monday loading schedule, per-item temperature
limits and door activity. Exactly one loading causes a problem. A rule-based
analysis (no trained model, no network) names the likely cause, writes an alert,
and lists the fixes that the simulated numbers support.

    python3 rooms_sim.py --print            # print the alert and fixes
    python3 rooms_sim.py --serve --port 8010   # small separate web page

This file does not read sensors, the FrostIQ database or any recorded data, and it
does not talk to backend.py. Every number below is invented for the demo.
"""

import argparse
import math
import random
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEED = 7
DAY = "Monday"
MARGIN_C = 0.5            # safety margin the suggested fixes keep below the limit
MAX_OPEN_MIN_POLICY = 5   # a loading with a door open longer than this is "long"
MAX_OPENINGS_POLICY = 5   # a loading with more openings than this is "many"

# rise_per_open_min: degrees C gained per minute the door stays open.
# rise_per_opening: extra degrees C per opening. recovery: degrees C lost per minute once closed.
ROOMS = [
    {"id": "4417", "name": "Freezer A", "setpoint_c": -18.0,
     "rise_per_open_min": 0.45, "rise_per_opening": 0.10, "recovery_c_per_min": 0.40},
    {"id": "5032", "name": "Freezer B", "setpoint_c": -20.0,
     "rise_per_open_min": 0.35, "rise_per_opening": 0.08, "recovery_c_per_min": 0.50},
    {"id": "6208", "name": "Chill room C", "setpoint_c": 2.0,
     "rise_per_open_min": 0.30, "rise_per_opening": 0.06, "recovery_c_per_min": 0.50},
]

# limit_c is the warmest the item may get. (room, load id, item, limit, hour, openings, open minutes)
LOADINGS = [
    ("4417", "101", "frozen chicken", -15.0, 8, 3, 3),
    ("4417", "102", "frozen vegetables", -15.0, 11, 2, 2),
    ("4417", "103", "frozen fish", -15.0, 14, 9, 14),   # the one problem loading
    ("5032", "201", "ice cream", -15.0, 9, 3, 3),
    ("5032", "202", "frozen berries", -15.0, 13, 4, 4),
    ("6208", "301", "dairy", 5.0, 10, 4, 5),
    ("6208", "302", "fresh produce", 6.0, 15, 3, 2),
]


def room_by_id(rooms, room_id):
    return next(room for room in rooms if room["id"] == room_id)


def simulate():
    """Return the simulated rooms and loadings. Deterministic."""
    rng = random.Random(SEED)
    rooms = [dict(room) for room in ROOMS]
    loadings = []
    for room_id, load_id, item, limit, hour, openings, open_min in LOADINGS:
        room = room_by_id(rooms, room_id)
        before = round(room["setpoint_c"] + rng.uniform(-0.2, 0.2), 1)
        rise = room["rise_per_open_min"] * open_min + room["rise_per_opening"] * openings
        peak = round(before + rise, 1)
        minutes_above = 0.0
        if peak > limit:
            share = (limit - before) / (peak - before)
            minutes_above = open_min * (1 - share) + (peak - limit) / room["recovery_c_per_min"]
        loadings.append({
            "room_id": room_id, "load_id": load_id, "item": item, "limit_c": limit,
            "hour": hour, "openings": openings, "open_minutes": open_min,
            "temp_before_c": before, "temp_peak_c": peak,
            "minutes_above_limit": round(minutes_above),
        })
    return {"day": DAY, "rooms": rooms, "loadings": loadings}


def room_headroom(rooms, loadings, room, limit_c, exclude_load=None):
    """Degrees C of room to spare for an item, judged from that room's own loadings."""
    rises = [load["temp_peak_c"] - load["temp_before_c"] for load in loadings
             if load["room_id"] == room["id"] and load["load_id"] != exclude_load]
    typical = max(rises) if rises else 0.0
    projected_peak = room["setpoint_c"] + typical
    return round(limit_c - projected_peak, 1), round(projected_peak, 1)


def analyze(sim):
    """Find loadings that went above their item limit and build the suggested fixes."""
    findings = []
    rooms, loadings = sim["rooms"], sim["loadings"]
    for load in loadings:
        if load["temp_peak_c"] <= load["limit_c"]:
            continue
        room = room_by_id(rooms, load["room_id"])
        allowed = load["limit_c"] - load["temp_before_c"] - MARGIN_C
        excess = load["temp_peak_c"] - load["limit_c"]
        causes = []
        if load["open_minutes"] > MAX_OPEN_MIN_POLICY:
            causes.append("door_left_open")
        if load["openings"] > MAX_OPENINGS_POLICY:
            causes.append("many_openings")
        if not causes:
            causes.append("temperature_drift")

        fixes = []
        # 1. Limit how long the door may stay open, keeping the number of openings as is.
        minutes = math.floor((allowed - room["rise_per_opening"] * load["openings"])
                             / room["rise_per_open_min"])
        if minutes >= 1 and minutes < load["open_minutes"]:
            fixes.append({"kind": "limit_open_time", "value": minutes, "text":
                          "Limit how long door %s can stay open to %d minute%s per loading."
                          % (room["id"], minutes, "" if minutes == 1 else "s")})
        # 2. Limit the number of openings, keeping the open time as is.
        openings = math.floor((allowed - room["rise_per_open_min"] * load["open_minutes"])
                              / room["rise_per_opening"])
        if openings >= 1 and openings < load["openings"]:
            fixes.append({"kind": "limit_openings", "value": openings, "text":
                          "Limit door %s to %d opening%s per loading."
                          % (room["id"], openings, "" if openings == 1 else "s")})
        # 3. Lower the room setpoint enough to keep the same loading under the limit.
        new_setpoint = math.floor((room["setpoint_c"] - (excess + MARGIN_C)) * 2) / 2
        fixes.append({"kind": "change_setpoint", "value": new_setpoint, "text":
                      "Decrease room %s temperature to %.1f °C on %s, if the equipment can reach it."
                      % (room["id"], new_setpoint, sim["day"])})
        # 4. Move the item to the room with the most headroom, judged from the other rooms' data.
        best = None
        for other in rooms:
            if other["id"] == room["id"]:
                continue
            headroom, projected = room_headroom(rooms, loadings, other, load["limit_c"])
            if headroom >= MARGIN_C and (best is None or headroom > best[1]):
                best = (other, headroom, projected)
        if best:
            fixes.append({"kind": "move_item", "value": best[0]["id"], "text":
                          "Move %s (#%s) to room %s, which stayed near %.1f °C in the simulated loadings."
                          % (load["item"], load["load_id"], best[0]["id"], best[2])})
        findings.append({"loading": load, "room": room, "causes": causes, "fixes": fixes})
    return findings


def alert_text(sim, finding):
    load, room = finding["loading"], finding["room"]
    lines = ["Storage room %s (%s): temperature rose to %.1f °C on %s at %02d:00 while loading #%s (%s)."
             % (room["id"], room["name"], load["temp_peak_c"], sim["day"], load["hour"],
                load["load_id"], load["item"])]
    facts = []
    if "door_left_open" in finding["causes"]:
        facts.append("Door %s was left open for %d minutes" % (room["id"], load["open_minutes"]))
    if "many_openings" in finding["causes"] or load["openings"] > 1:
        facts.append("opened %d times" % load["openings"])
    if facts:
        lines.append(" and ".join(facts) + ". This may be why.")
    else:
        lines.append("Door activity was low, so the rise may come from the room itself.")
    lines.append("This can cause an issue for %s (limit %.1f °C): it spent about %d minutes above its limit."
                 % (load["item"], load["limit_c"], load["minutes_above_limit"]))
    return " ".join(lines)


def report_text(sim, findings):
    out = ["SIMULATED DATA. Invented rooms, loadings and limits. Suggestions only; a person decides.", ""]
    if not findings:
        out.append("No loading went above its item limit.")
    for finding in findings:
        out.append(alert_text(sim, finding))
        out.append("Suggested fixes (any one may work):")
        for fix in finding["fixes"]:
            out.append("  - " + fix["text"])
        out.append("")
    return "\n".join(out)


def render_html(sim, findings):
    rows = []
    for room in sim["rooms"]:
        for load in (l for l in sim["loadings"] if l["room_id"] == room["id"]):
            over = load["temp_peak_c"] > load["limit_c"]
            rows.append(
                "<tr%s><td>%s</td><td>%02d:00</td><td>#%s %s</td><td>%.1f</td><td>%d</td><td>%d min</td>"
                "<td>%.1f</td><td>%s</td></tr>" % (
                    ' class="bad"' if over else "", escape(room["id"]), load["hour"],
                    escape(load["load_id"]), escape(load["item"]), load["limit_c"], load["openings"],
                    load["open_minutes"], load["temp_peak_c"], "above limit" if over else "ok"))
    cards = "".join(
        "<div class='card'><b>%s</b> %s<br>setpoint %.1f °C</div>"
        % (escape(room["id"]), escape(room["name"]), room["setpoint_c"]) for room in sim["rooms"])
    alerts = []
    for finding in findings:
        fixes = "".join("<li>%s</li>" % escape(fix["text"]) for fix in finding["fixes"])
        alerts.append("<div class='alert'><p>%s</p><p><b>Suggested fixes (any one may work):</b></p><ul>%s</ul></div>"
                      % (escape(alert_text(sim, finding)), fixes))
    return """<!doctype html><html><head><meta charset="utf-8"><title>FrostIQ rooms (simulated)</title>
<style>body{font-family:system-ui,sans-serif;margin:0;background:#f3f5f1;color:#1b2b24}
header{background:#1f3d33;color:#fff;padding:14px 24px;font-weight:700}
.sim{background:#fff3cd;color:#5c4400;padding:10px 24px;font-weight:600}
main{max-width:980px;margin:20px auto;padding:0 16px}.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{background:#fff;border-radius:8px;padding:12px 16px;min-width:200px}
table{border-collapse:collapse;width:100%%;background:#fff;margin-top:14px}
td,th{padding:8px 10px;border-bottom:1px solid #e4e8e2;text-align:left;font-size:14px}
tr.bad td{background:#fde8e6}.alert{background:#fff;border-left:5px solid #b3402e;padding:12px 18px;margin-top:16px}
small{color:#55645c}</style></head><body><header>FrostIQ: room what-if (%s)</header>
<div class="sim">SIMULATED. Invented rooms, loadings and limits. Not live sensor data.</div><main>
<div class="cards">%s</div>
<table><tr><th>Room</th><th>Time</th><th>Loading</th><th>Item limit &deg;C</th><th>Door openings</th><th>Door open</th><th>Peak &deg;C</th><th>Result</th></tr>%s</table>
%s
<p><small>Causes and fixes come from simple rules applied to the simulated numbers. No trained model is used here.
Door limits, setpoints and item moves are suggestions for a person to decide.</small></p></main></body></html>""" % (
        escape(sim["day"]), cards, "".join(rows), "".join(alerts))


def make_handler(sim, findings):
    page = render_html(sim, findings).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            return

    return Handler


def main():
    parser = argparse.ArgumentParser(description="FrostIQ simulated multi-room what-if page.")
    parser.add_argument("--print", action="store_true", help="print the alert and fixes")
    parser.add_argument("--serve", action="store_true", help="serve a separate page")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    sim = simulate()
    findings = analyze(sim)
    if args.serve:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(sim, findings))
        print("FrostIQ rooms (SIMULATED) on port %d. Separate from backend.py." % args.port)
        server.serve_forever()
    else:
        print(report_text(sim, findings))


if __name__ == "__main__":
    main()
