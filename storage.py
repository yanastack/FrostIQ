"""Persistent readings, observed door transitions and operator-entered loads."""

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def parse_time(value, name="timestamp"):
    if not isinstance(value, str):
        raise ValueError(name + " must be an ISO-8601 timestamp with Z or a UTC offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid " + name + ". Use a timestamp such as 2026-11-14T20:20:00Z.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(name + " needs Z or an explicit UTC offset.")
    return parsed.astimezone(timezone.utc)


def iso_time(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def optional_time(value, name):
    return iso_time(parse_time(value, name)) if value is not None else None


def state_name(value):
    return "open" if value is True else "closed" if value is False else "unknown"


class Store:
    def __init__(self, path, room_id, door_id, source, max_gap_s):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.room_id, self.door_id, self.source = room_id, door_id, source
        self.max_gap_s = max_gap_s
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY, room_id TEXT NOT NULL, source TEXT NOT NULL,
                epoch REAL NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS samples_time ON samples(room_id, source, epoch);
            CREATE TABLE IF NOT EXISTS door_events (
                id INTEGER PRIMARY KEY, room_id TEXT NOT NULL, source TEXT NOT NULL,
                door_id TEXT NOT NULL, epoch REAL NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS door_events_time ON door_events(room_id, source, door_id, epoch);
            CREATE TABLE IF NOT EXISTS loads (
                room_id TEXT NOT NULL, source TEXT NOT NULL, load_id TEXT NOT NULL,
                scheduled_epoch REAL, actual_epoch REAL, payload TEXT NOT NULL,
                PRIMARY KEY (room_id, source, load_id));
            CREATE INDEX IF NOT EXISTS loads_actual ON loads(room_id, source, actual_epoch);
        """)

    def close(self):
        self.db.close()

    def _latest_sample(self, before_epoch=None):
        sql = "SELECT payload FROM samples WHERE room_id=? AND source=?"
        params = [self.room_id, self.source]
        if before_epoch is not None:
            sql += " AND epoch<=?"
            params.append(before_epoch)
        sql += " ORDER BY epoch DESC, id DESC LIMIT 1"
        row = self.db.execute(sql, params).fetchone()
        return json.loads(row[0]) if row else None

    def _event(self, sample, event_type, state, previous_state, timestamp, **details):
        event = {
            "event_id": str(uuid.uuid4()), "room_id": self.room_id,
            "door_id": self.door_id, "source": self.source,
            "session_id": sample["session_id"], "recording_id": sample["recording_id"],
            "timestamp": timestamp, "event_type": event_type,
            "state": state_name(state), "previous_state": state_name(previous_state),
            **details,
        }
        self.db.execute(
            "INSERT INTO door_events(room_id,source,door_id,epoch,payload) VALUES(?,?,?,?,?)",
            (self.room_id, self.source, self.door_id, parse_time(timestamp).timestamp(),
             json.dumps(event, allow_nan=False)),
        )

    def record_sample(self, sample, gap=False):
        previous = self._latest_sample()
        state = sample["derived"]["door_open"]
        previous_state = previous["derived"].get("door_open") if previous else None
        restarted = previous and previous.get("session_id") != sample["session_id"]
        # Lost observations end at the last valid sample, so the dashboard does
        # not shade an unobserved interval as if the door were definitely open.
        with self.db:
            if previous and previous_state is not None and (restarted or gap or state is None):
                self._event(
                    sample, "observation_lost", None, previous_state, previous["timestamp"],
                    reason="process_restarted" if restarted else "data_gap" if gap else "sensor_unavailable",
                )
                previous_state = None
            if restarted or gap:
                previous_state = None
            if state is not None and state != previous_state:
                event_type = "state_observed" if previous_state is None else "opened" if state else "closed"
                details = {"opening_observed": event_type == "opened"}
                if event_type == "closed":
                    row = self.db.execute(
                        "SELECT payload FROM door_events WHERE room_id=? AND source=? AND door_id=? ORDER BY id DESC LIMIT 1",
                        (self.room_id, self.source, self.door_id),
                    ).fetchone()
                    opened = json.loads(row[0]) if row else None
                    if opened and opened["state"] == "open":
                        duration = max(0.0, (parse_time(sample["timestamp"]) - parse_time(opened["timestamp"])).total_seconds())
                        details["observed_open_duration_s"] = round(duration, 3)
                        details["duration_s"] = round(duration, 3) if opened["event_type"] == "opened" else None
                        details["opened_at"] = opened["timestamp"] if opened["event_type"] == "opened" else None
                self._event(sample, event_type, state, previous_state, sample["timestamp"], **details)
            self.db.execute(
                "INSERT INTO samples(room_id,source,epoch,payload) VALUES(?,?,?,?)",
                (self.room_id, self.source, parse_time(sample["timestamp"]).timestamp(), json.dumps(sample, allow_nan=False)),
            )

    def history(self, limit, start=None, end=None):
        sql = "SELECT payload FROM samples WHERE room_id=? AND source=?"
        params = [self.room_id, self.source]
        for bound, operator in ((start, ">="), (end, "<")):
            if bound is not None:
                sql += " AND epoch" + operator + "?"
                params.append(bound.timestamp())
        sql += " ORDER BY epoch DESC, id DESC LIMIT ?"
        rows = self.db.execute(sql, params + [limit + 1]).fetchall()
        return {"samples": [json.loads(row[0]) for row in reversed(rows[:limit])], "truncated": len(rows) > limit}

    def door_events(self, start, end, limit=2000):
        rows = self.db.execute(
            "SELECT payload FROM door_events WHERE room_id=? AND source=? AND door_id=? AND epoch>=? AND epoch<? ORDER BY epoch,id LIMIT ?",
            (self.room_id, self.source, self.door_id, start.timestamp(), end.timestamp(), limit + 1),
        ).fetchall()
        events = [json.loads(row[0]) for row in rows[:limit]]
        preceding = self._latest_sample(start.timestamp())
        initial_state = None
        if preceding and 0 <= (start - parse_time(preceding["timestamp"])).total_seconds() <= self.max_gap_s:
            boundary_event = self.db.execute(
                "SELECT payload FROM door_events WHERE room_id=? AND source=? AND door_id=? AND epoch<=? ORDER BY epoch DESC,id DESC LIMIT 1",
                (self.room_id, self.source, self.door_id, start.timestamp()),
            ).fetchone()
            boundary_state = json.loads(boundary_event[0])["state"] if boundary_event else "unknown"
            initial_state = True if boundary_state == "open" else False if boundary_state == "closed" else None
        last = self._latest_sample(end.timestamp())
        observed_until = last["timestamp"] if last else None
        # A stopped sensor cannot insert its own gap event. Expose the stale
        # boundary at query time as an explicitly generated observation loss.
        if last and last["derived"].get("door_open") is not None:
            last_time = parse_time(last["timestamp"])
            if (end - last_time).total_seconds() > self.max_gap_s and last_time >= start:
                if not any(event["timestamp"] == last["timestamp"] and event["state"] == "unknown" for event in events):
                    events.append({
                        "event_id": None, "room_id": self.room_id, "door_id": self.door_id,
                        "source": self.source, "timestamp": last["timestamp"],
                        "event_type": "observation_lost", "state": "unknown",
                        "previous_state": state_name(last["derived"]["door_open"]),
                        "reason": "stale_data", "generated_at_query": True,
                    })
        events.sort(key=lambda event: parse_time(event["timestamp"]))
        return {
            "room_id": self.room_id, "door_id": self.door_id, "source": self.source,
            "window": {"start": iso_time(start), "end": iso_time(end)},
            "state_at_start": state_name(initial_state), "observed_until": observed_until,
            "events": events, "truncated": len(rows) > limit,
        }

    def save_load(self, value, received_at):
        if not isinstance(value, dict) or value.get("room_id") != self.room_id:
            raise ValueError("Supply this backend's room_id in the loading record.")
        allowed = {"room_id", "load_id", "item", "scheduled_at", "actual_at", "product_arrival_temperature_c"}
        if set(value) - allowed:
            raise ValueError("Unknown loading fields: " + ", ".join(sorted(set(value) - allowed)))
        load_id = value.get("load_id")
        if not isinstance(load_id, str) or not 1 <= len(load_id.strip()) <= 80:
            raise ValueError("load_id must be a nonempty string of up to 80 characters.")
        load_id = load_id.strip()
        row = self.db.execute(
            "SELECT payload FROM loads WHERE room_id=? AND source=? AND load_id=?",
            (self.room_id, self.source, load_id),
        ).fetchone()
        existing = json.loads(row[0]) if row else {}
        item = value.get("item", existing.get("item"))
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= 200:
            raise ValueError("item must be a nonempty string of up to 200 characters.")
        scheduled = optional_time(value.get("scheduled_at", existing.get("scheduled_at")), "scheduled_at")
        actual = optional_time(value.get("actual_at", existing.get("actual_at")), "actual_at")
        if scheduled is None and actual is None:
            raise ValueError("Supply scheduled_at or actual_at; use null if a time is unknown.")
        product_temp = value.get("product_arrival_temperature_c", existing.get("product_arrival_temperature_c"))
        if product_temp is not None:
            try:
                valid = type(product_temp) in (int, float) and math.isfinite(product_temp)
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("product_arrival_temperature_c must be a finite measured value or null.")
        record = {
            "room_id": self.room_id, "load_id": load_id, "item": item.strip(), "source": self.source,
            "scheduled_at": scheduled, "actual_at": actual,
            "product_arrival_temperature_c": product_temp,
            "recorded_at": existing.get("recorded_at", received_at), "updated_at": received_at,
        }
        with self.db:
            self.db.execute(
                "INSERT INTO loads(room_id,source,load_id,scheduled_epoch,actual_epoch,payload) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(room_id,source,load_id) DO UPDATE SET scheduled_epoch=excluded.scheduled_epoch,actual_epoch=excluded.actual_epoch,payload=excluded.payload",
                (self.room_id, self.source, load_id, parse_time(scheduled).timestamp() if scheduled else None,
                 parse_time(actual).timestamp() if actual else None, json.dumps(record, allow_nan=False)),
            )
        return record, not bool(existing)

    def loads(self, start=None, end=None):
        sql = "SELECT payload FROM loads WHERE room_id=? AND source=?"
        params = [self.room_id, self.source]
        for bound, operator in ((start, ">="), (end, "<")):
            if bound is not None:
                sql += " AND COALESCE(actual_epoch,scheduled_epoch)" + operator + "?"
                params.append(bound.timestamp())
        sql += " ORDER BY COALESCE(actual_epoch,scheduled_epoch), load_id"
        return [json.loads(row[0]) for row in self.db.execute(sql, params).fetchall()]

    def loading_context(self, at_time):
        row = self.db.execute(
            "SELECT payload FROM loads WHERE room_id=? AND source=? AND actual_epoch<=? ORDER BY actual_epoch DESC,load_id LIMIT 1",
            (self.room_id, self.source, at_time.timestamp()),
        ).fetchone()
        last = json.loads(row[0]) if row else None
        return {
            "last_actual_load": last,
            "seconds_since_last_actual_load": round((at_time - parse_time(last["actual_at"])).total_seconds(), 3) if last else None,
        }
