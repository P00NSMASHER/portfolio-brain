# Portfolio Brain Command Center v2

The command center is a read-only operator view over Portfolio Brain's current sanitized checked-in state.

It observes the unrestricted post-optimization architecture, including the finite model/API budget and the bounded Gmail action gateway, without becoming a mutation or ACT surface itself.

## What it shows

- all registered portfolio projects and evidence health;
- scheduler-selected and blocked work;
- the persistent agent fleet and maximum autonomy;
- current post-restriction optimization state;
- historical validation-sprint status and the current no-freeze continuous-optimization policy;
- Hunter strategy state;
- cost-governor ceilings and reservations;
- enabled non-Tier-0 model routes;
- the bounded external action engine, rate limit, allowlisted projects, sanitized execution counts, and prohibited action classes;
- runtime, scheduler, Hunter, notification, spend, and action-engine kill switches;
- autonomous GitHub workflow coverage;
- a deterministic snapshot hash.

The former week-long validation sprint is retired; it is historical evidence only and imposes no active freeze or stop date.

The action-engine panel is observational. It cannot send Gmail, execute ACT, change allowlists, alter rate limits, change model routes, spend budget, merge, deploy, trade, move money, or mutate Portfolio Brain.

## Run locally

From the repository root:

    python -m dashboard.command_center --serve

Open:

    http://127.0.0.1:8765

Read-only endpoints:

- / or /index.html — command-center UI
- /snapshot.json — sanitized machine-readable snapshot
- /healthz — health response

POST requests return HTTP 405.

## Static output

    python -m dashboard.command_center --write-html dashboard/out/command-center.html --write-json dashboard/out/command-center.json

## Validate

    python -m dashboard.validate_command_center

Validation fails closed if the command center widens authority, gains mutation/network capability, leaks raw Gmail identifiers/recipient-like data, loses portfolio/agent coverage, stops reflecting the unrestricted optimization state, or introduces browser-side outbound network primitives.

## Command-center authority

- Authority class: OBSERVE
- Mutation capability: NONE
- Browser outbound network capability: NONE
- Data boundary: SANITIZED_CHECKED_IN_STATE_ONLY

The underlying Portfolio Brain may have separately authorized model/API execution and bounded ACT pathways. Those remain governed by their own policies, rate limits, kill switches, provider gates, evidence requirements, and ledgers.
