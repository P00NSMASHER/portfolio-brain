# Unattended operation, restart, and recovery

The scheduled main-only workflow restores `brain-state-v2/state.sqlite`, verifies it,
executes exact-SHA tests, observes sources, researches, experiments, diagnoses state,
and publishes one verified non-force state commit. It does not launch a soak.
It requires an initialized dedicated state branch; missing state fails closed instead
of silently substituting an empty database. Report artifacts include exact source,
run, attempt, state parent, delivered commit, canonical hash and pending count.

## Accepted v4: operator handoff (October 8, 2026)

V4's six-hour production acceptance is **terminal PASS** for protected main
`9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`. The sole authoritative
acceptance record is
[`brain-acceptance-v4/acceptance/finish-soak-v4.json`](https://github.com/P00NSMASHER/portfolio-brain/blob/brain-acceptance-v4/acceptance/finish-soak-v4.json)
at terminal commit `b1b9f63dc8136f259abdc1b9ad18fcd47cf3b681`.
Historical v2 FAIL and v3 BLOCKED remain separate and immutable.

- **Actual core:** `.github/workflows/brain-cycle.yml` has native GitHub cron
  `7,27,47 * * * *` UTC and serializes state publication on
  `brain-state-v2/state.sqlite`. Verify the completed core and mandatory
  monitor, research, experiment, doctor and nonforce state-delivery steps.
- **Native watchdog:** `.github/workflows/brain-clock.yml` uses
  `16,36,56 * * * *` UTC; a green watchdog by itself is not a completed core.
- **Independent recovery clock:** Cloudflare Worker `portfolio-brain-recovery`
  runs `*/10 * * * *` UTC and avoids duplicate cores after recent same-source
  success. Provider result `FRESH` means no new dispatch was needed.
  `DISPATCH_ACCEPTED_NOT_COMPLETED` means only that a request was accepted;
  look up the child GitHub core and validate its signed origin and completion.
- **State/health:** For each material issue, check protected main SHA, actual
  provider event, recent GitHub core jobs (including failures), artifact ZIP
  SHA256 and `delivery.json`, nonforce state commit parent, doctor sequence
  and canonical chain, and pending events. Never infer availability from
  configured crons alone or overwrite historical state to manufacture a pass.

The v4 record counts 14 Cloudflare cycles with independently verified original
provider logs and matching P-256 origin receipts, from 13:50:59Z to 21:50:51Z
on October 8 (28,792 seconds; largest accepted gap 3,625 seconds).
All 18 core attempts in that window completed successfully. Three signed jobs
at 15:20, 16:20, and 18:50 UTC lacked retrievable **original Cloudflare
provider event logs** and are explicitly **successful but nonqualifying**;
one additional GitHub-native scheduled core is also inventoried separately.
Do not relabel unavailable provider logs as verified, and do not erase those
successful nonqualifying runs. Every original ZIP SHA256 and durable state
parent was checked, with zero pending events.

Final independent raw SQLite verification, performed on the exact terminal
state commit `f2fb6ffd4f4a3cfd979c6ce28b990b9ad8379b05`, passed the
210-event hash chain, SQLite integrity, foreign keys, report and backlog in
[Foundation CI run 37850145136](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37850145136).
The separate [independent hosted verifier](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37850298010)
passed its code checks; its intentionally network-disabled raw-transport
skip is **not** the evidence for the binary replay.

**Release boundary:** Never alter the accepted v4 record, restart its clock,
or infer that a future source inherits this PASS. Draft evidence-only
[PR #655](https://github.com/P00NSMASHER/portfolio-brain/pull/655) must
remain unmerged unless separately authorized. A new source candidate must
follow the existing protected exact-head CI, independent verifier,
controlled integration, and a **new acceptance version**, not rewrite v4.
Continue existing production reliability tasks with their current schedules
and notification settings; diagnose failures without silently disabling
workers, changing credentials, or weakening gates.

Requests are GET-only for source acquisition, capped24 per operation, ten-second
timeouts, one bounded retry for429/502/503/504 with retry delay at most two seconds.
No full-preflight speculative retry loop exists. A source failure preserves successful
other observations but fails full monitored coverage. The next scheduled cycle starts
from durable acknowledged state and drains interrupted input. Last failure remains
visible in attempts. Optional knowledge-upgrade failure is BLOCKED without discarding
core observations. Authentication/rate-limit/provider outage is never renamed success.

Knowledge proposal delivery uses narrowly scoped repository contents, pull-request,
and Actions permissions. After creating a fixed-file candidate PR, it dispatches
the existing Foundation workflow exactly once on that candidate branch. Token-created
PR events can require workflow approval; the explicit dispatch avoids depending on
that event for validation. The unchanged independent verifier still binds and checks
the actual head and alone merges eligible bot candidates through main protection.
API failures expose sanitized status/endpoint evidence and leave the proposal
unaccepted. Repository policy may still refuse bot PR creation; permissions do not
override that policy. Failed attempts retain the weekly new-proposal cooldown.
A recorded interrupted proposal may resume once after at least one hour, only for
the identical evidence fingerprint and unchanged source main. Recovery verifies
branch ancestry, the sole changed knowledge file, exact content and bot PR identity;
it reuses the branch/PR and delivers the missing validation dispatch. A second
failure, different evidence or main drift cannot create a rapid retry loop. Legacy
orphan proposals without the new recovery receipt remain blocked/inert evidence.

## Local continuous process on an existing host

```ini
[Unit]
Description=Portfolio Brain read-only intelligence
After=network-online.target
[Service]
WorkingDirectory=/path/to/portfolio-brain
ExecStart=/usr/bin/python3 -m brain service --db /private/brain/state.sqlite --output /private/brain/reports
Restart=on-failure
RestartSec=60
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
```

This is an installation example, not a deployed host or new paid service. Bind the
checkout to an accepted commit, set file access appropriately, and use an existing
service manager. The CLI checks source SHA before every cycle; code changes require
a process restart. Create a `STOP` file beside the database for a clean stop; normal
SIGTERM interruption also rolls back an open transaction safely. GitHub schedules
can be delayed or paused by provider/repository conditions, so nonstop availability
is not claimed.

## Recover current state

1. Stop concurrent writers or wait for the serialized GitHub owner to finish.
2. Preserve the failing database and commit identity; do not overwrite evidence.
3. Restore the last verified `state.sqlite` from the dedicated branch's immutable
   commit history, or `python -m brain backup --db ... --output backup.sqlite`.
4. Verify SQLite integrity and use `Store` to verify event IDs, content, contiguous
   sequence and chain. Drain pending work, then generate a new exact-source report.
5. Rerun complete monitor → research → experiment → doctor. Compare expected sequence
   and canonical hash; missing acknowledged input or uncertain lineage stays BLOCKED.

A corrupt canonical event is not automatically deleted. Snapshot corruption may
be repaired by generating a new report from verified ledger facts; report reads
never accept a corrupt old projection. Loss of the authoritative branch or secrets
requires external restoration; no honest software can guarantee otherwise.

## Restore original implementation

Create a recovery branch from exact preserved Brain commit
`f0814f55fb5abf83135181d447171fb45d01933c`, verify its tree
`e3306d6608608e6d2771914399f6e3cdb4b34243`, compare it with the replacement, and use
protected reviewed integration. Do not reset/force-push main, erase history, change
credentials, or replay old paid schedulers blindly. Old Step23 evidence remains
blocked by issue640 unless GitHub actually repairs the provider record.

## External clock fallback (GitHub cron delivery outage)

Native `17 * * * *` remains configured. GitHub documents that scheduled events
may be delayed or dropped. An active workflow is not delivery evidence.
The existing hourly Portfolio Brain Reliability task owns the fallback clock;
no new account, credential, service or automation subscription is introduced.
When there is no successful current-main core cycle within 45 minutes and no
active core run, it publishes at most one `clock/pulse.json` per UTC hour on
`brain-clock-v2`, using a nonforce expected-parent update. The branch tree is
copied from the current protected main, changing only this nonsecret receipt.
The receipt contains exactly schema_version=1, source_sha=current main,
issued_at=UTC timestamp, slot=YYYYMMDDTHH, producer=the existing reliability
job ID, and kind=scheduled (only inside an actual scheduled task execution)
or manual_probe (operator demonstration). A retry must not create another
signal for the same slot. Do not refresh a failed receipt to hide its age.

`brain-clock-v2` validates the receipt with code checked out from protected
main, refuses stale/future timestamps and source drift, and requests exactly
one dispatch of `brain-cycle.yml` at main. A request accepted by the API is
not a completed workload. The core independently validates the immutable
receipt again and includes clock.json in its actual execution artifact.
The optional clock gate is absent on native cron/push runs; every existing
mandatory core gate remains required. No source change is needed per pulse.
The normal core concurrency and nonforce state publication remain authoritative.

A fallback automatic acceptance cycle must have an actual scheduled task
execution, immutable kind=scheduled receipt, successful clock job/artifact,
and the associated successful workflow_dispatch core run/artifact containing
that same receipt. Manual probes never count as automatic delivery. Native
cron gaps remain recorded; fallback proof must be labelled external scheduling,
not event=schedule. Require three automatically delivered complete cycles on
one unchanged main over at least two hours, gaps at most 90 minutes, all
failures accounted for, existing freshness/lineage/replay/zero-backlog gates,
and post-soak validation. Invalid dispatches or provider failure are preserved
and diagnosed without rerun loops. There is no guarantee of uninterrupted
availability from either hosting provider.

## Historical v3 redundant native delivery (superseded by v4)

The earlier v2 hourly cron/ChatGPT fallback missed a complete automatic cycle for more than 90 minutes and was recorded FAIL. The governed v3 candidate preserves existing ledger and gates while replacing the sparse scheduler with two *GitHub-native* crons declared in `brain/POLICY.json`. The primary runs full core on main every 20 minutes. The offset watchdog reads GitHub's actual recent core runs and only dispatches a missing core after 35 minutes, never changing state or source. It fails closed on stale active writers and records decisions. The core re-verifies that the watchdog's origin was a real GitHub `event=schedule` parent run, and its artifact retains the exact parent metadata. A separate acceptance verifier must authenticate both parent and child, and cannot count a manual request or a scheduling intention as a successful automatic run. More frequent GitHub Actions use and state growth must be measured after release. No new paid services or credentials are assumed.
