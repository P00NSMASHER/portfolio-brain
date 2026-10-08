# Portfolio Brain soak-first rebuild candidate (isolated)

## Purpose

Reliability and honest acceptance, not additional AI features. This branch is deliberately **not merged into `main` while an existing exact-SHA soak is active**. It does not start a soak, overwrite acceptance history, alter existing state, weaken protected checks or promote a manually triggered run.

The most recent version-2 code at creation already had a successful genuine native `event=schedule` cycle (GitHub run `37715456875`, source `8a47ce9f04f77c2c4ab4c972106ccd31bb1c97e9`, 2026-10-08T01:57 UTC). The version-2 acceptance owner remains responsible for its existing attempt and has the sole acceptance-record write authority. An unrelated merge would invalidate that active source-SHA acceptance.

## Actual discovered defect

The hourly external task formerly used `last-success <=45 minutes` to suppress a fallback. With hourly observation, a legitimate last success can fall just inside that window at one polling time; the next attempt may then be **up to 105 minutes** after the last successful cycle, exceeding the **90-minute soak gap limit**. The existing hourly task was changed to **25 minutes** with no schedule/name/enabled-status change, leaving five nominal minutes for scheduling/dispatch jitter (not a guarantee of any provider's timeliness). This is a real reliability improvement; it is not automatic-run evidence in itself.

## Soak-first acceptance design

`soak_v3/audit.py` provides a read-only independent evidence gate:

- The `verify_artifact` path cryptographically hashes actual ZIP bytes and compares them to an independently retrieved GitHub artifact digest. It parses real delivery, doctor and preflight receipts, checking source/run/state binding, zero backlog and required evidence. Neither a green badge nor an API dispatch acknowledgment alone is accepted.
- The `verify_sqlite` path opens remotely fetched state **read-only**, verifies SQLite integrity, contiguous event IDs and hashes, PUBLIC-only events, zero pending events, per-event ledger chain, report digest, chain/source identity and the exact sequence. The caller must independently fetch and bind these bytes to the immutable GitHub state commit. This verification is separate from the Brain's mutable state writer.
- `evaluate_window` considers **all** exact-SHA core executions submitted by the authoritative provider inventory, including failed/manual/push executions. It checks each mandatory job step, per-run artifact/state evidence, parent continuity and monotonic state sequence. It accepts real `event=schedule` delivery or an externally authenticated task→receipt→clock-job→core receipt chain; a manual `workflow_dispatch` alone never counts. No terminal success can be emitted without three valid automatic runs, a completed two-hour span and the original ≤90-minute gap. Its strongest output is `PRE_POSTVALIDATION`: independent final re-fetch/replay, exact-current-main verification and protected acceptance authority are **still required**.


## Read-only live GitHub baseline probe

`soak_v3/remote_probe.py` independently fetches a **single real native scheduled cycle** from the GitHub API, checks its exact run ID, `event=schedule`, protected source SHA, job and mandatory step conclusions, and its unique provider artifact/digest. It downloads the artifact ZIP and the immutable `brain-state-v2` SQLite blob, validates its Git object SHA-1 and the independently recomputed event ledger and ZIP SHA-256, and emits only `NATIVE_BASELINE_VERIFIED` with `soak_pass=false`. One temporary branch-only smoke workflow independently exercised real native run `37715456875` through the GitHub-hosted [run 37716480414](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37716480414), PASS with provider-verified SQLite and artifact evidence. That temporary workflow file was then deleted to comply with the repository's strict active-workflow inventory, which correctly rejected the extra workflow at the protected Foundation gate. The immutable successful run and artifact remain GitHub evidence, but are not a second automatic Brain cycle. Follow-up proof runs should use an approved workflow inventory or an external read-only auditor, never weaken the inventory gate.

`soak_v3/provider_inventory.py` now retrieves a bounded, paginated, complete provider run inventory for a declared UTC window, rejects incomplete or changing pages and duplicate identities, and includes failed as well as successful core cycles. This is run metadata only, not signed per-cycle artifact or durable-state evidence, and it never returns an acceptance PASS. A completed verifier must combine the inventory with verified per-cycle jobs, artifacts, state, fallback-task provenance, continuity and post-soak verification.

A complete future collector must still authenticate and reconcile all cycles and verify genuine external-task clock provenance, continuity, missed runs and final post-soak evidence. This candidate is not an unattended complete engine and does **not** authorize a soak PASS.

## Non-negotiable provenance limitations

The pure evaluator consumes a caller-supplied inventory, not a network connection. It cannot prove that the caller included *all* GitHub runs or that a boolean external-clock attestation is genuinely authenticated. Therefore **do not wire its output directly to an automatic `PASS`**. A separate trusted collector must paginate GitHub's actual runs (including failures), obtain API artifact digests and immutable remote state bytes, verify task-execution provenance for fallback events, and run POST-SOAK validation. Until such a collector exists and is independently tested, this package is an adversarial verifier building block, not a deployed replacement or a proof of completed acceptance.

Do not change `brain-acceptance-v2`, `brain-state-v2`, `main`, trust-anchor files, or legacy failure history from this branch. Do not treat old queued reducer `37655516971` as deleted; it is unrelated preserved history, not a v3 success.

## Acceptance criteria before proposing integration

1. Existing soak ends at a real and immutable PASS/FAIL/BLOCKED status, never silently restarted or rewritten.
2. Local and GitHub-hosted tests remain green on exact candidate head; protected `validate` and `portfolio-phase1-gate` pass with required review policy.
3. A trusted collector proves all run/job/artifact/state inputs originated from the actual GitHub API, with completeness and immutable source identity.
4. Rehearse pass, missing delivery, manual-only, timestamp drift, artifact tampering, state sequence rollback, and provider outage scenarios without broadening authority.
5. Integrate only after the current exact-SHA acceptance period. The new candidate must earn its **own** automatic two-hour soak on its own SHA. Never transfer another commit's PASS.

## Tests

`python -m unittest discover -s tests -p test_brain_soak_v3.py -v`

The new tests verify the verifier's adversarial logic; a unit-test PASS is not a hosted unattended run.

## After the original v2 soak failed

The v2 attempt is terminal **FAIL** at 2026-10-08T03:27:46Z (90-minute gap from the only genuine completed automatic cycle). Immutable source and provider evidence is preserved on `brain-acceptance-v2` under `acceptance/evidence/soak-gap-fail-20261008.json`. It must not be reclassified or restarted.

### v3 automatic delivery replacement

Two independently triggered GitHub-native schedules now provide redundancy under reviewed policy:

- Complete current-main core: `7,27,47 * * * *`. Every delivered scheduled run executes the original monitored source coverage, research, experiment, doctor, non-force parent-checked state publication and artifact receipt. No step is skipped in a qualifying automatic cycle.
- GitHub-native read-only watchdog: `16,36,56 * * * *`. It queries actual GitHub run metadata, never equates dispatch acceptance with core success, and dispatches once only if the last same-main successful core is at least 35 minutes old and no core is active. A provider-queued stale writer blocks instead of causing a competing writer. Its sole write privilege is Actions dispatch, not contents/state or pull-request merge.

An overdue fallback carries the *actual scheduled watchdog GitHub run ID* into the core. The core fetches the provider's parent metadata and requires event=schedule, correct main SHA, correct clock workflow, recent timestamp, first attempt and github-actions[bot] dispatch actor. Its artifact saves the origin receipt. A separate collector must independently fetch that scheduled parent run, verify its dispatch job and associated core artifact and state before counting the fallback as automatic. An operator/manual dispatch is never treated as a scheduled run merely because its inputs look similar.

Multiple schedules improve tolerance of an individual dropped/delayed cron. GitHub-native scheduling is still not guaranteed: a true outage, stale runner, state conflict, source-read failure or missing receipt fails closed. The original **three genuine automatic cycles, at least 7200 elapsed seconds, maximum 5400-second delivery gap, exact-main, all mandatory jobs, zero event backlog, immutable parent chain and post-soak verification** remain unchanged. Production requires protected exact-head CI and a fresh acceptance attempt after merging. These implementation changes are not a live soak PASS or proof of unlimited self-repair.
