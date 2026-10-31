# 2026-10-31 owner-activated 12-hour repair (review candidate)

## Source and user decision

- Previous source: 2b4fb0566938f32ef49deda2f056d1a766ab1d88.
- User explicitly STOPPED the active 12-hour attempt at approximately 2026-10-31 10:27 UTC and requested real code repairs before a new window.
- Old observation 41191831937 and producer 41191819420 are retained as original, non-final evidence: the original observer recorded 19,810 seconds of earlier source history, but the user's first active observer ran at 10:12:54 UTC.
- User-controlled GitHub variable PORTFOLIO_12H_OBSERVATION_ENABLED must be set to false by a repository admin to physically stop the old observer. GitHub connector cannot mutate repository variables. Do not claim the GitHub jobs have halted without source-run evidence.
- This PR contains source code and synthetic tests ONLY; it makes no GitHub variable changes or starts a new window.

## Defect fixed in candidate

The old reliability observer and receipt producer anchored the 12-hour count at the first automatic core after deployment, which could be hours BEFORE the user turned on the two repository variables. The original full-source state chain is valuable for integrity, but it must not earn post-activation time.

This PR introduces a read-only GitHub-evidenced owner activation record:

1. Exact trusted source SHA and original workflow path .github/workflows/reliability-day.yml.
2. First original completed SUCCESS observer job named observe, exact run ID, status, source SHA, attempt 1, and workflow_run trigger.
3. The original observer can use its own verified in-progress job as a provisional first marker. Producer and independent verifier require a completed original SUCCESS job.
4. Source deployment and earlier core jobs remain included for full source-artifact/state lineage replay, but only independently authenticated automatic core jobs CREATED and COMPLETED after activation receive elapsed-time credit.
5. Require a genuine >=43,200-second first-to-terminal completed-core interval AFTER activation, gap <=5,400 seconds, original repair artifacts, terminal 30-minute follow-through, source/SQLite replay, and independent App5121826 receipt verifier.
6. Freeze the first terminal that satisfies this new window instead of moving the cutoff forward indefinitely.
7. The strict receipt schema now carries both original source-history evidence and separate, exactly replayable post-activation owner-window details.
8. Existing Github owner protections, action-scope permissions, live Brain/repair cadence, and original evidence remain unchanged.

## Negative tests

Offline synthetic adversarial tests cover incorrect source/branch/path/event, non-original attempts, skipped/failed/cancelled observer, fake observe jobs, first-run self-identity, preactivation cores, insufficient post-start time, duplicate/invalid gaps, forged timestamps and receipt fields, premature terminal follow-through, and original source's legacy 12.5h truncation. A simulated test PASS is NOT an independent release check.

## Deployment and governance hold

- The predecessor source currently has NO genuine accepted 12-hour receipt. Current protected ruleset 24182301 requires issuer-pinned validate App15368 and portfolio-phase1-gate App5121826.
- A PR with a failing required check must remain unmerged; do not forge or bypass the check, force-update main, or overwrite original failed source evidence.
- This candidate will need a genuine independently authorized protected release path. If required source acceptance makes that impossible after an owner-aborted observation, report the bootstrap governance deadlock as an explicit blocker. Never call it 100% release health.
- Once a repaired protected main is independently authorized and passes genuine tests, require a fresh source-specific GitHub variable pair with the NEW exact protected SHA and an original non-skipped observer before the next 12-hour clock is credited.
- Financial/Know Me ingestion, personal investing PR #810, and unrelated product experiments remain out of scope.

## Completion checklist

- [ ] GitHub variable physically disables old observation.
- [ ] Full Foundation + focused adversarial tests pass exact repair candidate.
- [ ] Independent issuer-pinned required App check passes for exact head.
- [ ] Protected merge completed with zero bypass.
- [ ] Exact new main verified, all original postmerge CI/core/repair receipts healthy.
- [ ] No open significant safety/reliability blockers.
- [ ] New source observer is deliberately activated and the fresh 12-hour window starts with verified original GitHub evidence.

## Read-only capacity safety

The producer and independent App verifier formerly each admitted only 256 GitHub reads. A 12-hour window with delayed owner activation may need more than 256 original GETs because every source-bound core, repair, observer and final SQLite state must be inspected. Both now share an explicit **512 GET maximum**, within the existing hard read-only transport ceiling of 656. No tokens, permissions, GitHub writes, spending or acceptance criteria were expanded. Adversarial tests exercise the 257th through 512th read and confirm the 513th fails closed. Real provider-rate and terminal-replay success remain unverified until a real source-qualified observation.
