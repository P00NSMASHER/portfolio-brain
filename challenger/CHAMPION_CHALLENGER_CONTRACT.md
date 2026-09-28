# Champion/Challenger Contract

Portfolio Brain evaluates external architectures and candidate policies through a fail-closed shadow pipeline:

`discover → rights/evidence verification → isolated adapter → historical replay → challenger metrics → forward canary → human promotion review`

## Non-negotiable boundaries

- Discovery never grants reuse rights.
- Exact source revision must remain bound through rights and adapter evidence.
- Candidate code may not mutate production during evaluation.
- Historical replay is shadow evidence only and cannot promote a candidate.
- Challenger metrics are transparent per-metric comparisons; no opaque composite score is permitted.
- A forward canary must remain shadow-only with zero authority violations and zero forbidden actions.
- Passing every automated gate yields only **eligibility for human promotion review**.
- Automatic promotion, active-policy mutation, merge, deploy, payment, live trading, and authority expansion are outside this pipeline.
