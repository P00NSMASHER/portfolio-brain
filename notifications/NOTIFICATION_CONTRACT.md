# Step 22 Notification and Escalation Contract

The notification layer is an OBSERVE-only decision-support surface with no execution authority.

## Evidence-gated alert classes

Alerts may be created only from sanitized, durable evidence for:

- cost/kill-switch hard stops;
- human approval queues;
- open blockers requiring a human decision;
- cancelled/failed autonomous work;
- independently VERIFIED positive or negative experiment/transfer outcomes; or
- a material change in the deterministic executive-dashboard snapshot after an initial baseline exists.

Missing evidence creates no outcome alert.

## Deduplication and rate limiting

Every alert uses a stable fingerprint derived from its alert class, project scope, entity references, and state code. Unchanged conditions reuse the same alert record. Repeated notifications are limited by severity-specific cooldowns. The current policy emits HIGH conditions at most daily and MEDIUM conditions at most every three days. A persistent autonomous failure may escalate to CRITICAL after repeated observations; approval queues and governance blockers never auto-escalate into authorization.

## Delivery surface

The staged delivery surface is limited to GitHub Actions annotations and the GitHub Actions step summary. It does not send email, SMS, Slack, customer communications, arbitrary webhooks, or external API messages. Delivery output contains sanitized alert codes, IDs, project IDs, entity refs and evidence counts only.

## Authority boundary

An alert cannot approve ACT, grant authority, move money, trade, deploy, merge, change secrets, modify downstream repositories, or satisfy a required human approval. Alerts are information only.

## Public-repository boundary

While BLK-005 remains open, persistent notification state contains only sanitized IDs, hashes, severity, timestamps, counts and evidence references. No prompt text, credentials, private customer/operational payloads, or sensitive evidence bodies are stored.
