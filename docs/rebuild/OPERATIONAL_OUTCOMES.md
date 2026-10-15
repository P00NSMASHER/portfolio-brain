# Original workflow outcomes

`brain.operational_outcomes` measures a complete bounded GitHub main-branch
workflow run inventory for Brain, ABVM, RETALLY and App Factory. It performs
GETs only, using the existing public GitHub adapter and its 24-request total
limit including transport retries. Each project binds main before and after
the scan; changing main, duplicate IDs, malformed results, changing totals,
missing pages and histories exceeding three 100-row pages fail closed.

```bash
python -m brain.operational_outcomes \
  --project portfolio-brain --project abvm --project retally --project product-factory \
  --start 2026-10-15T22:30:00Z --end 2026-10-15T23:30:00Z \
  --output /tmp/brain-workflow-outcomes
```

Run explicit windows of at most seven days; use narrower windows when the
provider returns too many runs. No extra service, paid provider, new credential,
scheduled task, workflow or canonical database write is installed. Caller-supplied
callbacks remain explicitly unauthenticated input; only the bundled CLI identifies
its original HTTPS transport. Source URLs and canonical response digests permit
separate review, but are not an immutable archived GitHub response or signature.

The fraction is successes divided by successes plus adverse terminal outcomes,
excluding pending, neutral, skipped and PR-triggered runs. These exclusions are
reported separately. A green rerun makes the fraction unknown until original
attempt history is audited; earlier failures must never disappear. No runs means
unknown, not 100 percent. Workflow success measures workflow execution only:
it cannot establish production uptime, six-hour acceptance, meaningful repairs,
school content freshness, real users, buyer value or revenue. All such unmeasured
fields remain null. Per-workflow paths and source revisions are retained so a
reviewer can distinguish build checks from genuine workload observations.

The transport never reads schoolwork, student names, email, payment records or
analytics identities. It retains only bounded public workflow identities and
conclusions, not provider titles, actors, logs or payloads. Ingesting commercial
outcomes still requires a separately reviewed authoritative adapter and actual
baseline/results; this module supplies technical outcome evidence only.

Production source remains frozen during its current acceptance window. This
candidate must pass full source checks and the independent App gate and remain
draft until the governed release hold clears. It grants no merge/deploy authority.
