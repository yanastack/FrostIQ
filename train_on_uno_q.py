"""Prepare this file on your laptop; execute its training only on the UNO Q."""

import argparse
import hashlib
import json
import platform
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from features import EVENTS, FEATURE_NAMES, feature_vector


def load_trials(data_path, labels_path):
    labels_bytes = Path(labels_path).read_bytes()
    labels = json.loads(labels_bytes.decode("utf-8"))
    if not isinstance(labels, dict) or not labels:
        raise ValueError("Labels must be a nonempty object mapping recording IDs to event names.")
    if any(not isinstance(key, str) or value not in EVENTS for key, value in labels.items()):
        raise ValueError("Every recording ID must map to one of the four event names.")
    trials = defaultdict(list)
    skipped = Counter()
    data_hash = hashlib.sha256()
    with Path(data_path).open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            data_hash.update(line)
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
                if not isinstance(sample, dict):
                    raise ValueError("expected an object")
            except ValueError as error:
                raise ValueError("Invalid reading at line " + str(line_number)) from error
            if sample.get("source") != "real":
                skipped["not_real_sensor_data"] += 1
                continue
            recording = sample.get("recording_id")
            if not isinstance(recording, str) or recording not in labels:
                skipped["unlabeled"] += 1
                continue
            vector = feature_vector(sample)
            if vector is None:
                skipped["missing_features_or_window_warming_up"] += 1
                continue
            trials[recording].append(vector)
    receipts = {"data_sha256": data_hash.hexdigest(), "labels_sha256": hashlib.sha256(labels_bytes).hexdigest()}
    return dict(trials), labels, dict(skipped), receipts


