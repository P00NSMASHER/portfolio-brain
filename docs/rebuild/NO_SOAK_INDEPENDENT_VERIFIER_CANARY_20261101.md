# No-Observation Independent Verification Canary (2026-11-01)

This documentation-only change is an ordinary PR created against protected
`main` after PR #821 was merged as
`d020c2643a2bea60e4866914fce7777dc4b62536`.

## Purpose

Demonstrate the new release path, without restarting any observation or
providing a historical acceptance receipt:

- The unchanged Foundation CI issues `validate` from App 15368 on the exact PR head.
- The *protected-main* independent verifier executes isolated full, Phase 1,
  and operating-mode checks, validates exact-head and current-main ancestry,
  and issues `portfolio-phase1-gate` from App 5121826.
- Branch rules continue to require both issuer-pinned checks. A failed or
  absent independent check cannot be represented as successful.
- No `PORTFOLIO_12H_*` setting, elapsed time, observation workflow, fabricated
  receipt, rule bypass, or source-acceptance producer is involved.

## Evidence

Evidence must come from the real GitHub Actions jobs and Checks API for this
PR, not from this document. The check status is intentionally **not claimed**
inside this proposal. Verify the issuer IDs, job test outcomes, and check
head SHA before declaring the downstream release path validated.
