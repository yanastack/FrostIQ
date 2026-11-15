"""Adaptive door status for FrostIQ. Run on the UNO Q using Python 3."""

from collections import deque
from math import isfinite
from statistics import mean, stdev
from time import monotonic


def valid_distance(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


class DoorDetector:
    """Create once per sensor placement using readings taken while closed.

    Call update() once per new sample. It returns True (open), False (closed),
    or None (missing distance). Supply monotonic seconds for recorded samples.
    The default assumes opening moves the target closer to the sensor.
    """

    def __init__(self, closed_readings, *, window_seconds=4.0,
                 resolution_cm=0.1, opens_closer=True):
        closed = [value for value in closed_readings if valid_distance(value)]
        if len(closed) < 2:
            raise ValueError("Calibration needs at least two valid closed readings.")
        if not isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("window_seconds must be positive and finite.")
        if not isfinite(resolution_cm) or resolution_cm <= 0:
            raise ValueError("resolution_cm must be positive and finite.")

        self.closed_average = mean(closed)
        # One reporting increment prevents identical samples giving zero tolerance.
        self.noise_cm = max(stdev(closed), resolution_cm)
        self.window_seconds = window_seconds
        self.opens_closer = opens_closer
        self.samples = deque()
        self.last_time = None
        self.is_open = False

    def update(self, distance_cm, timestamp=None):
        now = monotonic() if timestamp is None else timestamp
        if not isfinite(now) or (self.last_time is not None and now < self.last_time):
            raise ValueError("Timestamps must be finite, in increasing time order.")
        self.last_time = now
        while self.samples and self.samples[0][0] <= now - self.window_seconds:
            self.samples.popleft()
        if not valid_distance(distance_cm):
            return None

        self.samples.append((now, distance_cm))
        current_average = mean(value for _, value in self.samples)
        change = self.closed_average - current_average
        if not self.opens_closer:
            change = -change
        if change > 3 * self.noise_cm:
            self.is_open = True
        elif change <= 2 * self.noise_cm:
            self.is_open = False
        return self.is_open
