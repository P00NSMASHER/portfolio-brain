## V7 bounded incident review packet (draft, human-only)

A new private, deterministic review packet translates an already replay-verified
V7 investigation receipt into the next **human** evidence checks. The output
is not a diagnosis, automated repair, permission to merge, or a production
monitor. It runs as a pure local projection while writing the existing
private Markdown/HTML report; canonical machine `report.json` stays identical.

Each selected source-bound check is routed to an explicit manual verification
category: missing/provider-unavailable evidence, changed source, newly adverse
CI, persistently adverse CI, inconclusive completed checks, or observed green
checks awaiting independent corroboration. Historical terminal samples provide
only bounded observation counts, not elapsed downtime or estimated loss.
Stable category instructions are authored by the application and cannot be
replaced by provider check names or web content.

The packet ranks evidence review proposals using a fixed operational ordering,
**not** an estimated severity, root-cause probability, impact, ROI or urgency
deadline. At most four proposals per repository and twelve overall are shown.
It separately counts omitted and deferred evidence so coverage gaps are not
mistaken for completion. The output escapes untrusted names before Markdown,
rejects malformed/unauthorized receipts, and validates source URLs to the
original repository/commit. No extra GitHub GET, mutable cursor, new provider,
software execution, outbound notification, PR mutation, new scheduled task,
trade, paid call, state write or expanded permission is added.

This is a private review section in the existing 0700/0600 protected bundle;
the optional public sidecar still uploads **only its existing sanitized
fixed-label counts**. This feature remains in draft PR #685, based on original
protected V6. The V6 acceptance gate #684, all existing schedules and
protected main remain untouched. No V7 production acceptance is claimed.
