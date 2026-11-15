"""The same inputs are used for training and live predictions."""

import math
import struct


EVENTS = ("normal", "door_left_open", "loading_warming", "possible_cooling_failure")
FEATURE_NAMES = (
    "temperature_c",
    "temperature_rate_c_per_min",
    "door_open",
    "door_open_duration_s",
    "motion_detected",
    "motion_available",
)


def feature_vector(sample):
    """Return model inputs, or None if sensors/window features are unavailable.

    Labels, scenario names, timestamps, source flags and recording IDs are
    deliberately excluded. They must never become clues to the answer.
    """
    readings = sample.get("readings")
    derived = sample.get("derived")
    if not isinstance(readings, dict) or not isinstance(derived, dict):
        return None
    if type(derived.get("door_open")) is not bool:
        return None
    motion = readings.get("motion_detected")
    if motion is not None and type(motion) is not bool:
        return None
    values = [
        readings.get("temperature_c"),
        derived.get("temperature_rate_c_per_min"),
        int(derived["door_open"]),
        derived.get("door_open_duration_s"),
        int(motion) if motion is not None else 0,
        int(motion is not None),
    ]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return None
    try:
        # sklearn's tree prediction also uses float32 feature values.
        values = [struct.unpack("f", struct.pack("f", value))[0] for value in values]
    except (OverflowError, struct.error):
        return None
    if not all(math.isfinite(value) for value in values) or values[3] < 0:
        return None
    return values
