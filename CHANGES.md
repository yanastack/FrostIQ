# What changed vs the original FrostIQ application archive

Baseline kept: backend.py, storage.py, board_feed.py, door_status.py, features.py, model_runtime.py,
train_on_uno_q.py, the sketch, and the timeline/door/load UI. No second backend or schema was added.

## New files
| File | Purpose |
|---|---|
| decision_engine.py | Person 4's engine. One-line fix: negative `temperature_limit_c` (freezers) was rejected. Logic/assumptions unchanged. |
| decision_adapter.py | Maps nested schema-1.1 samples to the engine's flat input; computes observed excursion minutes and a demo risk level; gates on stale/missing/untrained data; maps `loading_warming` -> `loading_related_warming`. |
| tests/test_integration_on_uno_q.py | Stdlib tests for the adapter (run on the board). |
| test_decision_engine_on_uno_q.py, run_decision_engine_on_uno_q.py, sample_events/ | Person 4's original tools, unchanged. |
| DEPLOY_ON_UNO_Q.md | Board runbook and hardware checklist. |

## Modified files
* backend.py: preserves the sensor's own status words (`read_error` vs `unavailable`, previously flattened to
  `missing`); `--door-opens-farther` (orientation was hard-coded); `POST /api/recording` starts a new trial ID and writes
  its label to `data/labels.json` (previously one recording ID per server run, so the trainer's 3-trials-per-class
  requirement was not achievable without restarts); `POST /api/recalibrate`; `GET /api/decision`.
* dashboard.py / monitor.html: the old simplified "Inventory scenario" panel is replaced by the engine's three-response
  comparison. Controls are now target, inventory value, downtime $/h, exposure proxy, hold cost. Model panel explains
  not_trained / insufficient_data / uncertain and shows the decision path. Source, model and recording labels are visible.

* train_on_uno_q.py / model_runtime.py: no longer hard-require all four classes. `--classes` trains a subset
  (e.g. 3 classes without `loading_warming`); the loader accepts any 2+ known events. Needs a board test.

## Behavior of the decision panel
| Situation | Shown |
|---|---|
| No fresh reading | "Waiting", no scenarios |
| Temperature sensor missing | "Unavailable", no scenarios |
| Model untrained/uncertain | Costs shown, cause "not classified"; at/below target -> continue monitoring |
| Warming rate not yet known | Modeled as steady, flagged on screen |
| Excursion minutes | Observed continuous time above target (lower bound), never door-open time |

## Status
Done in code, statically checked only (`py_compile`; nothing was executed): all of the above.
Not run anywhere yet: the unit tests, the server, the dashboard rendering, and every item in the DEPLOY checklist.
These must be run on the Uno Q. Known limits: no motion sensor; `loading_warming` is hard to separate from
`door_left_open` without motion, and the model features do not use the recorded load events; no trained weights
exist; only one room/door.
