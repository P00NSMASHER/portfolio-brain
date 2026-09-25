# Continuous Observation Runtime — Step 8

The Step 8 runtime is autonomous infrastructure, not an interactive ChatGPT loop.

## Execution modes

- `observe`: event-driven observation of one declared repository.
- `sync`: hourly observation of all enabled repository adapters.
- `daily`: synchronize sources, then rebuild a deterministic learning-state snapshot.
- `weekly`: synchronize sources, then produce a deterministic portfolio synthesis.

## State persistence

The checked-in exact-SHA cursor file is the bootstrap baseline. Each successful runtime cycle emits a sanitized `runtime_state.json` as the GitHub Actions artifact `portfolio-runtime-state`. The next cycle restores the newest non-expired artifact and advances only after successful observation receipts.

Artifacts are operational continuation state, not truth evidence by themselves. If artifacts expire or are unavailable, the runtime safely resumes from the checked-in baseline and replays only SHA deltas.

## Authority and safety

- GitHub workflow token permissions are `contents: read` and `actions: read`.
- No workflow has repository contents write, PR write, deployment, issue, package, OIDC, or customer-system authority.
- Downstream repository adapters remain OBSERVE-only.
- `REPO-006` remains disabled by `BLK-001` and performs zero reads.
- Model calls are prohibited in Step 8.
- All four autonomous triggers share the same serialized concurrency group.
- Per-cycle repository/API/file/output/time budgets are finite.
- HTTP reads use bounded retries.
- A repository variable `PORTFOLIO_RUNTIME_DISABLED=true` or the checked-in file kill switch disables execution.
- Runtime output is sanitized metadata/references only while this repository remains public.
