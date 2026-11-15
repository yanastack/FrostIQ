ARCHIVE NOTE (public release): These instructions describe an earlier development state. See README.md, START_HERE.md, DEPLOY_ON_UNO_Q.md, and CHANGES.md for current context. A previously trained model and private recordings are intentionally not included here.

NOTE: parts of this file predate the integrated build (the sensor adapter now exists; scenario endpoints/fields changed). START_HERE.md, DEPLOY_ON_UNO_Q.md and CHANGES.md are current.

Start with START_HERE.md for dashboard setup, calibration and the board sensor feed.

FrostIQ - Person 2 dummy-data starter
===================================

FIRST TIME WRITING CODE?
Start with first_step.py. It is a small, commented example that displays one
made-up temperature, distance and motion reading. The backend is already
written; you do not need to work out how to edit it before getting started.
With Python 3 installed, you can run the little example with:

   python first_step.py

That example was run successfully on this laptop. It does not train a model.

PURPOSE
Give Persons 3 and 4 a stable data interface while Person 1 builds the sensors.
This is a simulator and backend with AI code prepared for later board work.
No ML model has been trained or included. AI_NEXT_STEPS.txt explains that stage.
PERSON_3_HANDOFF.txt defines the agreed dashboard input/output contract, including
load-entry forms, observed door events and selected-window history.
example_sample.json is a hand-written example for agreeing on the format;
its values are not recorded readings or results of running the application.
All temperatures and distance mappings are illustrative demo values, not
food-safety thresholds or calibrated measurements.

START ON YOUR LAPTOP
The clarified requirement is that model training must happen on the Uno Q.
You can prepare and test this dummy-data prototype before the board is ready.
The default simulator command does not train or load a model.
1. Extract the folder and open a terminal in it.
2. With Python 3 installed, run:

   python backend.py --source simulated --host 127.0.0.1

On systems where the Python command is python3, use python3 instead.
Open http://127.0.0.1:8000/api/latest in your browser to see the dummy readings.
The local prototype keeps generation, processing and logs on your laptop.
Stop it with Ctrl+C when finished.

MOVE TO THE UNO Q
1. Copy this folder onto the Uno Q's Linux filesystem.
2. In a terminal running on the board, open this folder and run:

   python3 backend.py --source simulated

Python 3's standard library is sufficient; no additional packages are needed.
In this deployment, generation, processing and logs happen on the board.
Train the real ML model on the Uno Q. The final system's processing and
offline demonstration should run on the Uno Q as specified in the team plan.
This starter was not connected to or runtime-tested on an Uno Q here.
Local checks passed for the scenario generators, trend calculations, input
validation, SQLite persistence, scheduled/actual load handling, door observation
gaps, history windows, fixture-model predictions, trial separation and the
training guard. No training was performed here.
Network transport was not checked by the automated checks. You subsequently
confirmed the running dummy backend and door-open scenario in your browser.
Board deployment and actual model training still need testing.

The API listens on port 8000. Programs on the same computer use:
   http://127.0.0.1:8000/api/latest

The team's board-hosted dashboard can call this API from its Python code.
A laptop browser can inspect http://<UNO_Q_IP>:8000/api/latest while connected
to the same local network. Internet access is not required for this service.
The API has no authentication; it is a local hackathon prototype.

THE SHARED FORMAT
Each output sample contains:
  schema_version: "1.1"
  room_id: configured room; defaults to "demo_room"
  door_id: configured door; defaults to "door_1"
  session_id: unique to this backend process
  timestamp: UTC ISO-8601 time assigned by the backend at receipt/generation
  source: "simulated" or "real"
  recording_id: unique ID for a recording session
  readings:
    temperature_c: number or null
    distance_cm: number or null
    motion_detected: boolean or null
  sensor_status:
    one status per reading: "ok" or "missing"
  derived:
    temperature_rate_c_per_min: number or null while warming up/unavailable
    door_open: boolean or null when distance mapping is unknown
    door_open_duration_s: observed duration, 0 when closed, null when unknown
  prediction:
    status: "not_trained" by default; additional states described below
    event: null until a loaded model makes a prediction
    score: null until prediction; then an uncalibrated leaf class fraction
    evidence: []; a loaded model adds its actual decision path checks
  simulation: scenario, training_label, elapsed_s; null for real inputs
  loading_context: last recorded actual load and seconds since its actual time

The temperature rate uses the oldest and newest valid readings in the past
60 seconds, after at least 10 seconds of observations. It is a simple trend
estimate. A missing temperature resets that window. "ok" means present and
of the correct type; it does not certify sensor calibration or accuracy.
Door duration starts at the first observed open reading; it is not an exact
physical opening time. Unknown door status resets the duration estimate.
Use timestamps to detect stale data. /api/health reports process health and
the latest sample timestamp; a running process does not guarantee live sensors.
SQLite persists history, observed door transitions and operator-entered loads.
The database is stored beside the JSONL log, or at --db-path if configured.
The JSONL file also records accepted sensor samples for later on-board training.
Current-session health flags and timestamps distinguish saved data from live data.

TEAM HANDOFF
Person 1: confirm sensor models, units, sampling interval, and distance meaning.
Person 2: own ingestion, storage, features, future ML training and prediction.
Person 3: read /api/latest and /api/history for graphs and risk calculations.
Person 4: use the same inputs for their decision engine and simulations.
Persons 3 and 4 should handle null values and display "Model not trained".
They can use the simulation scenario to exercise demo UI branches, clearly
labeled as scripted scenarios. It must not be presented as an AI prediction.

