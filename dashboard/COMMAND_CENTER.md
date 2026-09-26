# Portfolio Brain Command Center v3

The command center is a read-only operator view over Portfolio Brain's current sanitized checked-in state plus the newest validated durable GitHub Actions state artifacts.

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

The bridge restores five durable state classes:

- runtime — stale after 150 minutes;
- scheduler — stale after 150 minutes;
- Hunter — stale after 450 minutes;
- cost governor — stale after 60 minutes;
- notifications — stale after 450 minutes.

The Agent Fleet currently has no separate durable artifact stream, so its state is explicitly labeled FALLBACK from agents/AGENT_STATE_SEED.json rather than being presented as live.

The bridge never writes portfolio state back to GitHub. It only restores sanitized artifacts into the ephemeral Pages build workspace.

## Publication

GitHub Pages is enabled for this repository and the command-center publication workflow is configured to publish from GitHub Actions.

Expected production URL:

    https://p00nsmasher.github.io/portfolio-brain/

The site rebuilds on relevant main-branch changes and every hour at minute 37. Before validation/rendering, dashboard.live_state_bridge restores the newest valid runtime, scheduler, Hunter, cost-governor, and notification artifacts using Actions read-only access. If a valid artifact is unavailable, the checked-in seed is used and labeled FALLBACK. Artifacts older than the subsystem freshness window remain usable but are labeled STALE. Public artifacts remain subject to dashboard.validate_publication before deployment.
