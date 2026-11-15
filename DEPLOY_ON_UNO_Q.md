# FrostIQ on the Arduino UNO Q: deployment runbook

Everything below runs ON THE BOARD (Linux side) unless it says "laptop". The laptop only edits and transfers
code and opens the board-hosted page in a browser. Do not run the server, tests, or training on a laptop.

## 0. One-time setup (board)
1. Copy this folder to the board (scp/rsync/USB from the laptop) and `cd FrostIQ`.
2. Python 3.8+: `python3 --version`
3. Sensor bridge dependency: `python3 -c "import msgpack"` (if missing: install Debian package `python3-msgpack` on the board).
4. Training dependency (only before training): `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-board.txt`
5. Flash `FrostIQ_Sensors/FrostIQ_Sensors.ino` with Arduino IDE (core for UNO Q, libraries Arduino_Modulino and Arduino_RouterBridge).

## 1. Smoke test (board, no sensors needed)
    python3 -m unittest tests.test_integration_on_uno_q -v
    python3 test_decision_engine_on_uno_q.py
    python3 backend.py --source simulated
Open `http://BOARD_IP:8000/` on the laptop. The page must say SIMULATED data. Run each simulated event.

## 2. Live sensor mode (board, two terminals, same folder)
Door CLOSED, then:

    # terminal A
    python3 backend.py --source real --log-path data/real-readings.jsonl [--door-opens-farther]
    # terminal B
    python3 board_feed.py

* Keep the door closed for the first 15 valid distance readings (dashboard shows progress).
* Default assumes opening moves the target CLOSER to the distance sensor. If your mount is the opposite, add
  `--door-opens-farther`. Verify by opening the door and watching the Door tile flip. Do not guess.
* If the mount moves, use the dashboard's "Re-calibrate" button (door closed) instead of restarting.
* Motion is unavailable on this hardware and is shown as Unavailable, never as "none".

## 3. Collect training trials and train (board only)
The trainer needs at least 3 independent recordings per class (4 classes), 20+ usable readings each.
1. In the dashboard (real mode) choose the label, press **Start**, perform the scenario for 2 to 3 minutes
   (the first ~10 s are warm-up and are skipped), then press **Stop**. The banner shows NOT RECORDING / RECORDING /
   STOPPED and whether the trial was SAVED. A trial with fewer than 20 usable readings is discarded automatically.
   Repeat 3+ times per class. Labels are saved to `data/labels.json` on the board.
   Backup without the UI: `curl -X POST http://127.0.0.1:8000/api/recording -H 'Content-Type: application/json' -d '{"label":"door_left_open"}'`
   then `curl -X POST http://127.0.0.1:8000/api/recording/stop -H 'Content-Type: application/json' -d '{}'`.
2. Train:

       .venv/bin/python train_on_uno_q.py --data data/real-readings.jsonl --labels data/labels.json \
         --output models/event_tree.json --confirm-uno-q
3. Restart the server with `--model models/event_tree.json`. Press "Start new labeled recording" for a fresh,
   held-out trial and compare the dashboard's prediction with what you physically did.
**3-class option (recommended if short on time):** loading vs. door-open is hard to separate without a motion sensor.
Record only `normal`, `door_left_open`, `possible_cooling_failure` (3+ trials each) and add
`--classes normal door_left_open possible_cooling_failure` to the training command. The loader accepts any
trained subset of events; the dashboard shows only classes the model actually learned.
If you cannot collect even that by the deadline, say the model is untrained. The dashboard handles that
state honestly and the decision comparison still works (cause shown as "not classified").

## 4. Hardware validation checklist (NOT yet done; needs the physical board)
- [ ] Sketch flashes; `python3 board_feed.py` prints no errors; values change on the dashboard
- [ ] Distance values at closed/open positions recorded; door orientation flag set correctly
- [ ] Door Open/Closed tile and green shading match physical door; opening count plausible
- [ ] Unplug a sensor: status shows Unavailable, no false door transition
- [ ] Stop `board_feed.py`: tiles clear within ~5 s ("Waiting for current readings")
- [ ] Record a load with actual arrival time; marker appears at that time
- [ ] Response comparison appears; changing target/inventory/downtime updates it; recommendation text is advisory
- [ ] `models/event_tree.json` trains on the board; prediction panel shows evidence and "not calibrated"
- [ ] Demo with the board's internet disabled
- [ ] `data/` survives a server restart

## Safety / honesty
Temperature is an air/sensor reading, not product core temperature. The target is an operator assumption. Dollar
figures are synthetic proxies, not forecasts. The model label is a possible explanation, not a diagnosis. The API
has no authentication: use a trusted demo network only.