def split_trials(trials, labels, classes=None):
    """Keep complete trials apart so overlapping windows cannot leak answers.

    `classes` (a subset of EVENTS) limits training to those events, e.g. a
    3-class model without loading_warming. Default: every event that has data.
    """
    by_event = defaultdict(list)
    for recording, rows in trials.items():
        if classes is not None and labels[recording] not in classes:
            continue
        if len(rows) < 20:
            raise ValueError("Recording " + recording + " needs at least 20 usable readings.")
        by_event[labels[recording]].append(recording)
    chosen = [event for event in EVENTS if (event in classes if classes else by_event.get(event))]
    if len(chosen) < 2:
        raise ValueError("Need real trials for at least 2 different events.")
    train_ids, test_ids = [], []
    rng = random.Random(42)
    for event in chosen:
        recordings = sorted(by_event[event])
        if len(recordings) < 3:
            raise ValueError("Collect at least 3 separate real trials for " + event
                             + " (or exclude it with --classes).")
        rng.shuffle(recordings)
        count = max(1, len(recordings) // 3)
        test_ids.extend(recordings[:count])
        train_ids.extend(recordings[count:])
    return train_ids, test_ids


def export_tree(classifier):
    tree = classifier.tree_
    nodes = []
    for index in range(tree.node_count):
        left, right = int(tree.children_left[index]), int(tree.children_right[index])
        if left == right:
            values = [float(value) for value in tree.value[index][0]]
            total = sum(values)
            nodes.append({"probabilities": [value / total for value in values]})
        else:
            nodes.append({
                "feature": int(tree.feature[index]),
                "threshold": float(tree.threshold[index]),
                "left": left,
                "right": right,
            })
    return nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="JSONL log collected on the board")
    parser.add_argument("--labels", required=True, help="JSON mapping recording IDs to event labels")
    parser.add_argument("--output", default="models/event_tree.json")
    parser.add_argument("--classes", nargs="+", choices=EVENTS,
                        help="Train only these events (e.g. normal door_left_open possible_cooling_failure). Default: all with data")
    parser.add_argument("--confirm-uno-q", action="store_true", help="Confirm this terminal is on the UNO Q")
    args = parser.parse_args()
    if platform.system() != "Linux" or not args.confirm_uno_q:
        parser.error("Training must run on the UNO Q's Linux side with --confirm-uno-q. Do not train on a laptop.")
    # Confirmation is an operator attestation; Linux alone does not identify a UNO Q.
    try:
        from sklearn import __version__ as sklearn_version
        from sklearn.metrics import classification_report, confusion_matrix
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        parser.error("Install requirements-board.txt on the UNO Q before training.")
    try:
        trials, labels, skipped, receipts = load_trials(args.data, args.labels)
        train_ids, test_ids = split_trials(trials, labels, args.classes)
        x_train = [row for recording in train_ids for row in trials[recording]]
        y_train = [labels[recording] for recording in train_ids for _ in trials[recording]]
        x_test = [row for recording in test_ids for row in trials[recording]]
        y_test = [labels[recording] for recording in test_ids for _ in trials[recording]]
        classifier = DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, random_state=42)
        classifier.fit(x_train, y_train)  # The only training call; execute on UNO Q.
        predicted = classifier.predict(x_test)
        trained_classes = [str(value) for value in classifier.classes_]
        report = classification_report(y_test, predicted, labels=trained_classes, output_dict=True, zero_division=0)
        confusion = confusion_matrix(y_test, predicted, labels=trained_classes).tolist()
        created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        document = {
            "format": "frostiq_tree_v1",
            "features": list(FEATURE_NAMES),
            "classes": [str(value) for value in classifier.classes_],
            "nodes": export_tree(classifier),
            "metadata": {
                "trained_at": created,
                "training_location": "operator-confirmed Arduino UNO Q",
                "training_source": "real",
                "motion_availability_seen": sorted({int(row[5]) for row in x_train}),
                "sklearn_version": sklearn_version,
                **receipts,
                "train_recording_ids": train_ids,
                "test_recording_ids": test_ids,
                "train_samples": len(x_train),
                "test_samples": len(x_test),
                "skipped_samples": skipped,
                "validation_report": report,
                "confusion_matrix": {"class_order": trained_classes, "values": confusion},
                "score_meaning": "Uncalibrated class fraction at a tree leaf.",
            },
        }
        # Verify the exported interpreter reproduces the sklearn model on every
        # held-out row before saving anything as a deployable model.
        from model_runtime import EventModel
        runtime = EventModel()
        runtime.document = document
        runtime._validate()
        runtime_events, runtime_truth = [], []
        for recording in test_ids:
            for vector in trials[recording]:
                sample = {
                    "readings": {"temperature_c": vector[0], "motion_detected": bool(vector[4]) if vector[5] else None},
                    "derived": {"temperature_rate_c_per_min": vector[1], "door_open": bool(vector[2]),
                                "door_open_duration_s": vector[3]},
                }
                result = runtime.predict(sample, minimum_score=0, check_motion_availability=False)
                expected = str(classifier.predict([vector])[0])
                if result["event"] != expected:
                    raise ValueError("Exported model does not reproduce sklearn predictions.")
                runtime_events.append(runtime.predict(sample)["event"] or "abstained")
                runtime_truth.append(labels[recording])
        operational_labels = trained_classes + ["abstained"]
        document["metadata"]["runtime_validation"] = {
            "samples": len(runtime_truth),
            "abstentions": runtime_events.count("abstained"),
            "accuracy_counting_abstentions_as_incorrect": sum(
                expected == predicted for expected, predicted in zip(runtime_truth, runtime_events)
            ) / len(runtime_truth),
            "confusion_matrix": {
                "class_order": operational_labels,
                "values": confusion_matrix(runtime_truth, runtime_events, labels=operational_labels).tolist(),
            },
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(output)
        print("Model trained on the UNO Q and saved to", output)
        print("Held-out trial evaluation:")
        print(json.dumps(report, indent=2))
        print("These are prototype results; tree scores are not calibrated confidence values.")
    except (OSError, ValueError, KeyError) as error:
        print("Training could not finish:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
