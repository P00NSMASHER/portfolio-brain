## V7 bounded monitor retry for source-branch movement (draft-only)

### Observed failure

The original protected V6 scheduled run
[#38468439594](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38468439594)
on October 13, 2026 failed in its original read-only public monitor step.
The observable reason was `SOURCE_REVISION_CHANGED` for the allowlisted
`P00NSMASHER/github-value-hunt-ledger` repository: its default branch
had moved between the initial GitHub branch lookup and the final
post-check-collection branch verification. The original monitor correctly
did **not** persist the non-atomic check snapshot.

### V7 candidate behavior

When (and only when) the **automatic public monitor** receives the exact
fixed `SOURCE_REVISION_CHANGED` error from the existing original
`GitHub.observe` source-identity contract, it may make **one** fresh
full observation of that repository. This restarts at metadata and branch
lookup, fetches the matching SHA's complete bounded check pages, and
reverifies the branch HEAD. Partial original results are discarded.
No first-attempt source event is created.

The retry is allowed only while **at least 16 GET requests remain**
inside the existing **24-GET operation ceiling**, enough for an entire
worst-case source observation (metadata, two branch reads, up to five
check pages, each with its existing single bounded transient retry).
It does **not** retry when the budget is insufficient, when the
second branch changes again, or on any other failure (auth, rate-limit,
private source, check-coverage ambiguity, transport, malformed content).
No third attempt or new background scheduler is introduced.

A complete second observation can persist **one** originally validated
public repository event with its final exact commit SHA; successful
rechecks are enumerated only in the *transient private monitor operation
report* as `source_revision_rechecks`. On failure the monitor continues
to fail as before, with no incomplete source event admitted. Explicitly
injected APIs and private monitor configurations retain the original
one-shot fail-closed behavior.

### Boundaries and acceptance

The change exists **only in the open V7 draft**. Protected V6 main, original
scheduled GitHub Actions core steps and Cloudflare source signatures remain
untouched. The original V6 signed six-hour acceptance issue
[#684](https://github.com/P00NSMASHER/portfolio-brain/issues/684)
is neither waived nor restarted. Synthetic tests prove one successful
race recovery, persistent second race fail-closed, 16-GET worst-case
headroom enforcement, 500-check bounded pagination, non-race error
fail-stop, stable default 4-GET behavior and preserved explicit-API
semantics.

These source-quality tests do **not** prove a production retry has run,
a real incident was fixed, or a new source-specific soak passed.
A future V7 promotion requires separate authorization and its own
genuinely signed production acceptance. There are no new GitHub writes,
customer messages, trades, spending, paid calls, private tokens,
cron changes or third-party code execution.
