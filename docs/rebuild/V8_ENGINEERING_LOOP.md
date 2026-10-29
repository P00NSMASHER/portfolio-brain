# V8 engineering integration

The engineering mission is useful research, maintenance, repairs and upgrades
across all nine registered projects. Revenue is optional. This increment reuses
the kernel and existing owners; it does not invent an unattended model/API.

## One entry point

```
python -m brain.v8 cycle --input /private/projects/report.json --source-sha EXACT_SHA --cycle INTEGER --now UTC_TIME
```

The existing core optionally runs this after project observation. No new cron,
network request, canonical DB write, permission or external mutation is added.
Its artifact identifies at most five source-bound owner jobs, all-project coverage
gaps and fixed acceptance contracts. Missing project SHA means observe first,
never patch a guessed source. Configured owner role names are routing contracts,
not verified task/runtime identities; original ownership must be rechecked.

## Ten upgrade areas and actual boundaries

| Area | Implemented behavior | Remaining live proof |
|---|---|---|
| Repair execution | Existing deterministic recipe bridge; exact-source generated source/test; old completed repairs reopen on adverse original evidence | A permitted original repair independently released and live verified; arbitrary unattended patch generation remains unsupported |
| Project intelligence | Nine registry-bound source/owner/test contracts; shared repos retain distinct logical identities | Current source, actual owner and deployment coverage for every project |
| Production verification | Owned HTTPS asset probe, redirects refused, bounded bytes, exact digest parity; HTTP200 alone never recovery | Original immutable asset identity and real journey/state verification for each deployment |
| Automation management | Private durable before-image and intent; serialized prompt edit, readback, ambiguity reconciliation and conditional rollback | Authorized persistent private storage and actual Chat-owner/provider integration; no unattended task API presumed |
| Recovery supervisor | Complete-page original run classification; stale work, adverse attempts, retry gaps and live work distinguished | Existing watchdog/provider evidence; no new supervisor authority or schedule |
| Need-driven research | Existing verified-source relevance correction plus project experiments; unchanged failed findings suppressed; uncertain licensing explicit | Independent source/rights/usefulness checks and production benefit |
| Operational memory | Private idempotent outcome persistence, failed/rollback/unknown observations retained | Actual live outcomes require original provider authentication; claimed ACTUAL is not authenticated |
| Isolated testing | Shipped recipe regression runs failing on original and passing after patch; fetched YAML never executed | Real project browser/device/runtime and deployment acceptance |
| Portfolio priorities | Existing mission correction, incident-first equal-tier rotation, unknown coverage explicit, no revenue weighting | Useful upgrades delivered across all projects |
| Runtime consolidation | One owner entry point integrated into existing core; obsolete divergent V7 release candidate retired | Legacy deletion remains blocked by real CI/runtime dependencies and replacement parity |

## Private storage and recovery

`AutomationReconciler` and `record_outcome` require an existing owned private0700
directory with no symlink ancestors. Files/locks are0600, bounded, digest-checked,
atomically replaced and fsynced. One nonblocking exclusive local lock serializes
writers. The API never publishes private prompts or before-images; receipts
contain only allowlisted digests/status. These local files are not a new hosted
service or a claim of persistent runtime volume availability.

Before calling a real provider, the Chat bridge must establish supported private
persistence and bind actual owned task identities. The adapter deliberately
supports prompt changes only. Schedules, enabled state, credentials, trusted
policies and independent verifier controls are outside this adapter. Unknown
provider outcomes are reconciled without automatic retries, even when old state
is still visible. Rollback only applies while live state matches this operation.
The provider has no atomic CAS: a separate actor may still race the final read.

A local file digest cannot authenticate a coordinated rewrite/whole-directory
rollback. Independent trusted checkpoints remain necessary before production
adoption. Current schemas do not grant release authority from caller declarations.

## Verification and rollout

Tests cover malformed identities, source substitution, missing coverage, stale
runs, original failures/retries, matching/mismatched assets, unsafe URLs, duplicate
findings, private permissions, restart ambiguity, idempotence and rollback.
The actual first kernel adoption is PR707/main e6a21892; its preceding six-hour
acceptance binds the old0c3ad0e2 source only. New code needs exact-head independent
checks and its own original production verification; old acceptance is never
inherited. Do not mark the ten areas production-complete from synthetic tests.

This batch integrates the exact reviewed diffs from #696/#697/#701/#703/#704/#705,
with upstream heads recorded in separate commits. #697 original chunk replay and
#701 original-attempt census remain independent audit tools; their inclusion
never lets the producer certify its own acceptance.

Rollback uses a separately tested protected-workflow revert of this integration.
Do not rewrite canonical events, reset state branches, change clocks or suppress
historical failures. Preserve active old paths until replacement is proven.
