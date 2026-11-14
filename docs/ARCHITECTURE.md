# System architecture and MVP

## Board-only execution rule

- **STM32 MCU:** Arduino IDE sketch polls installed sensors and sends board-local readings.
- **Qualcomm Linux on UNO Q:** Receives sensor readings, extracts features, stores training data, trains a lightweight model **on the UNO Q**, performs inference, runs risk and scenario calculations, and serves dashboard content.
- **External laptop:** Authoring, file transfer, terminal access and passive display. No FrostIQ model training, prediction or scenario calculations on the laptop.

## Candidate observations

- Thermal sensor: temperature reading or surface temperature trend, **depending on exact sensor model**.
- Distance sensor: door-position proxy **only if correctly mounted and calibrated**.
- Motion sensor: general activity indication; cannot by itself distinguish a person, loading or unloading.

## Candidate model classes

`normal`, `door_left_open`, `loading_related_warming`, `unexplained_warming`.

These labels are hypotheses; validation depends on real sensor characteristics and labeled events. Start with two or three easy-to-distinguish scenarios if four are unreliable.

## Interface contract

See `INTEGRATION_CONTRACT.md`. All inputs to Person 4 are a dictionary built on the UNO Q, with `predicted_event`, `temperature_c`, `warming_rate_c_per_min`, `excursion_minutes`, `risk_level`.

## Critical path

1. Sensor outputs visible on UNO Q.
2. Board-local event feature extraction and on-board model training/inference.
3. Person 4 scenario function executed and tested on UNO Q using sample inputs.
4. Uno Q dashboard imports board-local predictions and scenario output.
5. End-to-end physical demo runs without external internet.

## Honest limitations

This is a non-safety-certified prototype. A model cannot establish cooling-equipment failure, food core safety, causal attribution or actual financial risk from these sensors alone. Simulated costs are fully assumed and must be described as such.
