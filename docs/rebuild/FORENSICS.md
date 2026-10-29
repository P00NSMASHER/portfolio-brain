# Forensic inventory and preservation

Canonical runtime repository: `P00NSMASHER/portfolio-brain`, source main
`f0814f55fb5abf83135181d447171fb45d01933c`, tree
`e3306d6608608e6d2771914399f6e3cdb4b34243`.
Verified recovery ref: `recovery/pre-rebuild-20261007-f0814f5`.

Separate historical market-surveillance research: `P00NSMASHER/trading-platform`,
source main `6f7710512e6ac2f86e8cb12ad233a08980cf0220`, tree
`2157e4962617716a3134ada455f469d1e02bad7e`.
Verified recovery ref: `recovery/pre-rebuild-20261007-6f77105`.
Trading-platform code, datasets, workflows, and PRs are untouched by the replacement.

The refs anchor immutable content-addressed commits and their complete ancestor
history. A branch ref itself is mutable; it is not falsely called an immutable tag.
Recovery uses the recorded exact commit, not merely whatever a branch later points to.
A complete Git history bundle was also generated and `git bundle verify` passed.
All original configuration and checked-in nonsecret state remain at the preserved
commit; credentials and provider secrets are not copied or changed.

The audit read architecture/status documents, actual registry and adapter contracts,
active workflows, Step23 preflight/reducer/doctor code, state journal and regression
cases, main protections, open PR inventory, and the issue640 failure package.
The prior product was software-project portfolio orchestration. Its historical
OPERATIONAL assertions do not prove the later September30 remediation succeeded.

## Retired active components

`legacy/WORKFLOW_ARCHIVE_MANIFEST.json` enumerates40 original workflows and their
SHA-256 hashes. They moved outside GitHub's active workflow directory. This removes
hourly sync/daily/weekly learning chains, Hunter, agent heartbeat, scheduler, paid
worker/model proof, notification, cost watchdog, reducer/checkpoint candidates,
repair/factory workers, clock daemons, delivery probes, bootstrap loops, and old
Step2–23 proof/soak orchestrators from active execution.

Their implementation packages and historical ledgers remain inert recovery evidence
and offline regression fixtures. Physically moving hundreds of code files would
exceed the unchanged independent verifier's300-file compare bound and break useful
historical tests. The active package imports none of that runtime architecture.
Archive fixture lookup is explicit; original GitHub provenance strings remain intact.
Historical operating-mode validation is labelled historical, while active validation
checks the replacement's actual inventory and authority.

Retained active workflows: Foundation and the independent verifier (required protected
merge controls), two unrelated x402 product CI workflows, and the single Brain cycle.
Both verifier trust-anchor files are byte-identical. Main still requires exact-head
`validate` from App15368 and `portfolio-phase1-gate` from App5121826, strict current-main
ancestry, resolved review threads, and a PR, with no bypass actors.

## Old run37655516971

Fresh API inspection returned `queued`, `conclusion=null`, exact obsolete source
`18f3e3d5a9b3b8c9a3e64e118a7cd487a3551edb`, unchanged updated timestamp, zero jobs.
Issue640 records previous cancellation/force-cancellation and DELETE403 attempts.
It remains unresolved and no Support submission is claimed. No deletion/terminal/
success assertion is made. The new engine never reads legacy artifacts or shares
its writer lock; an old run later executing cannot write the new SQLite authority.
Legacy acceptance remains blocked. This is not a bypass of the replacement's own
freshness, durability, protected-merge or live-delivery checks.

## Historical validation diagnosis

Archival initially exposed15 path-fixture errors in1369 historical tests; explicit
archive lookups corrected them without deleting regressions. A second run found one
persistent-cache isolation failure; that test now uses its own temporary cache.
Focused security21, timeout10, and reader9 tests passed. Final full-suite and new-core
results are recorded with actual source commits in delivery evidence, not inferred
from this historical diagnosis.
