# Independent Cloudflare recovery clock

This is an independently scheduled Cloudflare Worker deployed to the user's connected Cloudflare account as `portfolio-brain-recovery`, with UTC cron `*/10 * * * *`. Unlike two GitHub-native workflow schedules, this provides a genuinely separate scheduling provider.

## Activation is intentionally fail-closed

Two Cloudflare Worker **secrets** are required:

- `GITHUB_ACTIONS_TOKEN`: a short-lived or limited-expiration fine-grained GitHub personal access token restricted to **P00NSMASHER/portfolio-brain**, with repository **Actions: Read and write** and Metadata: Read. It is sent only to `api.github.com` to query execution health and dispatch `brain-cycle.yml`. Keep it out of source, logs, and ChatGPT messages.
- `SIGNING_KEY_PKCS8`: base64-encoded PKCS#8 **P-256 ECDSA private key**, provisioned as a Cloudflare secret. The matching public key is `brain/cloudflare-clock-public.pem`, committed only to a reviewed GitHub source branch. Never place the private key in the repository.

Connected-application tools were unable to create Cloudflare secret bindings. **Do not claim external dispatch works until BOTH secret names exist, the Worker is deployed on the reviewed code, GitHub accepts a scheduled webhook dispatch, and an independently validated completed core artifact is observed.**

The Worker has no public dispatch endpoint. Its `fetch` handler always returns HTTP 404. Only Cloudflare's real `scheduled()` event handler signs and dispatches. Its provider-selected scheduled timestamp is included in the signed payload, with a ten-minute cron slot, the actual protected-main SHA, a current issuance time, and the Worker identity. The on-GitHub core independently checks the signature, exact source, slot, clock identity and a 20-minute freshness window using only the committed P-256 public key. It then performs the original monitored research/experiments/doctor and nonforce state publication, with `cloudflare-origin.json` retained in the core artifact.

Cloudflare logs with the original actual `scheduled` event, signature, GitHub core job, immutable SHA256 artifact and final SQLite state all must be verified independently before a Cloudflare-originating dispatch can count toward the six-hour soak. A manually dispatched job, a valid-but-replayed signature, or GitHub API HTTP 204 cannot establish automatic runtime readiness.

The Worker suppresses dispatch when the same-main core succeeded in the last 25 minutes or when a core is active. Stale queued writers block rather than generating competing writers. It never changes GitHub main, credentials, scheduling, acceptance, data integrity or billing settings, and uses no paid endpoint. Free Worker quotas and GitHub Actions usage must be checked regularly.

## Verified acceptance and future source changes

The original v4 six-hour soak is **terminal PASS** for protected source
`9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`, with the authoritative
[acceptance record](https://github.com/P00NSMASHER/portfolio-brain/blob/brain-acceptance-v4/acceptance/finish-soak-v4.json)
at commit `b1b9f63dc8136f259abdc1b9ad18fcd47cf3b681`.
Fourteen Cloudflare `scheduled()` events were independently retrieved,
matched to P-256-verified successful GitHub cores and durable state delivery,
and counted over 28,792 seconds (largest accepted gap 3,625 seconds).
The historical 15:20, 16:20 and 18:50 UTC jobs passed signed origin and
workloads but had no independently retrievable original provider event;
they are **successful but nonqualifying**, not silently counted or called
runtime failures. All original source-matched core runs are inventoried.
Independent raw SQLite terminal replay and hosted independent verification
passed; see [operations](../../docs/rebuild/OPERATIONS.md).

A successful provider Cron invocation alone, or the worker's `FRESH`
deduplication result, does not prove that a new GitHub core completed.
Continuing operation still requires the actual GitHub run, workload,
artifact, state and backlog checks. V4 acceptance applies only to that
source and time window. Any revised production source needs separately
authorized protected integration and a new-version acceptance period; do
not reopen or overwrite historical v4. The draft evidence-only
[PR #655](https://github.com/P00NSMASHER/portfolio-brain/pull/655)
remains unmerged.

## Historical integrity

The v2 soak is permanently FAIL; v3 missed its original automatic baseline deadline of 2026-10-08T05:57:53Z and remains BLOCKED. Neither historical result was rewritten when v4 passed. Any *future* code revision needs its own separately authorized protected source, new acceptance version and unchanged safety gates: at least 21,600 seconds between real successful automatic completions, no gap above 5,400 seconds, full failure/nonqualifier inventory, source/state continuity, independent replay and postvalidation.
