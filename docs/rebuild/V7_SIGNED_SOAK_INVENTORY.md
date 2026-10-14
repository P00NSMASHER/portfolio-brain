## V7 read-only original GitHub run inventory (draft-only)

This independent, **non-release** audit records which GitHub Actions core runs
appear in a bounded native provider listing, including the original failed,
skipped, incomplete and nonqualifying executions. It neither replaces V6
[#684](https://github.com/P00NSMASHER/portfolio-brain/issues/684), nor certifies
the six-hour acceptance window.

### Original provider evidence observed October 13–14, 2026

A bounded retrieval of five native GitHub Actions listing pages (100 workflow
runs per page; the API reported 11,602 records across the **whole repository**)
showed **52 original exact-V6-source `brain-cycle-v2` run attempts** between
October 13 00:16 UTC and October 14 00:02 UTC:

| Provider event/conclusion | Observed attempts | What this proves |
| --- | ---: | --- |
| `workflow_dispatch` / success | 46 | Completed GitHub job; **not** authenticated Cloudflare scheduled origin based on the event label alone. |
| `schedule` / success | 3 | Actual native schedule event candidates; original ZIP/job/source/SQLite verification is still required. |
| `schedule` / failure | 1 | Original [#38468439594](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38468439594), failed October 13 21:10 UTC. |
| `workflow_dispatch` / failure | 1 | Original [#38454048750](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38454048750), failed October 13 19:21 UTC. |
| `push` / success | 1 | Original V6 post-merge smoke; **not qualifying** for scheduled automatic acceptance. |

This is a **bounded snapshot, not a cryptographically complete run inventory**.
The two real failed attempts must retain their failure statuses and cannot be
reclassified PASS because later GitHub runs succeeded. These failures may
affect a proposed acceptance interval; they do not, by themselves, refute a
separately evidenced six-hour window *before* the failures. None of the above
totals certifies Cloudflare-origin P-256 signatures, original ZIP digest/CRC,
exact mandatory doctor/monitor/research/experiment logs, nonforce Git state
commit ancestry, independently replayed final SQLite, or 21,600 seconds of
qualifying completed automatic cores with a ≤5,400-second completion gap.

### New offline read-only inspector

`brain.soak_inventory` can take either a *strictly projected* original-run
list with a Boolean `provider_pagination_complete` caller claim or **one raw
native GitHub Actions `workflow_runs` API page** with `total_count`. The
raw native format is reduced to exact run attempt ID, workflow name, original
commit SHA, provider event/status/conclusion and recorded timestamps. Actor
information, tokens, arbitrary metadata, commits, payload URLs and raw
provider logs are not copied. An unexpected repository identity or malformed
provider row fails closed.

Example offline CLI, for a locally stored provider JSON page in an
operator-controlled directory:

```sh
python -m brain.soak_inventory \
  --input /secure/provider-page.json \
  --output /secure/soak-inventory-advisory.json \
  --expected-sha f39a8b2ad88b6e1f0db246b586c89a9d611a566c \
  --checked-at 2026-10-14T00:10:00Z
```

The parent output directory must already exist. A new owner-only 0600 advisory
file is created without overwriting or modifying the input. Symlink, output
alias and overwrite paths fail closed. No GitHub API calls are made by the
inspector. It is not part of any existing clock or scheduled workflow and does
not mutate acceptance receipts.

### Strict non-acceptance boundaries

The inspector **always** returns `production_accepted=false`,
`release_authority=false`, `six_hour_source_window_verified=false`, and
false flags for original ZIP, Cloudflare signed origin, mandatory job receipts,
complete provider-run coverage and independent terminal SQLite replay.
Even a native schedule listing spanning more than six hours is **not a valid
six-hour acceptance measurement**: the script labels reported times as
**provider last-update times, not independently verified core job completion
times**. Successful `workflow_dispatch` entries retain origin UNPROVEN,
rather than claiming Cloudflare signed scheduled invocation.

Exact-source failed/cancelled attempts are counted separately and force
`EXACT_SOURCE_FAILURES_REVIEW_REQUIRED`. Other-source runs, pending or
unfinished runs, native push smoke, nonqualifying events and duplicates are
accounted for explicitly. The module accepts at most 250 sanitized run
attempts at once, preserving the original run ID and attempt to avoid
whitewashing failed attempts with successful reruns. Normalized UTC times
ensure fractional timestamps are ordered correctly.

**No V7 deployment, no production source or schedule modification, no
spending/trading, no PR merge, no provider writes, no user notifications.**
A future strict acceptance assessor must independently authenticate *all*
original signed/source-bound artifacts and the terminal original SQLite.
This conservative inventory is not that assessor and cannot certify release.
