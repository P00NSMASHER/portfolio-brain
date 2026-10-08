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

## Historical integrity

The v2 soak is immutable FAIL; v3 had no qualifying automatic baseline by its 2026-10-08T05:57:53Z deadline and must be finalized by the independent Portfolio Brain Soak Watch, not silently restarted. A new source must receive exact-head protected CI and its OWN new six-hour v4 (or next unused version) acceptance: >=21600 seconds between first and last genuine successful automatic cycles, <=5400 seconds between consecutive completions, all-run inventory including failures, same source, correct durable state chain, zero pending and independent postvalidation. Do not replace v3 status with v4.
