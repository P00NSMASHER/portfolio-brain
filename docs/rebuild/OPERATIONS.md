# Unattended operation, restart, and recovery

The hourly main-only workflow restores `brain-state-v2/state.sqlite`, verifies it,
executes exact-SHA tests, observes sources, researches, experiments, diagnoses state,
and publishes one verified non-force state commit. It does not launch a soak.
It requires an initialized dedicated state branch; missing state fails closed instead
of silently substituting an empty database. Report artifacts include exact source,
run, attempt, state parent, delivered commit, canonical hash and pending count.

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
override that policy. Failed attempts retain the weekly cooldown; no rapid retry
or acceptance reset is implied by repairing code.

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
