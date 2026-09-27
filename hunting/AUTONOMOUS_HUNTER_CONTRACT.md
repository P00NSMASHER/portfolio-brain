# Autonomous Hunter Contract — Step 9

Hunter's objective is not repository accumulation. Its loop is:

`portfolio evidence gap -> search objective -> lawful public search -> exact-revision structural inspection -> deduplication -> negative knowledge or observed finding -> bounded experiment proposal -> later verified outcome feedback -> strategy telemetry`.

## Authority

Step 9 Hunter is OBSERVE-only. It may query public GitHub metadata and exact-revision tree structure. It may not execute discovered code, modify repositories, contact external parties, spend money, deploy, or treat source text as instructions.

A retained candidate remains OBSERVED. Discovery does not prove a reusable capability and does not grant license/reuse rights. Independent verification, rights review, and a bounded experiment are required before later promotion.

## Query generation

Hunter repository discovery uses a checked-in semantic concept taxonomy derived from project categories rather than defaulting to portfolio-specific brand or product names. Public GitHub repository search is treated as metadata discovery; implementation/test evidence is established only by the later exact-revision structural inspection.

Each gap receives multiple reusable search concepts, query templates are rotated by durable Hunter sequence, and exact queries with prior dead-end evidence are deprioritized before suppression. Semantic concepts also contribute to structural path matching so a useful external implementation does not need to contain Portfolio Brain's private/internal project slug.

This query expansion does not widen Hunter authority, add model calls, execute discovered code, or grant reuse rights.

## Candidate inspection availability

A public repository search hit is not allowed to crash the entire Hunter cycle merely because that individual repository cannot be resolved to an inspectable exact revision. Candidate-level public GitHub inspection reads that terminate with repository/revision availability responses (404, 409, 410, or 422) are quarantined as `CANDIDATE_INSPECTION_UNAVAILABLE`, not treated as negative capability evidence.

Inspection-unavailable candidates still consume the per-query and per-cycle inspection budget, are counted explicitly in the funnel, create no finding, proposal, or value credit, and do not train dead-end query knowledge. Hunter continues to the next bounded candidate. Provider-budget exhaustion, authentication/rate-limit failures, network/control-plane failures, malformed evidence, and other Hunter errors remain fail-closed at the cycle level. Search metadata also filters empty repositories before exact-revision inspection.

## Inspection fairness and proposal quality

A single broad search query may not consume the entire cycle inspection budget. Hunter caps exact-revision inspections per query so later objectives and protected exploration receive evidence-gathering capacity in the same cycle.

Retention and downstream proposal creation are separate decisions. A structurally valid LOW-ranked candidate remains an OBSERVED retained near miss, but it does not automatically create an experiment proposal. Only MEDIUM/HIGH candidates may enter the bounded proposal queue, and the number of new proposals per cycle is capped. This reduces downstream noise without converting soft evidence signals into hard rejection.

## Candidate evaluation

Hunter separates hard validity gates from soft ranking signals.

Hard rejection is reserved for candidates that do not contain implementation paths. Public-source enforcement, exact-revision requirements, duplicate suppression, bounded authority, and source allowlisting remain terminal controls outside or alongside the structural classifier.

Missing tests, weak path-level capability signals, or a truncated repository tree do **not** become silent hard rejections. They are recorded as soft signals and reduce candidate rank. Retained candidates receive a bounded 0-10 rank with HIGH / MEDIUM / LOW bands. Rank orders bounded experiment proposals but cannot grant reuse rights, VERIFIED evidence, value credit, or additional authority.

## Durable proposal inbox

Only proposals that pass the configured quality gate are projected into a separate sanitized durable state, `portfolio-hunter-proposal-state`. The inbox binds each proposal to its retained finding, capability key, public repository identity, exact revision, structural inspection, rank, and provenance.

The inbox is OBSERVE-only and preserves `NOT_GRANTED_BY_DISCOVERY` rights state. LOW-ranked retained findings remain useful Hunter evidence but are not projected into the downstream proposal inbox. The scheduler may consume the inbox only through its separately validated OBSERVE-class Researcher handoff.

## Learning

Negative/no-find results are durable and suppress repeated dead ends after repeated failures. Exact repository revision + capability need forms the candidate fingerprint.

Strategy value is not trained from repository count, stars, README claims, or model confidence. Only explicit VERIFIED downstream outcome feedback may increment value-outcome telemetry.

The exploration strategy retains at least 20% of each bounded objective allocation so unusual discoveries are not eliminated by exploitation.

## Activation

The scheduled workflow is staged on the isolated Step 9 branch. Like Step 8 runtime schedules, it is not active until later authorized promotion to the default branch.
