# Portfolio Brain V6 — governed release handoff (DRAFT; no deployment)

**Decision: SOURCE CANDIDATE ONLY.** The single intended V6 release candidate is
[PR #682](https://github.com/P00NSMASHER/portfolio-brain/pull/682).
Its source is the coordinated, source-bound superset of component
[#678](https://github.com/P00NSMASHER/portfolio-brain/pull/678),
[#679](https://github.com/P00NSMASHER/portfolio-brain/pull/679) and integrated
[#680](https://github.com/P00NSMASHER/portfolio-brain/pull/680), plus the
migration regressions and this handoff. Those earlier PRs are historical
evidence, **not additional independent merge targets**.

Never use this document, a green CI job, or a recurring assistant request
as authorization to merge, publish, move refs, change schedules, send external
messages, place trades, use paid providers, or relax security checks.

## Frozen starting point — recheck at release

- **Accepted, currently deployed V5 source at review:** protected `main`
  `3fb0bb0dcc28f961033d782260c31f36ed78eb71`.
- **Historical V5 acceptance receipt:** separate
  [`brain-acceptance-v5/acceptance/finish-soak-v5.json`](https://github.com/P00NSMASHER/portfolio-brain/blob/brain-acceptance-v5/acceptance/finish-soak-v5.json).
  Its PASS applies only to V5's exact source and frozen observation window.
- **V6 pre-handoff reviewed functional head:** `c721a40a611136159c0a4dd03cbf8ffb8760cee1`.
  The final candidate HEAD **will change with this handoff documentation**;
  never reuse the previous HEAD's checks as if they certify the new one.
- **V6 effects:** classify a fresh actual source with an expired previous
  comparison as `ACTUAL_STALE_BASELINE`, expose uncertainty in reports, and
  test that a time-expired transfer request never reaches a provider.
  Previously committed events and report bytes must remain untouched.
- **Validation baseline:** V6 component checks and the integrated source
  passed their separate exact-head Foundation + App gates. The real V5
  SQLite compatibility audit (one-off PR #681, closed without merge) fetched
  immutable `f914e7e53586bfca035d313b4d30126891ceac86`,
  verified its 42,897,408-byte SQLite blob, 1,175 canonical events and
  four repository comparisons, and created/replayed a new V6 report only on
  a disposable clone. Its sample contained **zero stale baselines**.
  PR #682's adversarial tests separately cover that missing scenario.

## Gate A — freeze the ONE candidate before operator approval

1. Review this PR's exact file diff against the actual protected V5 SHA.
   There must be no modifications to `brain/core.py`, live GitHub workflows,
   signed Cloudflare handling, scheduling, source-provider budgets,
   credentials, SQLite schema or ledger identity code.
2. Verify the **exact current PR head** has completed SUCCESS for GitHub
   Actions `validate` (App **15368**) and independent
   `portfolio-phase1-gate` (App **5121826**). Require the full combined
   suite, candidate regressions and exact-SHA Brain preflight. A newer commit
   voids those checks. A virtual PR-merge checkout is not the eventual
   protected merge SHA.
3. Preserve old pull requests and their successful and failed job logs as
   review evidence; do not merge the component branches into `main`.
4. Obtain authorization for this **specific final source transition** under
   normal protected review. With no such approval, **STOP — no release**.

## Gate B — read-only latest original state pre-arm

Before any source-changing merge, record actual protected `main` and
`brain-state-v2` commit SHAs. Pin the *newest then-current* durable commit
without replacing it. Capture its original Git `state.sqlite` blob SHA,
byte count and independently computed SHA-256; replay on the **original,
immutable read-only file**: `PRAGMA integrity_check`, foreign keys,
all contiguous event IDs, the exact previous/chain hashes, report digests
and stored V5 source identities, and zero pending events.

On a **separate local disposable copy only**, run the V6 candidate's actual
`Store.read_report` / `Store.report` / `Store.read_report` logic,
including an adversarial but truthfully **synthetic** expired-baseline case.
The real October 12 snapshot cannot be used to claim coverage of a condition
it did not contain.

If an authentic V5 report's `ACTUAL_FRESH` label conflicts with V6's
`ACTUAL_STALE_BASELINE` for the same older snapshot, the strict V6
`Store.read_report` **must reject that report**. This is projection-version
drift, not license to rewrite old state or bypass hash validation. Regenerate
a fresh V6 source-tagged projection **from verified canonical events on the
disposable clone**, preserve original V5 report bytes, and re-read the new
projection. If replay, event continuity or source interpretation cannot be
proved, HOLD the release.

## Gate C — protected source transition (requires explicit approval)

Use only the repository's existing protected review/merge controls.
Do not force-update `main`, overwrite or reset `brain-state-v2`, add a
parallel writer, edit the Cloudflare Worker, rotate signing keys or secrets,
or pause/rename/reschedule the user's existing ChatGPT tasks.

A protected merge produces a **new** `main` commit even if the reviewed
candidate files are identical. Read back that actual SHA. The dynamic
Cloudflare `portfolio-brain-recovery` Worker (last observed deployed version
`9b94dc1d-ee63-47de-8c61-dd62ffd7120c`; cron
`*/10 * * * *`) and native GitHub `brain-cycle-v2` schedule
`7,27,47 * * * *`, plus `brain-clock-v2` watchdog
`16,36,56 * * * *`, must **not** be edited or double-dispatched for this
transition. Verify current live provider configuration again at release;
these observations are not guarantees that it remains unchanged.

An in-flight old-source core may fail `MAIN_DRIFT`. Preserve every original
failure and its accepted/published state, without replaying writes. The
first newly source-bound core may reconstruct a source-specific report using
the ordinary `monitor` stage before `research`, `experiment`, and
`doctor`; it must not imply that an old incompatible report was valid.
Never substitute a push smoke, a Cloudflare `FRESH` tick or
`DISPATCH_ACCEPTED_NOT_COMPLETED` acknowledgment for a completed automatic core.

## Gate D — new V6 runtime acceptance, not inherited V5 PASS

- Require a *genuine* Cloudflare `scheduled()` event plus matching P-256
  signed GitHub origin, or label a genuine GitHub-native scheduled core as
  such; verify immutable production SHA, actual completed jobs, 339-test
  preflight when applicable, current monitor/research/experiment/doctor
  PASS, and zero pending events.
- Independently download the **original** GitHub artifact ZIP, verify its
  provider SHA-256 and CRC, full source/run binding, and exact nonforce
  `state_parent → state_commit` readback. Worker dispatch ACK alone is
  never job completion.
- Build a **source-specific** complete run census, including errors,
  partial discovery labels, unverifiable provider pairs and every
  failed attempt. At least **21,600 seconds** must elapse between first
  and last genuinely qualifying **completed** cores, with no eligible gap
  over **5,400 seconds** (90 minutes). A minimum of three qualifying cores
  is not sufficient without the full interval and other evidence.
- Independently replay the *final original binary SQLite* and report chain
  at the exact terminal state commit on a separate runner; a passing in-job
  doctor or Git parent check alone does not satisfy this gate.
- Only after all gates pass may an authorized reviewer record a **separate
  source-specific V6 terminal acceptance** on a dedicated evidence branch.
  Historical V2 FAIL, V3 BLOCKED, V4 PASS and V5 PASS are not reclassified.

## Rollback / halt conditions

HALT on a failing or missing independent gate, provenance mismatch, signed
origin defect, `MAIN_DRIFT`, concurrent state writer, unverified nonforce
delivery, corrupt/ambiguous event, pending backlog, stale source evidence,
report projection drift without proven safe reconstruction, or any
falsified passing status. Preserve actual failed jobs and source snapshots.

Any revert is a **new protected SHA** and requires approved review and
fresh acceptance; never force reset branches, reuse V5's receipt as rollback
authority, or mutate the event history to make old code pass. A pre-revert
independent read-only rehearsal must test **the actual proposed rollback
implementation** against the *latest* accumulated V6 state, not assume that
a V5 reader will accept new V6 report projections. Recreate a proper
source-tagged report from immutable events when supported, preserving every
prior report row and event. If semantic or schema compatibility cannot be
demonstrated, HOLD rollback for a reviewed compatibility repair.

**No deployment occurred merely by creating, checking or merging this
documentation into the V6 draft.**
