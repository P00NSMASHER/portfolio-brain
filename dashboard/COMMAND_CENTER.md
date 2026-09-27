# Portfolio Brain Command Center v4

The command center is a read-only operator view over Portfolio Brain's current sanitized checked-in state plus the newest validated durable GitHub Actions state artifacts. It reports model-provider readiness separately from the internal cost governor so missing credentials, inactive billing, provider quota, throttling, and budget blocks cannot be conflated.

It observes the unrestricted post-optimization architecture, including the finite model/API budget and the bounded Gmail action gateway, without becoming a mutation or ACT surface itself.

## What it shows

- all registered portfolio projects and evidence health;
- a Live State Bridge table for runtime, scheduler, Hunter, cost governor, notifications, and agent state, showing LIVE/FALLBACK/STALE, artifact timestamp, source run, sequence, and age;
- the live scheduler queue and currently blocked work, with seed fallback labeled explicitly;
- the persistent agent fleet and maximum autonomy;
- current post-restriction optimization state;
- historical validation-sprint status and the current no-freeze continuous-optimization policy;
- Hunter strategy state from the newest valid durable artifact when available;
- cost-governor ceilings and durable reservation state;
- enabled non-Tier-0 model routes;
- the bounded external action engine, rate limit, allowlisted projects, sanitized execution counts, and prohibited action classes;
- runtime, scheduler, Hunter, notification, spend, and action-engine kill switches;
- autonomous GitHub workflow coverage;
- real operational telemetry: durable queue state, agent heartbeat evidence, actual governed usage versus ceilings, recent sanitized actions, failure stream, and last successful autonomous cycle;
- durable 90-day hourly history with 14-day daily trend summaries and 24-hour per-project momentum signals (explicit signals, never an opaque score);
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
- Data boundary: SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE

The underlying Portfolio Brain may have separately authorized model/API execution and bounded ACT pathways. Those remain governed by their own policies, rate limits, kill switches, provider gates, evidence requirements, and ledgers.


## Live State Bridge

The Pages workflow runs:

    python -m dashboard.live_state_bridge --output-dir dashboard/live --receipt dashboard/live/state_sources.json

The bridge restores durable state for:

- runtime — stale after 150 minutes;
- scheduler — stale after 150 minutes;
- Hunter — stale after 450 minutes;
- cost governor — stale after 60 minutes;
- notifications — stale after 450 minutes;
- agent heartbeat state — stale after 180 minutes;
- model-provider readiness — stale after 1560 minutes.

The bridge never writes portfolio state back to GitHub. It only restores sanitized artifacts into the ephemeral Pages build workspace.

Persistent role activity has its own sanitized `portfolio-agent-heartbeat-state` artifact. Substantive workflows still emit role-specific activity heartbeats: Portfolio Manager for scheduler cycles, Hunter for Hunter cycles, Data Steward for runtime observation, and Engineer for software-factory actions. In addition, the governed `agent-heartbeat-sweep` runs every two hours and emits an explicit `HEALTH_CHECK` heartbeat for every registered role. This keeps connectivity/registration health current without pretending that a health check was substantive agent work; the Agent Fleet table exposes `HEALTH_CHECK` as the last activity when that is the newest evidence.

## Operational telemetry

The v4 operations surface exposes the durable scheduler queue and states, agent heartbeat evidence, actual committed cost/model/API usage, conservative budget-accounted usage, sanitized external action receipts, failure-class signals, last successful autonomous cycles, and live-state source ages. Actual usage and governor-accounted usage are shown separately so reservations are never mislabeled as measured spend.

## Authenticated control plane

The public Pages UI remains read-only and intentionally omits the authenticated control workflow. Manual operations live in `.github/workflows/operator-console.yml` and are repository-owner gated. Persistent pause/resume, budget, and owner-approval changes are proposed through pull requests; queue cancellation and emergency run cancellation operate only through the authenticated GitHub Actions workflow. See `operator_console/OPERATOR_CONSOLE.md`.

## History & trends

Each successful Pages refresh restores the newest `portfolio-command-center-history` artifact, replaces/records one point for the current UTC hour, publishes a sanitized `history.json`, and uploads the new continuation artifact. The history retains up to 2,160 hourly points (90 days).

Daily trends include completed/cancelled work, actual cost, model/API calls, GitHub runner minutes, Hunter candidates/retained findings, sanitized action executions, failure signals, and verified external outcomes.

Project momentum is not a score. It exposes open work and 24-hour deltas in completed/cancelled work, external actions, and verified outcomes.

## Publication

GitHub Pages is enabled for this repository and the command-center publication workflow is configured to publish from GitHub Actions.

Expected production URL:

    https://p00nsmasher.github.io/portfolio-brain/

The site rebuilds on relevant main-branch changes and every hour at minute 37. Before validation/rendering, dashboard.live_state_bridge restores the newest valid runtime, scheduler, Hunter, cost-governor, notification, agent-heartbeat, and provider-readiness artifacts using Actions read-only access. If a valid artifact is unavailable, the checked-in seed is used and labeled FALLBACK. Artifacts older than the subsystem freshness window remain usable but are labeled STALE. The publication gate still suppresses Pages deployment when only volatile metadata changed; telemetry history is persisted independently each successful refresh. Public artifacts remain subject to dashboard.validate_publication before deployment.


## Visual design

Command Center v4.1 uses an Apple-inspired product-site presentation while remaining fully original and dependency-free:

- adaptive light/dark appearance using system preferences;
- native Apple/system typography stack with no bundled font files;
- translucent glass navigation;
- oversized editorial hero typography;
- bento-style KPI cards;
- soft layered depth and restrained gradients;
- pill controls and status badges;
- cleaner table containers and hover states;
- responsive iPhone layouts with horizontally scrollable navigation;
- reduced-motion support for accessibility.

The redesign changes presentation only. Data sources, public read-only authority, live-state provenance, operator-console separation, cost governance, and action boundaries are unchanged.


## Runtime health recovery

A runtime-health recovery pass fixed per-workflow GitHub compute starvation without changing the portfolio-wide paid-model/API ceiling. The command center should treat provider/agent observability as optional to core bridge health while still surfacing their own status explicitly. The first post-fix daily reasoning run produced fresh runtime and agent artifacts and a live provider-readiness result.
