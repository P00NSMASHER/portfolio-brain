# Brain v8 Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested local v8 work kernel with strict source-bound records,
fair planning, transactional restart-safe history and non-overlapping ownership.

**Architecture:** Introduce the small `brain.v8` package behind an opt-in local
CLI. Reuse `brain.core.canonical`, `digest`, `BrainError` and `require`, without
opening or migrating production state. External actions remain disabled until
their adapters and independent verification are implemented in later plans.

**Tech Stack:** Python 3.12 standard library; sqlite3; unittest; existing GitHub
Foundation and independently credentialed verifier workflows.

**Spec:** `docs/superpowers/specs/2026-10-15-brain-v8-design.md`

## Global Constraints

- No new paid plan or additional spending.
- Private records must never enter public canonical state.
- Keep existing project owners rather than add a competing fleet of agents.
- Retain current per-adapter provider budgets, including the existing 24-GET Brain source collection ceiling.
- Do not erase incidents, acceptance receipts, state branches, source provenance or valid user changes.
- No v8 change inherits an older version's acceptance.
- No production state, active workflow, schedule, verifier identity or task prompt changes in this kernel increment.
- Execute natively in the existing isolated worktree; no Work-credit workflow or delegated implementers.

## Scope and file responsibilities

| File | Responsibility |
|---|---|
| `brain/v8/__init__.py` | Package version and explicit local-only scope |
| `brain/v8/contracts.py` | Strict record validation, UTC parsing and legal transitions |
| `brain/v8/planning.py` | Deterministic project-fair, incident-first selection |
| `brain/v8/journal.py` | Private local SQLite history, replay and resource claims |
| `brain/v8/__main__.py` | Explicit local validate/plan/replay CLI; no provider calls |
| `tests/test_brain_v8_contracts.py` | Identity, schema, evidence and authority negatives |
| `tests/test_brain_v8_planning.py` | Fairness, severity, dependency and bound tests |
| `tests/test_brain_v8_journal.py` | Crash, conflict, tamper and lease tests |
| `tests/test_brain_v8_cli.py` | End-to-end local execution and path safety |
| `docs/rebuild/V8_KERNEL.md` | Usage, measured validation and remaining adapters |

## Review Focus

1. Boolean counters, invalid/date-only UTC values, duplicate IDs and unknown authority fields must fail closed (Task 1).
2. Cyclic or unknown dependencies must not silently become executable work (Task 2).
3. Crash after a durable intent but before provider result must not authorize blind retry (Task 3).
4. Expired claims must not let a new writer steal an operation with an unknown external result (Task 4).
5. Symlinked files or a v2 production database passed to the local CLI must remain untouched (Tasks 3 and 5).

## Task 1: Strict records and non-skippable state transitions

**Files:** Create `brain/v8/__init__.py`, `brain/v8/contracts.py` and
`tests/test_brain_v8_contracts.py`.

**Interfaces:**
- Produces `validate_work(row: dict) -> dict`, returning a deep normalized copy.
- Produces `validate_capability(row: dict, *, now: str) -> dict`.
- Produces `advance(row: dict, target: str, *, evidence_ids: list[str], now: str) -> dict`.
- Produces `parse_utc(value: str) -> datetime` with explicit UTC and full date/time.

Work fields are exactly: `schema_version`, `work_id`, `project_id`, `repository`,
`source_sha`, `fingerprint`, `owner`, `resource`, `state`, `priority_tier`,
`evidence_ids`, `dependencies`, `created_at`, `updated_at`, `attempts`, `blocker`.
Version is integer 1; booleans are not integers. SHA is 40 lower hex, fingerprint
64 lower hex. Work ID is `work:` plus `digest` of project/repository/source SHA/
fingerprint. Project and owner identifiers are 1..80 ASCII alphanumeric/dot/hyphen/
underscore; repository follows existing `REPO` validation. Resource is a 64-hex
digest, not an arbitrary command/path. Timestamps require full ISO UTC `Z` with
optional 1..6 fractional digits; updated time cannot precede creation.
Evidence IDs and dependencies are unique bounded lists of at most 32 IDs;
priority tier is integer 0..4; attempts is integer 0..100. Blocker is either null
or exactly `code`, `retry_condition`, `last_operation_id`, using fixed allowed
codes and bounded opaque identifiers, never free-text secrets.

Capability fields are exactly `schema_version`, `executor`, `repository`,
`resource`, `action`, `status`, `evidence_id`, `observed_at`, `expires_at`.
Status is DECLARED, READ_CONFIRMED, WRITE_CONFIRMED or UNAVAILABLE; stale is
computed from expiry. Actions are READ, PATCH_BRANCH, RUN_TESTS, MERGE, DEPLOY,
UPDATE_TASK. This local increment validates declarations; it never grants access.

