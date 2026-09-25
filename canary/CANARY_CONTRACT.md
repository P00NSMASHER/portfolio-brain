# Step 24 Autonomous Learning Canary

This canary proves that Portfolio Brain can complete a bounded no-prompt continuation cycle using deterministic code and durable machine-readable state.

The canary deliberately uses a local exact-cursor mirror instead of live network access. The mirror returns only the exact repository SHAs already present in the durable adapter cursor state; blocked sources remain unread. This exercises the observation/runtime path without depending on external availability or introducing new evidence.

The first pass:

1. bootstraps/restores sanitized runtime, scheduler, cost, notification and learning state;
2. executes one deterministic daily runtime cycle;
3. schedules bounded research/Hunter/integration work while preserving human-gated experiments as blocked;
4. obtains and commits a Step 20 cost reservation with zero paid model/API usage;
5. evaluates Step 22 notifications;
6. rebuilds Step 10 learning state without fabricating observations or promotions;
7. persists sanitized continuation states and a canary receipt.

The continuation pass reloads the persisted bytes and repeats the deterministic boundaries. It must produce zero newly selected scheduler work for unchanged source fingerprints, a duplicate-suppressed cost request, notification cooldown suppression, the same learning-state hash, and zero authority violations.

This is a shadow canary only. It does not enable the final recurring autonomous operating mode, contact customers, spend money, trade, deploy, merge, or modify downstream repositories.
