# One durable PASS checkpoint per complete core cycle

Only production core steps explicitly setting `BRAIN_CYCLE_COMPACT_REPORTS=1` use compact mode. Standalone/manual callers retain the original durable-report behavior. The monitor/research PASS reports are deterministic recomputable projections
over the original canonical event/attempt ledger. Persisting all three full
versions per 30-minute core cycle was growing raw SQLite by several hundred
kilobytes per run even when no useful new integration was released.

The existing GitHub Actions run artifact retains `monitor/report.json`,
`research/report.json`, and the final `experiment/report.json` as separate
source-bound output records. The final PASS report remains in the canonical
SQLite `reports` table; the existing `doctor` replay checks still require
that final report, fresh source identity, complete operation attempts and
zero event backlog. Every report with non-PASS derived status remains durable
even if a caller requests preview mode.

New canonical records are not removed. No change to the append-only
`events`, `ledger`, `attempts`, failures, publication safeguards or
protected main rules. Prior reports already committed in Git history remain.

Evidence motivating this bounded change: on protected commit
`ac9811fb4c04d00ff8749833d9e0f400248a563f`, original core artifacts
42080072384, 42084876548, 42089686825 contained **three** full
~245–250 KB JSON reports per cycle; the 19:00 cycle increased raw state by
634,880 bytes and compressed state by 135,274 bytes. The claimed production
reduction must be verified against original post-release state artifacts:
this code change is not itself proof of saved capacity or business value.
