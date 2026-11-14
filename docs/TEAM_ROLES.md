# FrostIQ — team responsibilities

## Person 1 — Sensors and Arduino IDE
- Wire thermal, distance and motion sensors, validating electrical compatibility.
- Write Arduino IDE C++ to collect and timestamp sensor readings from UNO Q MCU.
- Calibrate, collect labeled example scenarios **on UNO Q**, and coordinate data format with Person 2.
- Test integration of readings from MCU to Linux processor.

## Person 2 — On-device AI, backend and integration
- Own Linux environment and communication from Arduino-side sensor code.
- Train a lightweight classifier **on UNO Q**, run offline inference, and output standardized event labels.
- Expose board-local readings, model predictions and explanations to Persons 3 and 4.
- Support all-board integration and test with external internet disconnected.

## Person 3 — Board-hosted dashboard and risk analysis
- Serve the dashboard from UNO Q Linux, with browser only as display.
- Show current sensor readings, temperature history, classifications, and risk level.
- Provide editable fictional simulation assumptions and render Person 4's outputs.
- Compute all risk and display data on the board, not in client-side JS.

## Person 4 — Decision intelligence and simulation
- Own `person4_decision_intelligence/decision_engine.py`.
- Compare monitoring, inspection and inventory-isolation scenarios using clearly hypothetical cost and exposure proxies.
- Provide transparent, human-review escalation suggestions and explanations.
- Work most closely with Person 3 on the UI and Person 2 on prediction labels.
- Execute and test module **only on UNO Q** under event rule.

## Coordination

Persons 1+2 are sensor/AI team; Persons 3+4 are product/simulation team. Agree on labels and units before integration. All project training/processing must run on UNO Q. Use GitHub branches or pull requests if multiple teammates are editing at once.
