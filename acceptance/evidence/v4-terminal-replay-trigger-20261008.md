# V4 final raw-state replay evidence trigger (read-only)

Evidence-only CI trigger for draft PR #655. **DO NOT MERGE** during v4. This file has no runtime or acceptance authority.

- Production source (frozen): `9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`
- Original genuine Cloudflare-scheduled first completed core: `37787547513`, `2026-10-08T13:50:59Z`.
- First core satisfying 21600-second elapsed time: `37838694515`, completed `2026-10-08T20:20:47Z`, span `23388 seconds` (6h29m48s).
- Latest successfully completed genuine Cloudflare-scheduled core at evidence freeze: `37849541008`, completed `2026-10-08T21:50:51Z`.
- Latest exact published durable-state commit: `f2fb6ffd4f4a3cfd979c6ce28b990b9ad8379b05`.
- Previous immutable state parent: `098b42824934984cd7e90c004868e02d29a47566`.
- Original GitHub core artifact ID: `11581816477`; independent original ZIP SHA256: `db50049bad405e842dfaa60eac7dd4025133fa84f56d63b36dabad59193c4d18`.
- Latest doctor: PASS, event sequence `210`, canonical hash `d5b48a0c3d5fadb6210ef8a277ec3a43d762f96f6e7ab22881fa161ed2b38f0a`, pending events `0`.
- Provider: observed actual Cloudflare scheduled() invocation at `2026-10-08T21:50:23.858Z`; signed-origin verification and mandatory GitHub workload steps passed.

This marker only re-triggers pre-existing Foundation CI on the **draft evidence PR**, so that its unchanged network-capable test reads true binary `brain-state-v2/state.sqlite`, recomputes SQLite and the complete cryptographic event/ledger chain, and prints a fresh pinned receipt. The raw replay receipt must explicitly name the exact commit above and match its canonical chain/event sequence. If it does not, this marker is not proof. The isolated network-disabled verifier may skip only the live transport test, and a skip never counts as raw replay PASS.

This marker alone is NOT v4 acceptance, and does not verify the entire earlier provider log inventory. Only Soak Watch may independently reconcile all original clocks, failed/nonqualifying runs, actual ZIPs, state history, missing provider records and post-soak validation before writing an evidence-based terminal PASS/FAIL/BLOCKED on `brain-acceptance-v4`.
