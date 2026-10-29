# PR #742 reconciliation — October 29, 2026

Port the repeated original-provider evidence checks from #742 onto the current
GitHubOriginalReader API. Do not replace the bounded transport with the older
callback API. Retain repository/route allowlists, redirect refusal, response-byte
limit, duplicate-key rejection, credential handling, and shared GET budget.

Draft-only reconciliation now uses four GETs: main, PR, PR, main. Check-bound
reconciliation uses six: main, PR, checks, checks, PR, main. Any difference between
repeated documents is a failure; exhausting the existing request budget is a
failure. This conservative comparison may reject harmless metadata changes.
Repeated reads detect observed changes; they cannot make remote snapshots atomic.
Neither result confers merge authority or unattended production acceptance.

The old proposal's hardcoded human-author restriction is not ported: the current
protocol supports automated draft authors and binds repository, candidate, base,
PR identity and an exact operation-marker line. This change does not add an
alternative authorization route. Current issuer-pinned success checks remain.

Tests cover PR mutation, check reruns and adverse changes, budget exhaustion,
wrong source, missing marker, issuer mismatch, duplicate checks, and main drift.
The active scheduler/12-hour observation remains owned by the other chat; this
candidate must not auto-merge during that observation.
