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

## Stable original-source case references (draft extension)

Each private human-review item now receives a **stable 24-hex case reference**
derived from its exact observed Git repository, immutable commit revision and
check name. Unlike the transient review proposal ID, this reference remains
the same when a later check is reobserved or changes outcome **on that same
commit**. It changes for another check, repository or source revision. It is a
deterministic bookmark for operator discussion, **not a persisted incident
record, a ticket, an acknowledgement, a status tracker or an automated action**.

## Cross-repository check-name coincidences (not a causal claim)

Within the original bounded private review packet, the Brain compares only
the **selected** human-review items. If the **exact same GitHub check name**
has been observed as adverse in two or three distinct, original public
repository-scoped check-run references in that one pass, it adds a separate
human-only comparison note. Names can overlap even when underlying workflows
or causes do not. **A same-name coincidence is not a common root cause, a
shared infrastructure incident, impact measurement, or a suggestion to apply
one fix everywhere.** Successful, missing, ambiguous, pending, provider-
unavailable and non-check-run observations never become coincidences.

The comparison note carries an original source-bound case reference and the
static recommendation to independently review the original CI results. The
selection remains bounded to **four evidence-review items per repository,
twelve overall, and at most four same-name coincidence notes**, with any
omitted coincidence groups counted separately. Review order is a deterministic
evidence order, not a business impact or urgency estimate. GitHub-sourced
check names are escaped before private Markdown/HTML rendering.

No additional provider GETs, filesystem state writes, incident resolution,
downstream PR creations, external messages, costs, trading, schedules or
production runtime changes. Only the existing private 0700/0600 evidence bundle
changes on this **unmerged V7 draft**; the optional public sidecar remains
strictly names-free.

### Partial evidence coverage, not skipped investigation

Duplicated GitHub CI check names in either original snapshot are quarantined
individually. A repository can still have a distinct, uniquely named failure
that merits evidence-only human review. The private review packet now exposes
a clear **partial original CI check-name coverage** caveat and the number of
affected repositories. No duplicate-named check is falsely identified as
missing or fixed. Only the previously verified uniquely identified checks
receive proposals; the review packet never certifies full test-suite coverage.

The stable case keys, no-root-cause label, bounded per-repository human
review selection and noncausal cross-project comparisons remain unchanged.