- [ ] Write `test_work_identity_and_unknown_authority_rejected`: valid fixture
  round-trips; altered SHA with old ID and added `auto_approve=True` raise BrainError.
- [ ] Add strict scalar/time/duplicate tests and `test_capability_read_is_not_write`.
- [ ] Run `python -m unittest discover -s tests -p test_brain_v8_contracts.py -v`;
  observe RED before implementation; distinguish absent module from assertion failures.
- [ ] Implement strict validators and sequential transitions OBSERVED, DIAGNOSED,
  REPRODUCED, PATCHED, TESTED. BLOCKED, FAILED and ROLLBACK_REQUIRED are explicit
  terminal-for-this-attempt states; resume requires a new recorded observation.
  Later release-related transitions raise `V8_INDEPENDENT_ADAPTER_REQUIRED` in
  this increment. No caller-supplied success flag enables them.
- [ ] Add `test_green_local_tests_cannot_claim_release`: TESTED to RELEASED and
  TESTED to INDEPENDENTLY_VERIFIED both reject; skipped intermediate stages reject.
- [ ] Run focused tests GREEN, then commit `feat(v8): validate source-bound kernel records`.

## Task 2: Bounded all-project planning

**Files:** Create `brain/v8/planning.py`, `tests/test_brain_v8_planning.py`.

**Interfaces:** Consumes Task 1 `validate_work`.
Produces `select_work(items: list[dict], *, cycle: int, limit: int) -> dict` with
`selected`, `deferred`, `blocked_dependencies` and `automatic_execution_authority=False`.

- [ ] Write `test_incident_precedes_profitable_upgrade`: tier 0 school failure
  always precedes tier 3 RETALLY work, regardless of rotation. Unknown revenue
  fields reject under Task 1 rather than enter scoring.
- [ ] Write `test_equal_priority_projects_rotate`: nine equally eligible projects
  each occupy first position once across nine cycles. Within a project, oldest
  updated time then work ID breaks ties. Age cannot outrank a more severe tier.
- [ ] Write dependency tests: only LEARNED dependencies satisfy work; unknown IDs,
  self-dependencies, cycles and unresolved dependencies remain blocked, with
  explicit fixed reason codes. No dependency is assumed complete because absent.
- [ ] Run `python -m unittest discover -s tests -p test_brain_v8_planning.py -v` RED.
- [ ] Implement tier-first project round-robin, excluding blocked/failed work and
  dependency-blocked items. Validate cycle integer 0..2**63-1; limit integer1..5;
  maximum256 input items, unique IDs. Do not mutate caller inputs.
- [ ] Run focused tests GREEN, then commit `feat(v8): plan fair incident-first work`.

## Task 3: Transactional local journal and external-outcome ambiguity

**Files:** Create `brain/v8/journal.py`, `tests/test_brain_v8_journal.py`.

**Interfaces:**
- Produces `KernelJournal(path: Path, *, create=False, readonly=False)` with `append(operation: dict) -> dict`,
  `replay() -> list[dict]`, `close() -> None` and a context-manager interface.
- Operations contain exactly `schema_version`, `operation_id`, `work`,
  `expected_state`, `occurred_at` and `outcome`. Work is a Task1 validated full
  snapshot. Initial creation requires expected_state null and work state OBSERVED;
  subsequent snapshots must match previous state and immutable identity fields.
  Only state, evidence_ids, updated_at, attempts and blocker may change; attempts
  cannot decrease. occurred_at equals work.updated_at. Task1 governs transitions.
- Outcome is LOCAL_COMMITTED, EXTERNAL_INTENT, EXTERNAL_CONFIRMED or EXTERNAL_UNKNOWN.

- [ ] Write `test_duplicate_operation_is_noop_and_conflict_rejected`: same ID and
  canonical request digest yields the same receipt once; differing digest rejects.
- [ ] Write replay tests for modified body, digest, sequence and previous hash;
  every tampered journal fails closed. Verify restart after committed local action
  does not append a duplicate transition; a rolled-back append leaves no partial row.
- [ ] Write `test_external_intent_without_result_requires_reconciliation`: after
  restart, EXTERNAL_INTENT remains unresolved; no automatic retry/execution grant.
  EXTERNAL_UNKNOWN is preserved. Kernel does not call any provider.
- [ ] Write file tests: refuse symlinks/hardlinks, shared parent directories,
  pre-existing foreign SQLite schemas and production schema_version2 files before
  mutating them. Original bytes/mode must be unchanged on refusal.
