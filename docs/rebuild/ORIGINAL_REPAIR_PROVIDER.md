# Original provider readback closes the repair evidence gap

The Brain's existing technical repair queue and restart-safe owner
follow-through can now collect **real GitHub PR/merge/CI facts** without a
human compiling provider JSON. This is an owner-invoked GET-only helper for
the standing RETALLY and App Factory source repair tasks, not another cron.

## Existing task procedure

1. Use the newest **exact-source** Brain project stage artifact (not a
   cached or hallucinated chat status). Extract `autonomous_repair_queue`
   to a private `queue.json`.
2. Use the existing owner-authorized read-only GitHub token. The helper
   accepts the prior private follow-through `report.json` directly when
   available and first retries unfinished *unsampled* source PRs.
3. Run:

```sh
python -m brain.repair_provider \
  --current /absolute/private/queue.json \
  --previous /absolute/private/earlier/report.json \
  --output /absolute/private/provider-proofs

python -m brain.repair_followthrough_cli \
  --current /absolute/private/queue.json \
  --history /absolute/private/earlier/report.json \
  --provider /absolute/private/provider-proofs/report.json \
  --cycle 2000 \
  --output /absolute/private/next-owners
```

The cycle number must come from the actual verified canonical state or trusted
native workflow run. Omit `--previous` and `--history` for the first
invocation. This procedure can be executed by the existing project-owning
scheduled agents without requesting a fresh prompt. No new GitHub Actions
schedule, ChatGPT task, provider subscription or credentials are created.

## Strict source and request rules

- Fixed eligible repositories:
  `P00NSMASHER/github-value-hunt-ledger` (RETALLY) and
  `P00NSMASHER/x402-product-factory` (App Factory).
- Allowlisted **GET** endpoints only:
  `/pulls/N`, `/branches/main`, and exact
  `/commits/40hex/check-runs?per_page=100`.
  The host is exactly `https://api.github.com`; redirects are refused.
- At most **8** distinct source PRs and **20** transport requests per owner
  invocation (usually 5 PRs, 2 cached main lookups = 7 GETs).
  This is a distinct owner task budget; it never adds calls to the canonical
  Brain's protected **24 GET** main observation operation.
- One error, 404, stale head, wrong base, fork, unsupported provider shape,
  partial check page, unsafe redirect or permission block becomes a clearly
  labeled **gap or fail-closed refusal**, not an implied resolved defect.
- The helper independently binds the original PR number, same-repository
  head/base, current exact SHA, true GitHub `merged` state, merge SHA,
  current main SHA, and a full <=100-check original page to named check ID,
  app identity and head SHA. No provider text, PR title, body or file contents
  become executable instructions.
- If a merge SHA is **not the latest main**, the provider proof remains a
  historical merge observation. Current-main reachability and source
  correctness are unverified; the system must not label it current production.
- `brain.repair_followthrough_cli` consumes the private original-proof
  envelope directly. The existing independent source check names/app IDs
  remain mandatory for `MAIN_TECHNICALLY_VERIFIED`: RETALLY
  `release-gate` and `freight`; Factory `test`, `browser`, and
  `manufacturing`. Other check failures cannot be ignored.
- The provider credential is already supplied by the operator's authorized
  environment. The code neither creates/touches secrets nor requests extra
  scopes. The entire transport is read-only and emits private 0700/0600
  report files.

**Verification meaning:** Original GitHub observations are not signed merely
because they were retrieved through HTTPS. Their schema is validated and
their source identity cross-bound, but the caller must use an authenticated
approved account and source freshness. Technical main checks never establish
real customer success, online service health, legal status, money recovered
or an approved production release.

## Autonomous continuation

A scheduled owner is expected to examine `next_operation` and continue:
reproduce a live defect, patch the actual source and regression, inspect red
checks and revise the exact head, obtain independent gate evidence, or use an
existing SHA-guarded normal merge path when legitimately allowed. An external
legal/payment/consent/one-time Roblox publication hold does not block the next
safe engineering task. If the PR disappears from the latest open sample, the
earlier `next_history` carries it forward, so the owner can obtain its
original closure/merge proof rather than reporting the same finding forever.

This code does **not** implement GitHub writes or grant release authority.
The existing signed V6 source acceptance freeze and original project-specific
QA remain in force. No human-only action is secretly bypassed.