API ROUTES
GET  /api/health              Process status, source, last sample timestamp
GET  /api/latest              Latest sample; 503 until the first reading
GET  /api/history?limit=60    {"samples": [...], "truncated": false}; limit 1 to 10000
GET  /api/door-events         Observed door transitions; default last 20 minutes
GET  /api/loads               Planned and actual loads
POST /api/loads               Create/update a load by load_id
GET  /api/scenarios           Supported simulated scenarios
POST /api/scenario            Switch scenario; simulated mode only
POST /api/ingest              Submit sensor values; real mode only

SWITCH SCENARIOS
During local prototyping, in another Windows PowerShell terminal:

   Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/scenario -ContentType 'application/json' -Body '{"scenario":"door_left_open"}'

On Linux or the Uno Q, in another terminal:

   curl -X POST http://127.0.0.1:8000/api/scenario \
     -H 'Content-Type: application/json' \
     -d '{"scenario":"door_left_open"}'

Other choices: normal, loading_warming, possible_cooling_failure.
Every switch starts a new recording_id and resets the temperature trend window.
Observed door-state continuity remains based on the samples. Historical
samples remain available, with their own original scenario and recording ID.
The simulated patterns develop over tens of seconds to several minutes.
All scenarios start from the same arbitrary baseline of about 4 degrees C.
They are test fixtures, not a validated refrigerator physics model.

SWAP TO REAL READINGS LATER
Stop the backend and start it in real mode:

   python3 backend.py --source real

Sensor readings enter using this exact input format:

   {
     "room_id": "demo_room",
     "temperature_c": 4.2,
     "distance_cm": 5.0,
     "motion_detected": false
   }

temperature_c is required and may be null. Motion is optional and defaults to
null. Supply distance_cm for calibrated door inference, or supply a direct
door_open boolean. Explicit door_open=null means unknown and overrides distance.
A numeric 0 is a valid reading and is different from missing data.

LOADING RECORDS FOR THE DASHBOARD
Person 3's operator-entry form sends room_id, load_id, item, scheduled_at and
actual_at to POST /api/loads. Planned entries may have actual_at=null. Updating
the same load_id preserves omitted fields and does not create a duplicate.
See example_load_input.json. The API returns loads through GET /api/loads and
adds the latest actual load to new sensor samples' loading_context.
The scheduled time never substitutes for actual arrival. A product arrival
temperature is optional and stays null unless measured separately.
See PERSON_3_HANDOFF.txt for door timeline reconstruction, counts and clipping.
Test ingestion from another terminal ON THE UNO Q:

   curl -X POST http://127.0.0.1:8000/api/ingest \
     -H 'Content-Type: application/json' \
     -d '{"room_id":"demo_room","temperature_c":4.2,"distance_cm":5.0,"motion_detected":false}'

Person 1's microcontroller sketch still needs an Uno Q Bridge adapter on the
Linux side. That adapter will receive readings and either POST to /api/ingest
or call Backend.ingest() inside this process. The hardware adapter is not
implemented in this starter. Dashboard and decision-engine outputs keep the
same schema when the source changes.

In simulated mode only, distance >20 cm means open by convention. Real mode
leaves door state unknown until the team confirms a calibrated mapping.
If the real setup also means "larger distance = open", configure its threshold:

   python3 backend.py --source real --door-open-above-cm 20

Replace 20 with the measured threshold. If your sensor has a different meaning
or reversed direction, change the mapping in Backend._append_locked first.

NEXT: TRAIN THE PREPARED AI CODE ON THE BOARD
1. Agree with Person 1 on labeled, repeated real scenarios.
2. Save a recording_id for each trial, with labels recorded by the operator.
   Real-mode human label capture is a future addition, not included here.
3. Build model inputs from readings and time-window features only.
4. Follow AI_NEXT_STEPS.txt to run train_on_uno_q.py ON THE UNO Q and save the model.
5. Hold out entire trials for evaluation, rather than randomly mixing adjacent
   readings or overlapping windows between training and testing.
6. Load the exported JSON with backend.py --model models/event_tree.json.
7. Test complete operation on the board without an internet connection.

Do not feed scenario names, training labels, recording IDs, or source flags
into the classifier. Synthetic-data accuracy does not establish real-world
performance. Temperature, distance and motion may not uniquely distinguish
loading from other warming; allow uncertain predictions where appropriate.
Missing sensors and unexpected inputs should not produce confident events.

The prepared training script requires real recordings and labels, ignores
simulated samples, and holds entire trials aside for evaluation. It refuses
training on Windows and requires --confirm-uno-q when invoked on Linux.
The operator must verify that this Linux terminal is on the actual Uno Q.
No training has been executed here. The backend's default remains not_trained.
With a model, statuses are predicted, uncertain or insufficient_data. Evidence
items contain feature, value, comparison and threshold for the decision path.
Low leaf scores can trigger uncertain; a high score is not proof of accuracy.

VERIFICATION CHECKLIST
Use these checks for the local prototype, then repeat on the Uno Q:
- /api/health responds; /api/latest has source=simulated and prediction.event=null.
- Each scenario changes the readings and creates a new recording_id.
- History and the JSONL log both update; graphs show gaps for null readings.
- In real mode, send a valid reading; confirm it arrives at the dashboard.
- Send temperature_c=null; confirm missing status and no temperature rate.
- Invalid types are rejected with HTTP 400; real mode rejects scenario changes.
- Disconnect internet and repeat; all teammates' processing stays on the board.
