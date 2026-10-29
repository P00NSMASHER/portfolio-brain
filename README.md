# Portfolio Brain

An autonomous research, upgrade and repair engine for all current projects.
It observes failures, researches useful improvements, prepares scoped repairs
through existing owners, and requires independent checks and actual delivery
verification. Success means reliable useful projects and less user intervention.
Revenue is optional project context, not the portfolio objective.

The active implementation is **`brain/`**. The former workflow control plane is
retired. Its code and historical evidence remain available for recovery and offline
regression testing; they do not establish current operational readiness. Historical
issue #210 is a separate acceptance track and is not marked complete by this rebuild.

## What it does

- Keeps the four canonical repositories in durable state and adds a separate bounded read-only observation of four more active repo-backed repositories every core cycle, covering eight active repository bindings without widening the canonical write path.
- Builds an explicit improvement queue for nine active logical projects, with named success metrics, candidate counts, operator-reported outcomes, and empty baseline/result fields until genuine before/after evidence exists.
- Rotates project-focused searches across freight recovery, useful applications, school tools, Portfolio Brain reliability, trading data, Roblox quality, permit intelligence, and document workflows.
- Inspects actual source blobs and test paths, preserving source hashes and license classifications. No license type filters discovery.
- Ranks reusable code from transparent structural evidence, stores observations and outcomes, and produces experiment plans and useful upgrade hypotheses.
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
python -m brain projects --db brain-local/state.sqlite --output brain-local/projects
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

## Accepted v4 production baseline (October 8, 2026)

