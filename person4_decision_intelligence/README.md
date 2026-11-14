# Person 4 — decision intelligence (Uno Q)

**Status:** Source code and example events are prepared, but this module has not yet been run or verified on the Uno Q.

This folder contains:
- `decision_engine.py`: purely illustrative scenario cost, exposure and response recommendations.
- `run_on_uno_q.py`: board-only sample input runner.
- `test_on_uno_q.py`: board-only behavioral checks.
- `sample_events/*.json`: fictional demo events for testing.

## Running on the Uno Q

After transferring/cloning the repository onto the board:

```bash
cd ~/FrostIQ/person4_decision_intelligence
python3 test_on_uno_q.py
python3 run_on_uno_q.py sample_events/door_open.json
python3 run_on_uno_q.py sample_events/normal.json
python3 run_on_uno_q.py sample_events/unexplained_warming.json
```

Person 3 imports `simulate_scenarios(event, settings=None)` from `decision_engine.py` and renders the returned dictionary on an Uno Q-hosted dashboard.

All simulation rates, response timings and costs are synthetic **demonstration assumptions**. The `temperature_limit_c` of 5°C is an example threshold, not a universal food-safety standard. This engine does not calculate historical microbial exposure, diagnose equipment, determine food safety, or automatically discard or release inventory.

Board-local training and processing are required by the hackathon; editing or transferring files from a laptop is permitted. Never commit passwords or SSH private keys.
