# V8 local engineering kernel

This increment provides strict work/capability declarations, incident-first fair
planning, a private local SQLite journal and single-writer resource claims.
It is source tooling, not a deployed autonomous v8 release. It does not call
providers, mutate scheduled tasks, write project repositories, merge or deploy.

## Local commands

```sh
python -m brain.v8 validate --input work.json
python -m brain.v8 plan --input work-items.json --cycle 0 --limit 5
python -m brain.v8 replay --journal /private-owned-directory/kernel.sqlite
```

The journal API creates only explicitly requested new files in a private owned
0700 directory, with mode0600. Replay opens existing v8 journals read-only.
Foreign/production databases, symlinks, hardlinks and shared parent directories
are refused without migration or permission changes. Journal writes use SQLite
transactions, contiguous content-linked records and idempotent operation IDs.
A crash rolls back incomplete local writes; unresolved external intents survive.

Work can advance through OBSERVED, DIAGNOSED, REPRODUCED, PATCHED and TESTED.
Later acceptance/release transitions require independent adapters and are refused
by this kernel. Imported LEARNED records may inform advisory dependency planning;
they are supplied observations, never authenticated release evidence. Capability
records likewise describe supplied declarations, not verified runtime access.
Every CLI result reports LOCAL_V8_KERNEL_ONLY, zero runtime actions and no
production acceptance. Replayed receipts are historical, not a current ownership
or provider-authority grant.

Equal-tier projects rotate using an explicit persisted-cycle input. Critical
incident tiers precede upgrades regardless of rotation. Cyclic, missing and
unfinished dependencies remain blocked. Revenue is not a ranking input.

Claims bind resource, owner, source, action identity and a lease up to3600s.
Expiry alone does not release unknown external work. An original claim holder
must reconcile, complete or explicitly release the claim before unsafe reuse.
Independent provider verification and private automation rollback storage remain
future adapters; no API endpoint or credential is assumed available.

## Verification and next increment

Run `python -m unittest discover -s tests -p 'test_brain_v8_*.py' -v` for source,
transition, fairness, crash/replay, claim-race and hostile CLI coverage. Run the
full existing suite and independent exact-head GitHub checks before adoption.
Original failing-before tests and per-task commits are retained in the review
record. Production source/acceptance remains unchanged by this increment.

Next comes source-bound repair adapter integration, then private automation
reconciliation, research/learning and dependency-proven legacy consolidation.
Do not delete historical state or old execution code merely because this
package exists. The approved design and implementation plan define the scope.

## Review hardening and limits

A fresh read-only branch review found planner complexity, schema allowlist,
truncation, action-identity and foreign-WAL read-side-effect gaps. Reproducing
regressions failed before correction and passed afterward. An additional
concurrent-reader regression reproduced a mixed-snapshot tip mismatch and was
corrected with a single read transaction. Terminal attempts refuse new external
intents while still accepting reconciliation of an existing uncertain action.

The journal now atomically maintains an expected count/hash tip and checks it
against replay. This detects an accidentally truncated surviving prefix; it
cannot authenticate wholesale rollback or coordinated rewriting of the database
and checkpoint. That requires an independently retained trusted tip before
production adoption. Exact schema allowlisting rejects extra tables/views/triggers,
including names that resemble SQLite internal names. Foreign main-file identity
and WAL mode are checked before opening SQLite. WAL journals are unsupported and
refused; this local v8 format uses rollback mode only.

Local verification: 40 focused tests PASS; full suite1943 tests PASS,2 platform
skips, exit0. These are source-level observations, not production acceptance.
