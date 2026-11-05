# Verified operational raw-state capacity and measured engineering result

Date: November 5, 2026. Repository: `P00NSMASHER/portfolio-brain`.

## Backend capacity proof

- Original raw limit: **120,512,512 bytes** (October 16 production-state qualification).
- The isolated GitHub [backend test](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/42076693102) completed successfully on protected source `246d7260d7bf610f0f5bc3a31180ecf517dd9ddb`.
- Synthetic canary Git branch: `brain-capacity-canary-180mb-20261105`.
- Independently read back immutable canary commit `3ca5f50852b8e582a427a148e0e74b38ea9e5ed5`.
- **180,043,776 raw bytes** packed into **376,871 compressed bytes**, committed and checked out through actual GitHub. A separate job restored and replayed SQLite and verified the exact source.
- The approved new raw envelope is **180,000,000 bytes**, conservatively below the original canary's restored raw size.
- The independently established compressed production ceiling **20,602,941 bytes** is unchanged; the raw allowance never bypasses this independent limit.
- The probe used synthetic data. It did **not** certify arbitrary future compressed images or modify `brain-state-v2`. Full production state publication and original-run readback remain required.

The raw-size compaction trigger is 75% of this independently qualified bound (135,000,000 bytes); the separate compressed trigger and report-count trigger remain effective. This removes repeat vacuum/compaction work on a stable roughly 105 MB database without suppressing new source records or deleting canonical history.

## Independently measured short-window engineering outcome

- Operator-discovered issue: fast growing public SQLite state.
- Reviewed and independently gated repair: [PR #865](https://github.com/P00NSMASHER/portfolio-brain/pull/865); merged commit `dbd548034c6002009098c1cab9bee3aa65a64bdb`.
- Source-bound reference snapshots and original Git commits are recorded in `repair/V11_TECHNICAL_OUTCOME_CASE.json` and verified by `brain/v11/technical_outcome.py` each time the read-only result dashboard runs.
- Before: raw database +1,200,128 bytes between 12:22:56 and 16:22:25 UTC (**+300,679 bytes/hour**).
- After: raw database -24,576 bytes between 16:28:09 and 17:03:09 UTC (**-42,130 bytes/hour**). Compressed bytes increased over that short interval; do not claim universal savings.
- These are **actual immutable Git state-manifest measurements** linked to the exact reviewed release. They do not establish causality, longer-term sustainability, money saved, customer revenue, or third-party discovery integration.
- The dashboard still holds those unverified outcomes as **UNKNOWN**, rather than treating a PR or simulation as revenue.

Acceptance requires exact-head Foundation `validate`, independent App `portfolio-phase1-gate`, protected merge, successful original post-merge core publication/readback, and the original read-only dashboard emitting a valid measured technical outcome rather than an unavailable placeholder.