The source-pinned production Brain completed independent six-hour **v4 acceptance:
PASS** on protected `main` commit
[`9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`](https://github.com/P00NSMASHER/portfolio-brain/commit/9fc08c72e2d050359e7f119bfcbfb82b23f95b5b).
The authoritative, read-only acceptance record is
[`brain-acceptance-v4/acceptance/finish-soak-v4.json`](https://github.com/P00NSMASHER/portfolio-brain/blob/brain-acceptance-v4/acceptance/finish-soak-v4.json)
(commit `b1b9f63dc8136f259abdc1b9ad18fcd47cf3b681`).

Fourteen independently provider-logged, signed Cloudflare-originated completed
cores span 28,792 seconds (7h 59m 52s), with a maximum accepted completion gap
of 3,625 seconds (below the 5,400-second limit). All 18 core runs in the
certified window completed successfully, including three **nonqualifying**
Cloudflare-origin jobs whose original provider invocation logs were unavailable,
plus one separate GitHub-native scheduled success. None of those four was
counted as a provider-verified Cloudflare cycle. Original artifact ZIP digests,
remote Git state parents, and zero backlog were independently checked. The
terminal 210-event SQLite ledger and database integrity were replayed in
[networked Foundation CI](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37850145136),
with a separate [independent hosted verifier](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37850298010)
also successful.

**Scope:** This PASS certifies the exact source and historical observation
window only. It does not certify later code, permanently guarantee uptime,
establish commercial outcomes, or authorize a production merge. The recurring
Brain core, native watchdog and independent Cloudflare recovery clock still
need normal runtime monitoring. For current schedules, recovery, and how to
read a provider dispatch without mistaking it for a completed core, see
[operations](docs/rebuild/OPERATIONS.md) and the
[Cloudflare clock contract](reliability/cloudflare/README.md). The evidence-only
[PR #655](https://github.com/P00NSMASHER/portfolio-brain/pull/655) remains
**draft / do not merge**.

## Historical v3 candidate (superseded by accepted v4)

The v2 two-hour soak failed because one successful genuine automatic run was not followed by another within 90 minutes; see the immutable `brain-acceptance-v2` failure record. The isolated v3 candidate replaces one sparse cron with a full monitored core at `7,27,47 * * * *` and an independently scheduled GitHub watchdog at `16,36,56 * * * *`. The watchdog is read-only except for requesting a due core through existing Actions permissions; it validates GitHub provider run metadata and cannot change source, state or declare acceptance. The full core verifies the exact scheduled watchdog origin and preserves its receipt. False/manual scheduled claims are rejected. Passing CI only proves code regressions, not a completed unattended soak. The unchanged two-hour evidence gates and separate post-soak verification remain required. Cloud scheduling may still be delayed or dropped.

### RETALLY and App Factory draft-source intelligence

The optional read-only project report samples current open pull requests and
exact-head CI for RETALLY and `x402-product-factory`, surfacing the highest-priority
source-pinned review actions and stacked draft dependencies. Strict 24-GET bounds,
untrusted-metadata validation and fail-closed CI labels preserve separate release,
buyer-validation and protected-core acceptance requirements. Green CI does not
imply production deployment, actual buyer value or autonomous external authority.

### Focused evidence-to-action queue

The read-only `brain projects` stage now prioritizes high-leverage
RETALLY first-customer/accuracy/security work and App Factory
idea→deployment/buyer-proof work using **bounded exact-open-PR evidence**.
Instead of defaulting to the newest PR, a transparent fixed-category
heuristic ranks up to four distinct opportunity themes for each project,
pinning three review packets to precise PR and source commit identities.
Each packet includes proposed tests, adverse controls, a measurable acceptance
metric and real production/business holds. The queue does not patch downstream
code, message buyers, spend funds or count green CI as realized value.

The optional focused PR reviewer rotates its exact-head CI checks among
the top three distinct RETALLY and App Factory opportunity themes using the
canonical sequence. Ranking stays relevance-only and every check remains
source-pinned. This is bounded evidence rotation, not autonomous project
deployment or verified commercial improvement.

Offline GitHub artifact evidence verification: see `docs/rebuild/ORIGINAL_PROJECT_EVIDENCE.md`.

### Autonomous repair handoff, not just finding generation

The `projects` stage compiles the three highest-ranked distinct current
RETALLY and App Factory source candidates into an **owner-directed fix-and-verify
batch** of at most five concrete technical actions. Every action names an
immutable PR revision, the accountable project owner, a separate QA owner,
failing/unknown exact-head CI conditions, negative tests, release holds and
stable deduplication IDs. Existing scheduled project owners may implement
approved routine source fixes without further prompting; this module cannot
authorize a GitHub token, merge protected code or contact real buyers. See
`brain/repair_autonomy.py` and the original repair-control issue #689.

### Reopening stalled repairs without manual prompts

The project-stage output now includes a restart-safe, owner-bound repair
continuation state machine. An unresolved source/CI fingerprint cannot silently
vanish after a report, failed CI, or a PR dropping from the open sample. Source
changes reopen the existing issue, current-main checks must be separately
verified, and every owner gets an explicit next technical step rather than a
new status-only finding. The private
[repair follow-through contract](docs/rebuild/REPAIR_FOLLOWTHROUGH.md) shows
how existing scheduled owners reuse the previous report's `next_history` and
fresh direct GitHub evidence without adding tasks, credentials or permissions.
This remains independent-gate guarded; it is not blanket authority to merge
financial/production changes or certify real buyer value.

The focused PR/CI sampler now prefers the monotonic GitHub
`brain-cycle-v2` run number for fair proof rotation rather than the event
ledger sequence, which can advance in multiples of three and starve an
opportunity theme. Injected/synthetic tests stay deterministic; no extra
provider calls, authority, or scheduled tasks are introduced.

### Original GitHub repair evidence without user-built JSON

Existing RETALLY and Factory owners can now use the offline/restricted
`brain.repair_provider` helper to fetch exact source PR/merge/current-main
and original named check results via **bounded read-only GitHub GETs**. Its
private evidence envelope replays directly through
`brain.repair_followthrough_cli`, carrying unresolved work across runs and
requiring the original trusted App checks before marking a *technical* main
source verified. See
[Original repair provider](docs/rebuild/ORIGINAL_REPAIR_PROVIDER.md).
No additional schedule, production release, customer contact, spending,
credentials, canonical-state writes, or signed-soak bypass is authorized.

The project stage now spends the freed read budget from retired-game
monitoring on exact, original GitHub PR/merge/CI confirmation for repair
candidates. It checks one rotated RETALLY or App Factory source per core run,
while enforcing the same strict 24-request cap, and explicitly labels
unverified, stale or merged-but-not-current results. Original provider evidence
updates the private owner follow-through queue, never self-approves a merge.

The same bounded original-source lookup also reads the chosen candidate PR's
own exact-head GitHub Actions checks. A verified red source check becomes an
owner-directed regression repair; green mandatory checks move only to
independent QA and unchanged release holds. A false, missing or incomplete
check cannot promote a draft into an active service.

### Repair-code, independent-delivery, and technical-learning handoff

The draft repair loop has three executable offline modules: a narrowly scoped,
SHA-256-verified local code patcher that generates regressions; an original
GitHub/independent-gate SHA-guarded delivery evaluator; and a learning engine
that updates matching repair priority only after several distinct externally
verified technical outcomes. It never equates a green PR with a live service
or technical tests with customer revenue. For commands and limitations, see
[Three-stage autonomous repair](docs/rebuild/THREE_STAGE_AUTONOMOUS_REPAIR.md).