- [ ] Run focused journal tests RED.
- [ ] Implement one local SQLite journal: application_id and schema version1,
  operation ID uniqueness, contiguous sequence, canonical body digest and
  previous/chain digest. Use BEGIN IMMEDIATE, synchronous FULL and finite5s busy
  timeout. Initialize only a fresh owned file or a recognized verified v8 journal.
  Existing production state is never opened through `brain.core.Store`. With
  create=False a missing path is an error; readonly=True uses SQLite read-only
  URI mode and refuses append/claims. Outer ledger records have a fixed record
  type plus operation payload; WORK is the sole type until Task4 adds claim types.
- [ ] Replay validates records, chain and state transitions; schema validation
  is not provenance verification. Receipts explicitly report local/advisory scope.
- [ ] Run focused tests GREEN, then commit `feat(v8): persist replayable local work history`.

## Task 4: Single-writer claims and conservative expiry

**Files:** Modify `brain/v8/journal.py`; extend `tests/test_brain_v8_journal.py`.

**Interfaces:** Produces `claim(*, resource: str, owner: str, operation_id: str,
source_sha: str, now: str, expires_at: str) -> dict` and
`release_claim(*, resource: str, owner: str, operation_id: str, now: str) -> dict`.

- [ ] Write `test_competing_connections_cannot_claim_one_resource`: two local
  journal connections race through transactions; exactly one current writer owns
  the resource, and the other receives a conflict, never a replacement claim.
- [ ] Write `test_expired_claim_with_unresolved_intent_is_not_stolen`: expiry
  produces reconciliation-required, not free ownership. Wrong owner, operation,
  source, timestamp or resource cannot release a claim.
- [ ] Run these claim tests RED.
- [ ] Implement transactional claims with the same append-only operation ledger;
  projections are derived/replayed and cannot self-certify external completion.
  Lease duration must be positive and at most3600s. An old claim can transfer only
  after recorded LOCAL_COMMITTED/EXTERNAL_CONFIRMED completion or explicit failure
  evidence; unresolved intents remain quarantined. These remain local supplied
  records, not independent provider verification. Claim payloads use separate
  strict CLAIM/CLAIM_RELEASE outer types; replay never treats them as work snapshots.
- [ ] Run all v8 tests GREEN, then commit `feat(v8): enforce single-writer resource claims`.

## Task 5: Local CLI, compatibility and source review

**Files:** Create `brain/v8/__main__.py`, `tests/test_brain_v8_cli.py`,
`docs/rebuild/V8_KERNEL.md`. No active workflow edits.

**Interfaces:** `python -m brain.v8 validate --input PATH`,
`python -m brain.v8 plan --input PATH --cycle N --limit N`,
`python -m brain.v8 replay --journal PATH`.
Commands emit bounded JSON to stdout with `scope=LOCAL_V8_KERNEL_ONLY`,
`runtime_actions_executed=0`, `production_accepted=False`.

- [ ] Write subprocess tests for valid round-trip planning/replay, malformed JSON,
  duplicate keys, non-UTF8, files over1MiB, symlinks and production DB rejection.
  Verify no token is required and no network subprocess/provider calls are used.
- [ ] Run CLI tests RED, then implement bounded local input loading and commands.
  Reuse validators and journal; replay opens readonly=True, create=False. Do not
  duplicate their logic, create absent journals on reads or add automatic migration.
- [ ] Run `python -m unittest discover -s tests -p 'test_brain_v8_*.py' -v` GREEN.
- [ ] Run `python -m unittest discover -s tests`; require exit0 and record actual
  count/skips. Run `git diff --check`; inspect the complete diff against this plan.
- [ ] Document actual supported commands, source-only status, external adapter
  gaps and next subproject. Commit `feat(v8): expose verified local kernel tooling`.
- [ ] Publish to a dedicated draft branch with source-pinned PR evidence using
  existing authorized GitHub tools. Preserve original RED results and failures.
- [ ] Require exact-head `validate` App15368 and `portfolio-phase1-gate` App5121826
  success; inspect original independent logs. Do not merge during the source hold.

## Completion and remaining plans

Kernel complete means the five deliverables above pass their regressions and
independent source checks. It does not mean deployed v8, autonomous arbitrary
patch generation, task-edit runtime access, live recovery or terminal acceptance.

After kernel validation, prepare separate reviewable plans for repair execution,
automation reconciliation, research/learning and operational cleanup. Those plans
must use measured kernel interfaces, verified runtime capabilities and actual
current-source release gates. Do not delete legacy code merely because v8 exists.

## Review and execution status

Spec review approved under the user's delegated authority. Plan self-review
covers interfaces, strict inputs, ambiguity, fairness, ownership and path safety.
Recommended method: native execution in this session, using the existing
independent GitHub verifier for exact-source checks; no background implementers.
The writing-plans workflow requires plan review and execution-method selection
before implementation. Product implementation has not started.
