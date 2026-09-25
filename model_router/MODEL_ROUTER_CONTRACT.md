# Model Router — Step 13

Portfolio Brain routes intelligence by required capability, not model prestige.

## Tiers

- **Tier 0 — No AI:** deterministic hashing, schema validation, state transitions, aggregation and routine reports.
- **Tier 1 — Low-cost intelligence:** classification, extraction, summarization and simple documentation.
- **Tier 2 — Strong reasoning:** architecture, difficult debugging, cross-project synthesis, experiment design and opportunity reasoning.
- **Tier 3 — Independent adversarial reasoning:** red-team review, consequential promotion verification, self-improvement verification and high-impact audit.

Tier 0 wins whenever deterministic code is sufficient unless the task explicitly requires independent adversarial verification.

## Provider abstraction

The provider registry is provider-agnostic and supports:

- deterministic local execution;
- an approved API slot using an OpenAI-compatible adapter contract;
- future/local self-hosted endpoints.

No concrete API model is enabled in the checked-in registry. The only enabled route is Tier 0. Credentials are referenced only by environment-variable names and no secret values are stored.

A non-Tier-0 provider must be explicitly enabled, compatible with the request's data classification and token ceilings, and have configured pre-call pricing sufficient to prove the maximum cost is within the request's budget.

## Independent Tier 3

Tier 3 requires the builder's independence group. The selected verifier must use a different independence group. If no independent eligible verifier exists, routing fails closed.

This is independent verification, not self-certification. A model result cannot grant authority or upgrade evidence state.

## Cost and outcome learning

Every invocation receipt records provider/model/tier, token usage, cost, cost basis, latency and input/output hashes. Prompt/payload content is not stored in the routing ledger.

Only VERIFIED downstream outcome feedback contributes to routing-value summaries. Unverified model popularity, prestige, confidence or activity does not teach routing value.

## Current activation state

The checked-in provider registry enables only Tier 0. Tier 1–3 are structural integration slots and remain disabled until a later authorized provider configuration is supplied. Step 13 therefore introduces no paid API spend.
