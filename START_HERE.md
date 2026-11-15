# FrostIQ on the UNO Q (integrated build)

See **DEPLOY_ON_UNO_Q.md** for the current runbook and **CHANGES.md** for what was integrated. The notes below are the original implementation's instructions and still apply, except the scenario controls (now target/inventory/downtime/exposure/hold) and that labeled recordings are started from the dashboard.


Work in the extracted FrostIQ folder on the board's Linux side. Use Python 3.8 or newer. The browser is for display and input. The board stores data, renders charts, computes exposure and hosts inference. The server listens on port 8000 on the local network. Use a trusted demo network.

## Preview the dashboard
Run on the board:

    python3 backend.py --source simulated

On a laptop connected to the board's network, visit http://BOARD_IP:8000/ using the UNO Q's reachable address. Use the simulated event control to change the test conditions. Use Ctrl+C in the server terminal to stop. Simulated readings and model predictions have separate labels.

## Live sensor demo
1. Person 1's sketch must expose the router method frostiq_read_sensors. The supplied FrostIQ_Sensors/FrostIQ_Sensors.ino is based on the team's Wire1 Thermo + Distance sketch. The supplied variant includes a sample ID to skip duplicate polls. Use that sketch with the UNO Q core, Arduino_Modulino and Arduino_RouterBridge libraries if you need to flash the board. The original working RPC sketch is compatible.
2. On the UNO Q check the sensor adapter dependency with `python3 -c "import msgpack"`. If missing, install the Debian python3-msgpack package on the board during setup.
3. Close the door. Start the server on the board:

       python3 backend.py --source real --log-path data/real-readings.jsonl

4. In a second board terminal in this folder run:

       python3 board_feed.py

5. Keep the door closed while the first 15 valid distance samples arrive. The dashboard reports calibration progress. The detector learns the average and sample standard deviation (with one reporting increment as a noise floor). A four-second moving mean dropping three noise units indicates open; returning within two units of baseline indicates closed. Missing readings display as unavailable. Your setup assumes opening moves the target closer. Restart the real server with the door closed after changing sensor placement. Each restart creates a new recording ID.
6. If Person 2 already supplies calibrated door_open values via /api/ingest, use their feed instead of starting a second producer. Direct door_open values take priority. The same route also accepts Person 1's nested JSON packets.

## Training and inference
The bundled trainer and model loader are Person 2's starter. No trained weights are included. Follow AI_NEXT_STEPS.txt for its required labeled independent real trials, setup and on-board training command. For this adaptive detector, use the real-mode command above without --door-open-above-cm. After training add `--model models/event_tree.json` to that command. Model scores describe an experimental classifier. Compare predictions with held-out physical trials on the board.

## Dashboard controls
Use the form to record a scheduled load or actual arrival. Times are UTC. Use the same load ID to add its actual arrival later. The temperature timeline shades observed open intervals and marks actual arrivals. If no recent data is available, the current values clear. The model panel displays inference when available.

The target, hourly percentage, action costs, inventory value and delay are illustrative assumptions. Set them explicitly for the demo. The comparison shows three hypothetical responses, not validated food safety or financial advice. SQLite and JSONL files in data/ survive restarts. Source modes have separate queries. The archive contains no physical trial logs or pre-trained model.

## Integration checks
GET /api/health, /api/latest, /api/history, /api/door-events and /api/loads remain available. The browser updates via the board-rendered /panel endpoint. The board feed uses Arduino's documented UNIX socket /var/run/arduino-router.sock and MessagePack RPC.

https://docs.arduino.cc/tutorials/uno-q/routerbridge-multilanguage/
