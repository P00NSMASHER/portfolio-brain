# Current protected 37a0 source — independent terminal review (READ ONLY)

**Source pin:** `37a0b9300a28e2f1fc19481a5351410709664302` protected main from PR #736 at 2026-10-21T06:50:14Z.

**Isolation:** This branch `review/portfolio-37a0-terminal-20261021` descends only from the prior independently reviewed 35ad terminal audit toolkit. Its workflow is **push-triggered only on this branch**, with `contents:read` and `actions:read`, no protected-main writes, source changes, event trigger, permission escalation, or new external scheduling. The historical 35ad workflow remains inert on this new branch.

**Audit:** The source-pinned `verification.v8_terminal_readiness` independently rereads GitHub run/job metadata, original ZIP bytes/digests/CRC, source-locked Cloudflare HMAC evidence already retained in each original artifact, Git publication ancestry, and terminal archived SQLite/event/report evidence against the immutable production source and exact state commit. Its every result retains `acceptance_pass=false`, `release_or_merge_authorized=false`, and `external_cloudflare_provider_accepted=false`. Original external authenticated Cloudflare Workers analytics remains independently required.

**Window:** Exclude the PR #736 push-triggered bootstrap. First qualifying dispatched original monitor is after 07:20 UTC. Never count elapsed wall-clock time or earlier source receipts as completed six-hour evidence. A full six-hour completed-automatic-run span cannot be declared until original terminal job evidence actually exists; never manufacture it. When the window is not yet complete, emit `WINDOW_RUNNING_NOT_ACCEPTED` and a preliminary raw SQLite replay without final acceptance.

**Disposition:** review/audit only, no new acceptance-only branch, production release or native enrollment. Do not merge this review audit workflow into main.