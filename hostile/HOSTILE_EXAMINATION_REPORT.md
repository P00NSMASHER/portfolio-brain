# Step 23 Hostile Examination Report

Step 23 attacked Portfolio Brain as if public repositories, persisted artifacts, internal request fields, metrics, graph claims, and autonomous work packets could be malicious.

## Findings fixed in Step 23

1. **Graph capability poisoning:** Hunter and the uncertainty engine previously treated any active `HAS_CAPABILITY` edge as coverage. An INFERRED/UNKNOWN edge could therefore hide a real capability gap. Both engines now require a VERIFIED capability node and VERIFIED edge.
2. **Verified graph provenance laundering:** a graph record could claim VERIFIED with arbitrary provenance text. VERIFIED nodes and edges now require a CI/event/evidence/verification anchor.
3. **GitHub workflow-command injection:** notification entity text was interpolated into Actions commands without escaping. The sink now sanitizes fields and escapes command data.
4. **Retry identity reset:** cost requests could rename a retry group and restart the attempt sequence. Model and GitHub execution retry groups/idempotency are now bound to their routed/run identities; generic API operations must provide one stable operation identity.

## Existing controls survived hostile examination

Prompt injection/malicious public repositories remain data-only in Hunter; private repositories fail closed; unverified reward signals cannot train value; builders cannot self-verify; circular evidence fails; agents cannot obtain ACT; disabled model providers fail closed; cost overages/kill switches hard-stop execution; private-reference state rejects raw payloads; the factory cannot merge/deploy; customer communication is no longer globally prohibited but remains non-executable without an explicit bounded channel executor; child-facing consequential changes remain approval-gated; and PRJ-007 remains research-only with trading/broker execution prohibited.

Every scenario in `hostile/ATTACK_MATRIX.json` is permanently tied to a regression or invariant. No recurring autonomous workflow is activated by Step 23.
