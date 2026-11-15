"""FrostIQ dummy-data backend for local prototyping and UNO Q deployment."""

import argparse
import json
import math
import random
import sqlite3
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from decision_adapter import decision_for_backend
from door_status import DoorDetector
from dashboard import page, panel
from features import EVENTS, feature_vector
from model_runtime import EventModel
from storage import Store, parse_time


MIN_USABLE_READINGS = 20  # the trainer rejects labeled trials shorter than this
SENSOR_STATUSES = {"ok", "missing", "read_error", "unavailable"}
SCENARIOS = ("normal", "door_left_open", "loading_warming", "possible_cooling_failure")


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_reading(value, room_id):
    if not isinstance(value, dict):
        raise ValueError("Send a JSON object.")
    if value.get("room_id") != room_id:
        raise ValueError("room_id must match the backend's configured room.")
    if "temperature_c" not in value:
        raise ValueError("Missing temperature_c. Use null if the sensor is unavailable.")
    for name in ("temperature_c", "distance_cm"):
        number = value.get(name)
        if number is not None:
            try:
                valid = (
                    not isinstance(number, bool)
                    and isinstance(number, (int, float))
                    and math.isfinite(number)
                )
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(name + " must be a finite number or null.")
    if value.get("distance_cm") is not None and value["distance_cm"] < 0:
        raise ValueError("distance_cm cannot be negative.")
    if value.get("motion_detected") is not None and not isinstance(value["motion_detected"], bool):
        raise ValueError("motion_detected must be true, false, or null.")
    sensors = {name: value.get(name) for name in ("temperature_c", "distance_cm", "motion_detected")}
    if "door_open" in value:
        if value["door_open"] is not None and type(value["door_open"]) is not bool:
            raise ValueError("door_open must be true, false, or null.")
        sensors["door_open"] = value["door_open"]
    return sensors


