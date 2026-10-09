# Balanced evidence selection for Portfolio Brain knowledge upgrades

This is an **offline source-selection enhancement**, not a new autonomous
workflow or a release of production Brain source. The proposal is based on
the v4-protected main baseline and is separate from V5 integration PR #661.

## Existing problem

The bounded knowledge upgrade selects the alphabetically first twelve
eligible source keys. If many candidates are discovered under an early
repository or path prefix, one project can occupy all twelve slots even
when there is already independently observed eligible evidence for other
configured business project targets.

## Deterministic selection contract

1. **Do not change qualification.** `build_knowledge()` still requires a
   passing canonical report, actual and current candidate, implementation
   plus structurally related test path, and at least two matched terms.
   The preexisting minimum of three eligible sources still applies.
2. **Preserve each candidate's original inspected evidence.** No inferred
   license rights, code execution, measured savings, causal claim or
   downstream deployment is produced by this selection.
3. **Balance by target only after qualification.** Sort eligible project
   targets and each target's candidate keys ascending. Select one from
   each target per round; continue until the twelve-source ceiling or
   the eligible list is exhausted. If only one target has sources, the
   output matches the previous alphabetical-key selection.
4. **Backfill unused capacity.** A project with just one or two eligible
   sources never prevents another project from filling remaining slots.
5. **Stable and bounded.** Input-order permutations yield identical
   selected source order and the same existing SHA-256 fingerprint.
   Nothing changes the `REUSE_KNOWLEDGE.json` schema, one-proposal-per-week
   limit, mutation endpoint allowlist, independent verifier, GitHub
   policies, budgets or runtime schedule.

## Boundaries and acceptance

- Scope: `brain/upgrades.py` source selection plus isolated
  `tests/test_brain_knowledge_diversity.py` adversarial tests.
- Production is unchanged until a separately authorized protected
  source integration and new acceptance. V5 integration PR #661 and
  contributing source PRs are **not** modified.
- Run the full existing Foundation regression suite and independent
  exact-head App gate on this draft branch. Green tests demonstrate
  candidate source quality, **not** verified production adoption or
  customer value.
