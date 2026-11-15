# FrostIQ rooms what-if (SIMULATED)

`rooms_sim.py` is a standalone extra. It does not touch sensors, the database, backend.py or the trained model.

- Three invented rooms (4417, 5032, 6208), a Monday loading schedule, and a maximum safe temperature per item.
- One loading (#103 frozen fish, room 4417) goes over its limit.
- Rule-based, no network, no cloud AI. The alert names the likely cause (door open time, number of openings, or drift).
- Fixes are shown only when the simulated numbers show they would work: limit door-open minutes, limit openings, lower the room temperature to a stated value, or move the item to the room with the most headroom.
- All numbers are invented. Suggestions only; a person decides.

Run: `python3 rooms_sim.py --print` or `python3 rooms_sim.py --serve --port 8010` (open http://BOARD_IP:8010). Tests: `python3 -m unittest tests.test_rooms_sim`.

**Interpretation:** These are hypothetical modeled **room-air** temperatures and thresholds. The simulator does not measure product core temperatures or justify food disposition or room setpoint changes. Any proposed action requires independent operational/safety validation. This standalone feature does not use live FrostIQ readings or machine learning.