class Backend:
    def __init__(self, args):
        self.args = args
        self.model = EventModel(getattr(args, "model", None))
        self.lock = threading.Lock()
        self.session_id = str(uuid.uuid4())
        self.door_id = getattr(args, "door_id", "door_1")
        self.max_gap_s = getattr(args, "max_sample_gap_s", None) or max(5.0, 3 * getattr(args, "interval", 1.0))
        self.last_sample_mono = None
        self.calibration = []
        self.detector = None
        self.samples = deque(maxlen=600)
        self.temperature_window = deque()
        self.door_open_since = None
        self.scenario = "normal"
        self.scenario_started = time.monotonic()
        self.recording_id = str(uuid.uuid4())
        self.recording_label = None
        self.recording_active = False
        self.recording_started = None
        self.recording_samples = 0
        self.recording_usable = 0
        self.last_recording = None
        self.log_file = None
        if args.log_path:
            log_path = Path(args.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = log_path.open("a", encoding="utf-8")
        self.db_path = getattr(args, "db_path", None) or str(Path(args.log_path or "data/readings.jsonl").with_suffix(".sqlite3"))
        labels = getattr(args, "labels_path", None)
        self.labels_path = Path(labels) if labels else Path(self.db_path).parent / "labels.json"
        try:
            self.store = Store(self.db_path, args.room_id, self.door_id, args.source, self.max_gap_s)
        except (OSError, sqlite3.Error):
            if self.log_file:
                self.log_file.close()
            raise

    def set_scenario(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("Choose a scenario from " + ", ".join(SCENARIOS))
        with self.lock:
            self.scenario = scenario
            self.scenario_started = time.monotonic()
            self.recording_id = str(uuid.uuid4())
            self.temperature_window.clear()
            return {"scenario": self.scenario, "recording_id": self.recording_id}

    def ingest(self, reading):
        """Real sensor adapters can call this method on the UNO Q."""
        status_hint = None
        if isinstance(reading, dict) and isinstance(reading.get("readings"), dict):
            # Keep the sensor's own status words (read_error vs unavailable).
            if isinstance(reading.get("sensor_status"), dict):
                status_hint = reading["sensor_status"]
            reading = {**reading["readings"], "room_id": reading.get("room_id", self.args.room_id)}
        sensors = validate_reading(reading, self.args.room_id)
        with self.lock:
            now = time.monotonic()
            if "door_open" not in sensors and self.args.door_open_above_cm is None:
                distance = sensors["distance_cm"]
                if self.detector is None and distance is not None:
                    self.calibration.append(distance)
                    if len(self.calibration) >= 15:
                        self.detector = DoorDetector(
                            self.calibration,
                            opens_closer=not getattr(self.args, "door_opens_farther", False),
                        )
                sensors["door_open"] = self.detector.update(distance, now) if self.detector else None
            return self._append_locked(sensors, now, status_hint)

    def _update_labels(self, change):
        """Atomically rewrite the labels file on the board."""
        try:
            labels = json.loads(self.labels_path.read_text(encoding="utf-8")) if self.labels_path.exists() else {}
        except ValueError:
            raise ValueError("labels file is not valid JSON: " + str(self.labels_path)) from None
        change(labels)
        self.labels_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.labels_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(labels, indent=2), encoding="utf-8")
        temporary.replace(self.labels_path)
        return labels

    def start_recording(self, label):
        """Real mode: begin one labeled trial. Press stop_recording() to end it."""
        if self.args.source != "real":
            raise ValueError("Labeled recordings require real mode.")
        if label not in EVENTS:
            raise ValueError("Choose a label: " + ", ".join(EVENTS))
        with self.lock:
            if self.recording_active:
                raise ValueError("A recording is already running. Press Stop first.")
            if self.detector is None and self.args.door_open_above_cm is None:
                raise ValueError("Door calibration is not finished. Keep the door closed and still until it completes.")
            recording_id = str(uuid.uuid4())
            self._update_labels(lambda labels: labels.__setitem__(recording_id, label))
            self.recording_id = recording_id
            self.recording_label = label
            self.recording_active = True
            self.recording_started = time.monotonic()
            self.recording_samples = 0
            self.recording_usable = 0
            self.last_recording = None
            self.temperature_window.clear()
            return {"state": "recording", "recording_id": recording_id, "label": label}

    def stop_recording(self):
        """End the trial. A trial with too few usable readings is NOT kept for training."""
        with self.lock:
            if not self.recording_active:
                raise ValueError("No recording is running.")
            rid, label = self.recording_id, self.recording_label
            summary = {
                "recording_id": rid, "label": label, "samples": self.recording_samples,
                "usable": self.recording_usable,
                "duration_s": round(time.monotonic() - self.recording_started, 1),
            }
            if self.recording_usable >= MIN_USABLE_READINGS:
                labels = self._update_labels(lambda labels: None)
                summary["saved"] = labels.get(rid) == label
                summary["message"] = (f"Saved: {summary['samples']} readings logged "
                                      f"({summary['usable']} usable for training) with label {label}.")
            else:
                self._update_labels(lambda labels: labels.pop(rid, None))
                summary["saved"] = False
                summary["message"] = (f"NOT kept for training: only {summary['usable']} usable readings "
                                      f"(need {MIN_USABLE_READINGS}). Record longer.")
            self.recording_active = False
            self.recording_id = str(uuid.uuid4())  # anything after Stop is unlabeled and ignored
            self.recording_label = None
            self.last_recording = summary
            return {"state": "stopped", "last": summary}

    def recording_state(self):
        with self.lock:
            state = {
                "need": MIN_USABLE_READINGS,
                "calibrated": self.detector is not None or self.args.door_open_above_cm is not None,
                "labels_file": str(self.labels_path),
                "log_file": self.args.log_path,
                "last": self.last_recording,
            }
            if self.recording_active:
                state.update(state="recording", label=self.recording_label, samples=self.recording_samples,
                             usable=self.recording_usable,
                             elapsed_s=round(time.monotonic() - self.recording_started, 1))
            else:
                state["state"] = "stopped" if self.last_recording else "idle"
            return state

    def recalibrate(self):
        """Real mode: restart door calibration (door must be physically closed)."""
        if self.args.source != "real":
            raise ValueError("Door calibration applies to real mode only.")
        if self.args.door_open_above_cm is not None:
            raise ValueError("A fixed --door-open-above-cm threshold is in use; adaptive calibration is off.")
        with self.lock:
            self.calibration = []
            self.detector = None
            self.door_open_since = None
            return {"calibrating": True, "needed_valid_distance_readings": 15}

    def _append_locked(self, sensors, now, status_hint=None):
        temp = sensors["temperature_c"]
        distance = sensors["distance_cm"]
        gap = self.last_sample_mono is not None and now - self.last_sample_mono > self.max_gap_s
        if gap:
            self.temperature_window.clear()
            self.door_open_since = None
        if temp is None:
            self.temperature_window.clear()
        else:
            self.temperature_window.append((now, temp))
        while self.temperature_window and now - self.temperature_window[0][0] > 60:
            self.temperature_window.popleft()
        rate = None
        if len(self.temperature_window) >= 2:
            first_time, first_temp = self.temperature_window[0]
            elapsed = now - first_time
            if elapsed >= 10:
                rate = round((temp - first_temp) * 60 / elapsed, 3)

        threshold = self.args.door_open_above_cm
        # This distance-to-door mapping is an explicit demo assumption.
        if self.args.source == "simulated" and threshold is None:
            threshold = 20.0
        door_open = sensors.get("door_open") if "door_open" in sensors else (
            None if distance is None or threshold is None else distance > threshold
        )
        if door_open is True:
            if self.door_open_since is None:
                self.door_open_since = now
            door_duration = round(now - self.door_open_since, 1)
        else:
            self.door_open_since = None
            door_duration = 0.0 if door_open is False else None

        sample = {
            "schema_version": "1.1",
            "room_id": self.args.room_id,
            "door_id": self.door_id,
            "session_id": self.session_id,
            "timestamp": utc_now(),
            "source": self.args.source,
            "recording_id": self.recording_id,
            "readings": sensors,
            "sensor_status": {
                name: "ok" if value is not None else (
                    status_hint.get(name) if status_hint and status_hint.get(name) in SENSOR_STATUSES
                    and status_hint.get(name) != "ok" else "missing")
                for name, value in sensors.items()
            },
            "derived": {
                "temperature_rate_c_per_min": rate,
                "door_open": door_open,
                "door_open_duration_s": door_duration,
            },
            "prediction": {
                "status": "not_trained",
                "event": None,
                "score": None,
                "evidence": [],
            },
            "simulation": {
                "scenario": self.scenario,
                "training_label": self.scenario,
                "elapsed_s": round(now - self.scenario_started, 1),
            } if self.args.source == "simulated" else None,
        }
        sample["loading_context"] = self.store.loading_context(parse_time(sample["timestamp"]))
        sample["prediction"] = self.model.predict(sample)
        if self.log_file:
            self.log_file.write(json.dumps(sample, allow_nan=False) + "\n")
            self.log_file.flush()
        self.store.record_sample(sample, gap=gap)
        self.samples.append(sample)
        if self.recording_active:
            self.recording_samples += 1
            if feature_vector(sample) is not None:
                self.recording_usable += 1
        self.last_sample_mono = now
        return sample

    def simulate_once(self, rng):
        # The same validation and storage path is used for both data sources.
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.scenario_started
            scenario = self.scenario
            temp = 4.0 + 0.08 * math.sin(elapsed / 15)
            distance, motion = 5.0, False
            if scenario == "door_left_open":
                temp = 4.0 + 0.035 * min(elapsed, 180)
                distance = 35.0
            elif scenario == "loading_warming":
                temp = 4.0 + 4 * min(elapsed / 40, 1) * math.exp(-elapsed / 180)
                distance = 35.0 if elapsed < 25 else 5.0
                motion = elapsed < 45 and int(elapsed) % 4 != 0
            elif scenario == "possible_cooling_failure":
                temp = 4.0 + 0.025 * min(elapsed, 600)
            raw = {
                "room_id": self.args.room_id,
                "temperature_c": round(temp + rng.uniform(-0.03, 0.03), 3),
                "distance_cm": round(distance + rng.uniform(-0.1, 0.1), 2),
                "motion_detected": motion,
            }
            return self._append_locked(validate_reading(raw, self.args.room_id), now)

    def view(self, limit=1):
        with self.lock:
            return self.store.history(limit)["samples"]

    def history(self, limit, start=None, end=None):
        with self.lock:
            return self.store.history(limit, start, end)

    def door_events(self, start, end, limit=2000):
        with self.lock:
            return self.store.door_events(start, end, limit)

    def save_load(self, value):
        with self.lock:
            return self.store.save_load(value, utc_now())

    def loads(self, start=None, end=None):
        with self.lock:
            return self.store.loads(start, end)

    def close(self):
        with self.lock:
            self.store.close()
            if self.log_file:
                self.log_file.close()


def make_handler(backend):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def respond(self, status, value):
            encoded = json.dumps(value, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            parsed = urlparse(self.path)
            try:
                self.get_route(parsed)
            except ValueError as error:
                self.respond(400, {"error": str(error)})
            except sqlite3.Error:
                self.respond(500, {"error": "Could not read stored data."})

        def query_window(self, parsed, default_window=False):
            query = parse_qs(parsed.query)
            start = parse_time(query["start"][0], "start") if "start" in query else None
            end = parse_time(query["end"][0], "end") if "end" in query else None
            if default_window:
                end = end or datetime.now(timezone.utc)
                start = start or end - timedelta(minutes=20)
            if start and end and start >= end:
                raise ValueError("start must be before end. Windows include start and exclude end.")
            return query, start, end

        def query_limit(self, query, default):
            try:
                limit = int(query.get("limit", [str(default)])[0])
                if not 1 <= limit <= 10000:
                    raise ValueError()
            except (ValueError, IndexError):
                raise ValueError("limit must be an integer from 1 to 10000.")
            return limit

        def get_route(self, parsed):
            if parsed.path in ("/", "/panel"):
                content = (page(backend) if parsed.path == "/" else panel(backend, parse_qs(parsed.query))).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif parsed.path == "/api/health":
                samples = backend.view()
                self.respond(200, {
                    "status": "running",
                    "source": backend.args.source,
                    "model_status": backend.model.status,
                    "last_sample_timestamp": samples[-1]["timestamp"] if samples else None,
                    "schema_version": "1.1",
                    "session_id": backend.session_id,
                    "has_current_session_readings": bool(samples and samples[-1].get("session_id") == backend.session_id),
                })
            elif parsed.path == "/api/latest":
                samples = backend.view()
                if samples:
                    self.respond(200, samples[-1])
                else:
                    self.respond(503, {"error": "No readings received yet."})
            elif parsed.path == "/api/history":
                query, start, end = self.query_window(parsed)
                self.respond(200, backend.history(self.query_limit(query, 60), start, end))
            elif parsed.path == "/api/door-events":
                query, start, end = self.query_window(parsed, default_window=True)
                self.respond(200, backend.door_events(start, end, self.query_limit(query, 2000)))
            elif parsed.path == "/api/loads":
                _, start, end = self.query_window(parsed)
                self.respond(200, {"loads": backend.loads(start, end)})
            elif parsed.path == "/api/recording":
                self.respond(200, backend.recording_state())
            elif parsed.path == "/api/decision":
                self.respond(200, decision_for_backend(backend, parse_qs(parsed.query)))
            elif parsed.path == "/api/scenarios":
                self.respond(200, {"scenarios": list(SCENARIOS)})
            else:
                self.respond(404, {"error": "Unknown route. See README.txt."})

        def do_POST(self):
            route = urlparse(self.path).path
            if route not in ("/api/scenario", "/api/ingest", "/api/loads", "/api/recording", "/api/recording/stop", "/api/recalibrate"):
                self.respond(404, {"error": "Unknown route."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Send a JSON body of 1 to 8192 bytes.")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError("Send a JSON object.")
                if route == "/api/scenario":
                    if backend.args.source != "simulated":
                        self.respond(409, {"error": "Scenario switching requires simulated mode."})
                        return
                    result = backend.set_scenario(value.get("scenario"))
                    self.respond(200, result)
                elif route == "/api/recording":
                    self.respond(201, backend.start_recording(value.get("label")))
                elif route == "/api/recording/stop":
                    self.respond(200, backend.stop_recording())
                elif route == "/api/recalibrate":
                    self.respond(200, backend.recalibrate())
                elif route == "/api/loads":
                    result, created = backend.save_load(value)
                    self.respond(201 if created else 200, result)
                else:
                    if backend.args.source != "real":
                        self.respond(409, {"error": "Sensor ingestion requires real mode."})
                        return
                    self.respond(201, backend.ingest(value))
            except (ValueError, UnicodeDecodeError) as error:
                self.respond(400, {"error": str(error)})
            except (OSError, sqlite3.Error):
                self.respond(500, {"error": "Could not save the reading. Check board storage."})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("simulated", "real"), default="simulated")
    parser.add_argument("--room-id", default="demo_room")
    parser.add_argument("--door-id", default="door_1")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--door-open-above-cm", type=float)
    parser.add_argument("--door-opens-farther", action="store_true",
                        help="Adaptive detector: opening moves the target FARTHER from the sensor (default: closer)")
    parser.add_argument("--labels-path", help="Recording-label JSON for training; default labels.json beside the SQLite file")
    parser.add_argument("--log-path", default="data/readings.jsonl")
    parser.add_argument("--db-path", help="SQLite path; by default stored beside the JSONL log")
    parser.add_argument("--max-sample-gap-s", type=float, help="Longer gaps reset observed continuity; default max(5, 3*interval)")
    parser.add_argument("--model", help="JSON model trained on the UNO Q; omit until training is complete")
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be a positive finite number.")
    if args.door_open_above_cm is not None and (
        not math.isfinite(args.door_open_above_cm) or args.door_open_above_cm < 0
    ):
        parser.error("--door-open-above-cm must be a nonnegative finite number.")
    if args.max_sample_gap_s is not None and (not math.isfinite(args.max_sample_gap_s) or args.max_sample_gap_s <= 0):
        parser.error("--max-sample-gap-s must be positive and finite.")

    try:
        backend = Backend(args)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error("Could not initialize backend: " + str(error))
    stop = threading.Event()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(backend))
    server.daemon_threads = False
    server.block_on_close = True
    worker = None
    if args.source == "simulated":
        def simulate():
            rng = random.Random(42)
            while not stop.is_set():
                try:
                    backend.simulate_once(rng)
                except (OSError, sqlite3.Error) as error:
                    print("Simulation stopped: could not save readings:", error, flush=True)
                    stop.set()
                    return
                stop.wait(args.interval)
        worker = threading.Thread(target=simulate, name="dummy-sensors", daemon=True)
        worker.start()
    print("FrostIQ backend on port", args.port, "| source:", args.source, flush=True)
    print("Stored readings, door events and loads:", backend.db_path, flush=True)
    if backend.model.status == "not_trained":
        print("No ML model is loaded. Predictions remain not_trained.", flush=True)
    else:
        print("Loaded model:", args.model, "| waiting for complete sensor features", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if worker:
            worker.join()
        server.server_close()
        backend.close()


if __name__ == "__main__":
    main()
