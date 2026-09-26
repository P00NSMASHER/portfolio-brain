# Portfolio Brain Command Center

The command center is a read-only operator view over Portfolio Brain's sanitized checked-in state.

It is intentionally **not** a control-authority expansion. It does not contact customers, execute trades, move money, deploy, merge, change secrets, invoke external services, or grant ACT authority.

## What it shows

- portfolio-wide operational status;
- all 12 registered projects and their evidence health;
- scheduler-selected and human-gated work counts;
- the 10 persistent agent roles and their maximum autonomy;
- current validation-sprint purpose, scorecard, guardrails, and next admissible action;
- sanitized FreightRecovery validation counts;
- Hunter strategy counters;
- cost-governor ceilings and checked-in reservation state;
- runtime, scheduler, Hunter, notification, and spend kill switches;
- the checked-in autonomous workflow surface;
- a deterministic snapshot hash tying the view to its inputs.

## Run locally

From the repository root:

    python -m dashboard.command_center --serve

Open:

    http://127.0.0.1:8765

The local server exposes only GET views:

- / or /index.html — command-center UI
- /snapshot.json — machine-readable command-center snapshot
- /healthz — read-only health response

POST requests return HTTP 405.

## Build static artifacts

    python -m dashboard.command_center --write-html dashboard/out/command-center.html --write-json dashboard/out/command-center.json

These outputs are derived artifacts. The source of truth remains the checked-in Portfolio Brain state and policy files.

## Validate

    python -m dashboard.validate_command_center

The validator fails closed if the command center widens authority, gains mutation/network capability, loses project or agent coverage, changes the zero paid-model/API budget boundary, or introduces browser-side outbound network primitives.

## Authority

Command-center authority class: OBSERVE

Mutation capability: NONE

Browser outbound network capability: NONE

Data boundary: SANITIZED_CHECKED_IN_STATE_ONLY
