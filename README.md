# Portfolio Brain

A small, autonomous business-portfolio intelligence engine. It observes projects,
finds reusable implementations, keeps evidence-backed memory, runs bounded
experiments, and produces engineering and business research reports.

The active implementation is **`brain/`**. The former workflow control plane is
retired. Its code and historical evidence remain available for recovery and offline
regression testing; they do not establish current operational readiness. Historical
issue #210 is a separate acceptance track and is not marked complete by this rebuild.

## What it does

- Monitors four registered public project repositories at exact revisions.
- Rotates business-focused searches across freight recovery, agent products, and school tools.
- Inspects actual source blobs and test paths, preserving source hashes and license classifications. No license type filters discovery.
- Ranks reusable code from transparent structural evidence, stores observations and outcomes, and produces experiment plans and commercial hypotheses.
- Runs a reviewed invoice-deduplication experiment with positive and adversarial simulated cases, comparing correctness and operation counts.
- Refreshes its reusable-code knowledge through at most one evidence-qualified protected PR per week. The existing independently credentialed verifier may merge eligible bot proposals only after required checks.
- Automatically drains acknowledged interrupted work on restart. Failed source reads never advance source observations; other sources continue.
- Also supports explicitly supplied USD long-only holdings, validated prices, exposure/concentration calculations, and fixed-holdings historical scenarios. No vendor subscription or brokerage integration is included.

It does **not** claim inspected third-party code is production-ready, estimate fictitious engineering savings, verify revenue without evidence, execute discovered code, send customer messages, place trades, deploy downstream projects, or spend money. Discovering code regardless of license is not a claim of independent rights verification.

## Run

Python 3.12; no third-party runtime packages or paid model calls.

```bash
python -m brain preflight --output brain-local/preflight --expected-sha "$(git rev-parse HEAD)"
python -m brain init --db brain-local/state.sqlite --output brain-local/bootstrap
python -m brain monitor --db brain-local/state.sqlite --output brain-local/monitor
python -m brain research --db brain-local/state.sqlite --output brain-local/research
python -m brain experiment --db brain-local/state.sqlite --output brain-local/experiment
python -m brain doctor --db brain-local/state.sqlite --output brain-local/doctor
python -m brain evolve --db brain-local/state.sqlite --output brain-local/upgrade
```

The recurring GitHub core and read-only watchdog schedule run without a local host, and the core persists **nonsecret public
observations only** on `brain-state-v2`. GitHub scheduling is not a guarantee of
continuous availability. `python -m brain service --db brain-local/state.sqlite
--output brain-local/service` is the noninteractive continuous-process entry point
for an existing host; an example service-manager configuration is documented.
No external continuous host has been provisioned by this rebuild.

Private repository discovery uses an existing authorized `GITHUB_TOKEN` with
`--private --repository owner/repository`, in private local state only. The public
scheduled engine deliberately cannot publish private repository content. An
inaccessible repository remains unavailable; no credential or access changes occur.

## Evidence and recovery

[Architecture, contracts, and honest acceptance matrix](docs/rebuild/ARCHITECTURE.md)

[Recovery and unattended operation](docs/rebuild/OPERATIONS.md)

[Legacy inventory and forensic evidence](docs/rebuild/FORENSICS.md)

Reports include HTML, Markdown, and machine-readable JSON. `PASS` from deterministic
preflight is not production acceptance. Live delivery and exact-main pre-arm must
also pass. A lengthy soak requires explicit authorization; none is started by these
commands or schedules.

## Reliability-first v3 candidate

The v2 two-hour soak failed because one successful genuine automatic run was not followed by another within 90 minutes; see the immutable `brain-acceptance-v2` failure record. The isolated v3 candidate replaces one sparse cron with a full monitored core at `7,27,47 * * * *` and an independently scheduled GitHub watchdog at `16,36,56 * * * *`. The watchdog is read-only except for requesting a due core through existing Actions permissions; it validates GitHub provider run metadata and cannot change source, state or declare acceptance. The full core verifies the exact scheduled watchdog origin and preserves its receipt. False/manual scheduled claims are rejected. Passing CI only proves code regressions, not a completed unattended soak. The unchanged two-hour evidence gates and separate post-soak verification remain required. Cloud scheduling may still be delayed or dropped.
