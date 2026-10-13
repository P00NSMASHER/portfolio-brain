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


## Public monitor provider-wide circuit breaker (draft-only)

Alongside the single source-revision recheck, V7's future automatic PUBLIC
monitor can now distinguish explicitly repository-local evidence failures
from potentially provider-wide access and API failures. A fixed 404, bounded
check-coverage failure, source revision race or oversized response means
that one repository is unverified; the monitor retains a safe fixed-class
record and may continue to other already allowlisted repositories without
widening the existing 24-GET operation ceiling.

A 403, rate limit, upstream 5xx, network/Unicode/unknown response error,
or other unclassified provider exception instead **stops further public
monitor reads immediately**. The private monitor report counts and lists
source repositories that were deliberately not queried. When a global failure
occurs at the last repository, the report still marks the stop cause even
though no repositories remain to defer. A locally unsuccessful read cannot
be relabeled a successful monitor cycle simply because another public
repository returned data. Original valid observations may still be retained
under the existing V6 monitor's canonical event validation.

Original upstream exception text, HTTP headers, provider error payloads and
private diagnostics are **never copied** into the future V7 automatic
public monitor's operation report or source-error console output. They are
replaced by fixed nonsecret `PUBLIC_MONITOR_EVIDENCE_UNVERIFIED` and one of
`REPOSITORY_LOCAL_READ_FAILED` or
`GLOBAL_OR_UNCLASSIFIED_SOURCE_STOP`. Explicit caller-injected adapters
and private monitoring keep legacy behavior for compatibility.

This is an independent **V7 draft source improvement only**. The protected
V6 monitor, signed source/ledger, existing scheduler and GitHub Actions core
workflow, trading/spending permissions and original acceptance run remain
unchanged. It is not a real incident repair, provider uptime claim or V7
production readiness attestation.
