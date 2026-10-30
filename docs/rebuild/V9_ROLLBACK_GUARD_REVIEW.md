> October 29 integration note: original review notes below are historical. Prepared on main 25e697c in PR #787; fresh checks and independent review are required. No release authority or live acceptance is granted.

# V9 rollback protection — read-only review candidate

**DRAFT; no production installation.** This proposal is deliberately narrower than automatic deployment or automatic rollback. It is a safety guard that can *prepare the prerequisites* for a separately reviewed revert, not a controller that actually performs a revert.

Inputs describe a GitHub original-run incident and a current protected-main snapshot. The pure deterministic module `verification.v9_rollback_plan` refuses invalid source/first-parent/state identities, disabled or bypassed protection, missing independent issuer-pinned check requirements, unreviewed changed paths, unsupported workflow origins, contradictory original monitor/run outcomes, manual/push triggers, or uncertain provider writes.

Only a first-attempt adverse automatic core may yield `PREPARE_PROTECTED_REVERT_PR_FOR_INDEPENDENT_REVIEW_ONLY`. That text is **not** sufficient to take action: the running production system or any agent must still independently read back all original GitHub run/job/artifact evidence and current branch rules, create a new restricted **draft** revert PR, independently test it, meet source-specific release acceptance, obtain the separate governed decision and merge only through protected GitHub. Any new merged source requires its own post-change six-hour reliability acceptance. Original state `brain-state-v2` must never be reset or rewritten.

There is intentionally no GitHub client, token, subprocess, command execution, scheduler, cleanup, force-push, automatic branch mutation or user notification in the module.

```sh
python -m verification.v9_rollback_plan \
  --snapshot observed-protected-main.json \
  --incident original-automatic-monitor-incident.json \
  --output unsent-protected-revert-review.json
python -m unittest discover -s tests -p test_v9_rollback_plan.py -v
```

The JSON input alone is untrusted and cannot establish provider authenticity or release approval. The report always has `production_release_authorized=false`, `provider_write_attempted=false` and `force_push_allowed=false`.

This isolated branch is not a live rollback system. Keep existing independent release holds intact; do not merge it or enable automatic deployment without separately tested protected policy adoption.
