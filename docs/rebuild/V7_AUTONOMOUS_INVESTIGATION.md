# V7 bounded autonomous check revalidation

## Release boundary

This is a candidate extension of existing draft PR #685, not a new production service. Protected V6 source `f39a8b2ad88b6e1f0db246b586c89a9d611a566c` and acceptance issue #684 remain unchanged. Do not merge during that source-specific acceptance window. V7 needs separate protected-source release authorization and its own acceptance. Historical checks and the original V7 shadow audit certify only their exact source versions.

## Intended behavior

The decision queue currently identifies a completed check deterioration but asks the operator to gather its next evidence. The extension selects that follow-up itself and uses the existing `GitHub.observe` GET-only implementation to recheck the public, policy-allowlisted repository. It does not diagnose root cause, repair code, execute third-party source, create or merge a PR, close an incident, change credentials, spend money, or publish state.

Only an existing, replay-verified PASS report with zero pending events qualifies. Both original comparison timestamps must still be actual and inside the existing 172800-second freshness window, on the same revision, with unambiguous check names and source references bound to the exact repository/commit. All eligible input evidence is validated before the first provider read. Unknown repositories, stale/nonactual comparisons, and third-party source-review proposals never trigger investigation reads.

The plan is deterministic, deduplicated by repository, and capped at three repositories. The existing adapter enforces a global 24-request cap, response size, retry and timeout bounds, public visibility, complete bounded check pagination, unique check identities, matching check revision, and unchanged branch during collection. Reserve sixteen remaining request slots before each observation: eight possible metadata/branch/check-page reads, each with at most one existing transient retry. Unused slots are not consumed. Defer remaining work honestly instead of raising budgets or inventing completion. The local `STOP` file is checked before each repository observation; an in-flight bounded observation is not interrupted.

## Outcomes are evidence, not authority

| Result | Meaning |
| --- | --- |
| `STILL_ADVERSE` | A uniquely named completed adverse check is observed on the same revision. |
| `SUCCESS_OBSERVED_NOT_RESOLUTION` | A uniquely named successful check is now observed; root cause and incident resolution are not established. |
| `SOURCE_CHANGED_REQUIRES_NEW_COMPARISON` | Current branch moved; no old-versus-new revision recovery inference. |
| `CHECK_NOT_COMPLETED` | Pending work is not success. |
| `UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK` | Missing or duplicate names cannot confirm either failure or recovery. |
| `OTHER_CONCLUSION_NOT_RESOLUTION` | Neutral, cancelled, skipped or absent conclusions are not resolution. |
| `UNVERIFIED_READ_FAILED` | Provider or evidence verification failed; preserve earlier successful observations but stop further reads and mark the overall result incomplete. |

Every receipt retains source SHA, original state sequence, original queue identity, observed revision, and explicit counts for eligible, attempted and deferred work. Source report objects are unchanged. `execution_authority=false`, `root_cause_verified=false`, `github_mutations=0`, `events_written=0`, and `paid_calls=0` remain explicit. Errors use fixed status labels rather than raw provider exception messages. Fetched check metadata is never treated as an instruction or a shell command.

## Standalone, one-shot entry point

After a separately authorized release and source-compatible state generation:

```sh
python -m brain.investigate \
  --db /private/brain/state.sqlite \
  --expected-sha "$(git rev-parse HEAD)" \
  --output /private/brain/investigation
```

This command is NOT wired into existing Cloudflare/GitHub cron, `brain service`, doctor, mandatory workloads, or canonical event schemas. It performs at most one bounded pass, without a scheduler or background loop. The public-state-only CLI verifies clean exact source and reads the existing original database through `readonly_authority_snapshot`; all `Store` operations occur on a disposable private copy. It must never bootstrap a missing original, drain pending events, generate a new canonical report, write attempts, or write feedback. Expired/source-mismatched reports fail before provider use. Output collision with the original database is rejected before snapshot or provider reads.

`report.json` in the dedicated output directory is the detailed investigation receipt, not a replacement for the canonical Brain report. Existing private report publication provides 0700 directory and 0600 files, rejects symlink/hardlink aliases, and publishes machine JSON last. Standard Markdown/HTML report summaries are ancillary; machine JSON contains the per-check findings. Do not point this output at the canonical report directory. Incomplete, stopped, or budget-deferred execution is not a full revalidation success.

## Test requirements

Use the real existing GitHub adapter with synthetic transport fixtures, not a replacement implementation of provider verification. Cover persistent failure, observed success without incident closure, branch movement and branch races, incomplete/ambiguous check observations, private metadata, source identity, stale/future evidence, zero-backlog and exact-source requirements, stop before/between observations, global budget reservation, deterministic selection and explicit deferred work. Exercise the real CLI on synthetic SQLite state and require unchanged original bytes, mtime and permissions, private receipt output, no missing-state bootstrap, no expired report reads and no output overwrite of original state.

Final candidate quality requires full exact-head Foundation CI plus the separately credentialed existing independent verifier. A passing synthetic test suite is not a real production incident investigation or V7 operational acceptance.
