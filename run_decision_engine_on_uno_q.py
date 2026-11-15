"""Execute ON THE UNO Q only. CLI test harness for Person 4's engine.

Usage on the board:
  python3 run_on_uno_q.py sample_events/door_open.json
  python3 run_on_uno_q.py sample_events/unexplained_warming.json
"""
import json
import sys
from pathlib import Path

from decision_engine import simulate_scenarios


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 run_on_uno_q.py sample_events/door_open.json")
        return 2
    path = Path(sys.argv[1])
    with path.open("r", encoding="utf-8") as source:
        event = json.load(source)
    result = simulate_scenarios(event)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
