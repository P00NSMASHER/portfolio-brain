# Post-repair reliability observation

The `brain-24-hour-reliability` workflow observes the final protected-main source after each scoped repair completes. It has read-only GitHub permissions and cannot publish an independent acceptance decision or change state.

It replays original core artifact digests, state publication ancestry, required job steps and automatic scheduling provenance through the existing source verifier. It requires at least 86,400 seconds between qualifying monitor completions, gaps no larger than 5,400 seconds, original attempts only, and matching original repair origin receipts. Pending work remains COLLECTING; failed or retried originals cannot pass. Reports are retained as workflow artifacts. A successful workflow with COLLECTING is not a passed 24-hour test.

The observation uses a fixed completed-run snapshot and a bounded first 24.5-hour core window. Repair artifacts are bounded to terminal completion plus 30 minutes. Limits remain explicit and fail closed: 100 core runs in the window, ten inventory pages, 656 API calls. Exceeding capacity is incomplete verification, never truncated PASS. Current production cadence is approximately one core every 30 minutes. This is an operational observation, not proof of unlimited capacity, independent human review, or unrestricted autonomy. Existing independently credentialed six-hour acceptance remains separate.

## Failure recovery validation

- Transient read transport failures: at most three attempts, with bounded delay and timeout.
- Authorization denials, invalid JSON and admission failures: no silent retry or token issuance.
- Diagnostics: static nonsecret error codes; no provider bodies, credentials or arbitrary exception text.
- Durable queue crash: persisted INTENT survives reopen and blocks duplicate external writes after lease expiry.
- Existing full regression suite covers growing complete check history, shared request capacity, source drift, state delivery readback, conflicting writers and interrupted state operations.
- Observer tests cover full/short windows, gaps, pagination, pending cores, original failures, repair reruns, exact origin coverage and out-of-window budget isolation.

Two definition-only private dashboard helpers were removed. Archived workflow fixtures remain because active historical validators verify them. The backlog audit records exact-head dispositions rather than age-based deletion.

A final source change starts fresh evidence. The 24-hour result cannot be marked complete until actual unattended elapsed-time and follow-through evidence pass.
