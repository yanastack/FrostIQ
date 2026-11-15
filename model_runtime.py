"""Run an exported decision tree without any third-party Python packages."""

import json
import math
from pathlib import Path

from features import EVENTS, FEATURE_NAMES, feature_vector


def empty_prediction(status):
    return {"status": status, "event": None, "score": None, "evidence": []}


class EventModel:
    def __init__(self, path=None):
        self.document = None
        if path:
            self.document = json.loads(Path(path).read_text(encoding="utf-8"))
            self._validate()

    @property
    def status(self):
        return "ready" if self.document else "not_trained"

    def _validate(self):
        data = self.document
        if not isinstance(data, dict) or data.get("format") != "frostiq_tree_v1":
            raise ValueError("Unsupported FrostIQ model format.")
        if data.get("features") != list(FEATURE_NAMES):
            raise ValueError("Model features differ from the backend's features.")
        classes = data.get("classes")
        if (not isinstance(classes, list) or len(classes) < 2
                or not all(isinstance(value, str) for value in classes)
                or len(set(classes)) != len(classes) or not set(classes) <= set(EVENTS)):
            raise ValueError("Model classes must be 2 or more distinct, known refrigeration events.")
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 1023:
            raise ValueError("Model must contain 1 to 1023 tree nodes.")
        visited = set()

        def check(index):
            if type(index) is not int or not 0 <= index < len(nodes) or index in visited:
                raise ValueError("Model tree has invalid or repeated node links.")
            visited.add(index)
            node = nodes[index]
            if not isinstance(node, dict):
                raise ValueError("Invalid tree node.")
            if "probabilities" in node:
                probabilities = node["probabilities"]
                if not isinstance(probabilities, list) or len(probabilities) != len(classes):
                    raise ValueError("Invalid model leaf.")
                if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities):
                    raise ValueError("Invalid leaf class fractions.")
                if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-6):
                    raise ValueError("Leaf class fractions must add to one.")
            else:
                feature = node.get("feature")
                threshold = node.get("threshold")
                if type(feature) is not int or not 0 <= feature < len(FEATURE_NAMES):
                    raise ValueError("Invalid model feature index.")
                if type(threshold) not in (int, float) or not math.isfinite(threshold):
                    raise ValueError("Invalid model threshold.")
                check(node.get("left"))
                check(node.get("right"))

        check(0)
        if len(visited) != len(nodes):
            raise ValueError("Model contains unreachable nodes.")

    def predict(self, sample, minimum_score=0.7, check_motion_availability=True):
        if self.document is None:
            return empty_prediction("not_trained")
        values = feature_vector(sample)
        if values is None:
            return empty_prediction("insufficient_data")
        seen_motion_states = self.document.get("metadata", {}).get("motion_availability_seen", [0, 1])
        if check_motion_availability and int(values[5]) not in seen_motion_states:
            return empty_prediction("insufficient_data")
        evidence = []
        index = 0
        nodes = self.document["nodes"]
        while "probabilities" not in nodes[index]:
            node = nodes[index]
            feature = node["feature"]
            value = values[feature]
            go_left = value <= node["threshold"]
            evidence.append({
                "feature": FEATURE_NAMES[feature],
                "value": value,
                "comparison": "<=" if go_left else ">",
                "threshold": node["threshold"],
            })
            index = node["left"] if go_left else node["right"]
        probabilities = nodes[index]["probabilities"]
        best = max(range(len(probabilities)), key=probabilities.__getitem__)
        score = probabilities[best]
        confident = score >= minimum_score
        return {
            "status": "predicted" if confident else "uncertain",
            "event": self.document["classes"][best] if confident else None,
            # This is a leaf class fraction, not a calibrated reliability claim.
            "score": round(score, 4),
            "evidence": evidence,
        }
