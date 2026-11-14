# FrostIQ

**Offline AI and decision support for cold-chain temperature anomalies — MadHacks 2026, Qualcomm + N+1 Institute track.**

**Status: hackathon prototype, under development.** This repository is a shared project scaffold. Only the initial Person 4 decision-intelligence module is included; team members must add and validate sensor, model and dashboard components.

## Problem

Cold-storage operators can receive temperature alarms without knowing which underlying event may explain them. Door openings, product loading and possible cooling faults can produce overlapping sensor patterns. Responses can impose different costs: inventory exposure, investigation time, downtime and unnecessary inventory holds.

FrostIQ aims to use **thermal, distance and motion sensing** to classify *candidate* refrigeration events, and allow operators to compare illustrative response scenarios. It is **not** a validated cooling-fault diagnosis, food-safety assessment, or inventory-disposition system.

## Prototype pipeline

```text
Thermal / distance / motion sensors
               |
       Arduino IDE C++ sketch
        (UNO Q STM32 MCU)
               |
        Board-local bridge
               |
       UNO Q Linux processor
        Data + feature pipeline
               |
     ML training + inference
       (on UNO Q, offline)
               |
    Event + on-board risk inputs
               |
 Person 4 Python decision engine
   scenario estimates + explanation
               |
     UNO Q-hosted dashboard
      (laptop = display only)
```

## Qualcomm track restriction (provided by organizers)

> All training and processing for this project must occur on the **Arduino UNO Q**, not on a laptop or cloud service.

- Code can be written on laptops and with AI-assisted code generation, per organizer guidance.
- **Execute** sensor processing, feature engineering, ML training and inference, simulations and dashboard-backend calculations **on the UNO Q**.
- The dashboard may be displayed on a laptop browser while served by the board, subject to organizer interpretation. Keep substantive computations board-side.
- Arduino IDE is used by Person 1 to program the STM32 microcontroller. Python modules run on the UNO Q Linux side.
- Never commit passwords, private keys or Wi-Fi credentials.

## Team workstreams

| Person | Owns | Current status |
|---|---|---|
| 1 | Sensors, Arduino IDE sketch, calibration, collection of on-board labeled data | Placeholder folder; pending teammate contribution |
| 2 | Board-local model training/inference, event outputs, hardware↔Linux/backend integration | Placeholder folder; pending teammate contribution |
| 3 | Uno Q-hosted dashboard, risk indicators, input controls and rendering | Placeholder folder; pending teammate contribution |
| 4 | Local decision engine, scenario tradeoffs, assumptions and recommendations | Initial code and sample data included; **not yet tested on UNO Q** |

See `docs/TEAM_ROLES.md`, `docs/ARCHITECTURE.md`, and `docs/INTEGRATION_CONTRACT.md`.

## Folder structure

```text
FrostIQ/
├── README.md
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TEAM_ROLES.md
│   └── INTEGRATION_CONTRACT.md
├── person1_hardware/README.md
├── person2_ai/README.md
├── person3_dashboard/README.md
└── person4_decision_intelligence/
    ├── README.md
    ├── decision_engine.py
    ├── run_on_uno_q.py
    ├── test_on_uno_q.py
    └── sample_events/*.json
```

## Person 4 integration

From **inside the UNO Q**, after transferring files:

```bash
cd ~/FrostIQ/person4_decision_intelligence
python3 test_on_uno_q.py
python3 run_on_uno_q.py sample_events/door_open.json
```

Person 3 can import `simulate_scenarios(event, settings=None)` from `decision_engine.py`. Exact inputs and outputs are specified in `docs/INTEGRATION_CONTRACT.md`.

For now, the event examples and modeled costs are fictional. Final outputs and ML performance must be verified using code executed **on the UNO Q**.

## Collaboration

1. Create one shared GitHub repository under the owning GitHub account, preferably private during development.
2. Invite the other three members via **Settings → Collaborators / Access → Add people**.
3. Keep work in designated folders; coordinate interfaces via `docs/INTEGRATION_CONTRACT.md`.
4. Merge contributions only after checking imports and board-local execution; avoid overwriting teammates' files.
5. Document physical sensor models and board connection details (excluding secrets) once verified.

## Safety and scope

This is a controlled demonstration only. Do not rely on it to control real refrigeration systems, verify food safety, determine spoilage, or release/dispose inventory. A surface or ambient thermal sensor may not represent food core temperature. AI event classes are hypotheses, not proof of cause. All monetary outputs are hypothetical proxies rather than validated forecasts.