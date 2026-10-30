# Portfolio Brain repair mode: explicit observation hold (October 30, 2026)

## User instruction and scope

The user explicitly directed: **do not start a new 12-hour observation until told to resume**. Prioritize useful engineering repairs and tests instead of repeatedly restarting observation windows. Preserve historical failures. This document is a source-bound technical proposal, not production acceptance.

Current protected starting SHA: `d67bcf066210c54d908d47576dd82286a09308d1`. Existing GitHub cron/scheduler, automatic core, state branch and separate V8 scoped repair cadence are not altered by this patch. No new credentials, payment calls, outreach, permission expansion, manual observer dispatch or unrelated repository changes are authorized.

## Observation and acceptance hold

Both workflow_run observer/receipt jobs are now **hard-disabled** by a literal `false &&` job-level condition, irrespective of any previously set repository variable. The same explicit opt-in variable is preserved for later controlled re-arming:

`vars.PORTFOLIO_12H_OBSERVATION_ENABLED == 'true'`

**Setting the variable alone cannot start an observation**. Resumption requires new explicit user authorization and a separately reviewed protected source change that removes the literal hold. This prevents accidental new 12-hour windows during ongoing repairs.

- `.github/workflows/reliability-day.yml` observer **does not run**, regardless of that repository variable's current value, while the literal hold remains.
- `.github/workflows/portfolio-source-acceptance-producer.yml` receipt producer **does not run**, regardless of that repository variable's current value, while the literal hold remains.
- The existing core and V8 repair workflows continue under their unchanged triggers; no existing cron is edited.
- Workflow-run events may still appear with **skipped** jobs, but a skipped job is not a newly started 12-hour observation, acceptance proof, source PASS or missing core.
- Independent receipt attestation remains gated by its existing trusted receipt-PR provenance; no new public release authority is granted.
- Do not turn on this variable, invoke an observer/acceptance workflow, or reclassify historical runs until the user explicitly requests a fresh observation. On consent, verify actual current source and the accepted mode first; a separate protected, independently tested re-arming change is required. Do not silently flip an existing variable and claim the hard gate is lifted. Never transfer an old source's elapsed seconds to a new SHA.

## Additional job identity hardening

Original GitHub REST job snapshots for cores 41103100254 and 41108902012 contain positive monitor job IDs, matching numeric run IDs, attempt 1 and the exact d67bcf source SHA. The candidate now rejects absent or inconsistent original job IDs, mismatched job-to-run IDs, non-first attempts and wrong source SHA, even if every step claims success. The read-only verifier binds its original monitor to the exact source being replayed. These constraints cannot retroactively turn the historical failures into successful repairs.

## Original failures and repair plan

Historical immutable original evidence:

- [Observer 41104190443](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41104190443): `SourceAcceptanceError: required production step failed` during original GitHub job-step replay, 2026-10-30 18:08 UTC.
- [Repair 41103960627](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41103960627): `V8_CORE_ORIGIN_UNVERIFIED; MANDATORY_CORE_STEP_INCOMPLETE; NO_WRITER_TOKEN`, absent original repair receipt.
- [Observer 41109285013](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41109285013): `soak_v3.audit.EvidenceError: GITHUB_API_UNAVAILABLE` while reading original jobs, 2026-10-30 18:44 UTC.
- [Repair 41109255250](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41109255250): same denied mandatory core-step evidence, no repair receipt.
- Both associated original core runs `41103100254` and `41108902012` were individually read back after completion with successful required steps. This makes temporary incomplete GitHub step snapshots a **hypothesis**, not proof of the exact prior response. Original failed repairs remain failures.
- See [issue #796](https://github.com/P00NSMASHER/portfolio-brain/issues/796) for provenance and [issue #795](https://github.com/P00NSMASHER/portfolio-brain/issues/795) for an independent premerge policy discrepancy.

The proposed fixes add **bounded original job re-reads** to V8 repair core admission (maximum four job snapshots) and independent source observer job verification (maximum three job snapshots). The observer retries an exhausted inner GitHub `GITHUB_API_UNAVAILABLE` response only two additional times. Delays are bounded; unrelated API failures, wrong source/run identity, adverse or explicitly skipped mandatory steps, duplicate required step names, changed original job IDs, missing signed dispatch origin, and exhausted retries **must fail closed**. No snapshot is invented, no old failed run is overwritten, and no token is issued before authenticated original success.

Both source code paths are bound by new immutable Git blob pins in their trusted workflows and active policy validator. Mock-only adversarial tests cover temporary completion, persistent partial steps, explicit negative steps, wrong attempt, job identity drift, source drift, quota/forbidden denials and exhausted GitHub transport.

## Additional original state-push defect (October 30)

- [Brain core 41117144407](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41117144407) failed its original state publication step with `git push` HTTP **408**: `RPC failed`, `send-pack: unexpected disconnect`, and `Everything up-to-date` appearing together. The workflow originally exited immediately on the nonzero push status and could not determine whether the Git remote had accepted the exact commit.
- Original read-only state-branch history later contained neighboring `41113037967` and `41118500349` committed cycles, but no `41117144407` publication in the inspected recent history. The failed run **remains failed**; a console message is not publication proof.
- The repair modifies **only** the existing `.github/workflows/brain-cycle.yml` state publication shell. One original non-force Git push is still attempted. Whether it succeeds, times out, or disconnects, the workflow requires the **exact local Git commit SHA** to be observed through the original remote GitHub branch GET before issuing its delivery receipt. The previous parent may be seen during a maximum of six bounded readbacks; a foreign SHA or exhausted readback denies success. **Never issue a second Git write** merely because the first transport returned an unknown result.
- Seven offline, black-box tests in `tests/test_brain_state_push_uncertain.py` extract and execute the actual production Bash segment under mocked `git`, `gh`, and `sleep`. They cover ambiguous HTTP 408 with exact publication, persistent parent, foreign writer, successful push with delayed visibility, unchanged state, remote API errors, and local commit failure. Nothing sends live Git writes or HTTP calls.
- Any genuinely undelivered prior state transaction still fails closed. The new code prevents false failure for a **genuinely delivered** exact commit after a transport ambiguity; it does not manufacture a state commit, replay the failed run, or treat stdout as confirmation.

## Release and resumption boundary

This is a draft repair until exact-head Foundation `validate` from App 15368, independent `portfolio-phase1-gate` from App 5121826 and review of the complete changed file list succeed, and protected ruleset 24182301 remains active with zero bypass. Do not bypass any permission or rule to merge.

A protected merge of a code fix changes the production source. **The hard opt-in hold must be part of the same protected release** so the new SHA does not automatically begin a new 12-hour source window. The user will explicitly decide when to resume observation later. Historical original GitHub evidence remains immutable and no FINAL PASS is claimed now.
