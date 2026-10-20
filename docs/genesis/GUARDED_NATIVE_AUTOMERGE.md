# Guarded GitHub-native auto-merge admission — v9 deployed controller and draft fix

**Status (2026-10-19):** The original narrowly scoped event-only controller was merged through PR #722 into protected main at `3ea4dc4d0ddcb3470dc0d884bb2702efaef6dc4d`. Actual production execution exposed missing `allow_auto_merge` in restricted-token REST responses. Repository-owner metadata and the original same-token GraphQL probe confirmed auto-merge is **enabled**. The authenticated GraphQL correction is **draft PR #724, not deployed**. Enrollment remains blocked until separately governed, source-specific six-hour reliability acceptance and an independently reviewed protected release. Neither the deployed controller nor this candidate adds schedules, secrets, bypasses, or paid infrastructure.

## Authorization model

The owner authorized routine automatic merges and deployments without removing independent verification. This controller never calls GitHub's direct merge endpoint; after admission it enrolls **one** PR in GitHub's native squash auto-merge. GitHub itself still enforces all branch rules. It makes exactly one GraphQL auto-merge mutation and does not retry uncertain mutations.

The hardcoded scope is currently **P00NSMASHER/portfolio-brain only**, repository ID 1387747549, protected main, and ruleset 24182301. It requires active protection without bypass actors, resolved review conversations, strict checks **validate** from App **15368** and **portfolio-phase1-gate** from App **5121826**. Check issuers, PR base and head, author, label, changed files and Git document blobs are all directly read back.

The source-specific reliability gate must be certified **for the current protected main commit**, using an owner-governed acceptance-only evidence branch, with a single child commit containing an authentic source-bound PASS record (six-hour original run census and terminal SQLite/ledger/report replay). A prior commit's acceptance cannot authorize merging a new commit. The candidate refuses missing, ambiguous or unsupported acceptance; a PR author's status or comment never supplies authority.

## Allowed changes

Only an open, non-draft, mergeable PR by the project owner or the existing trusted Brain bot, with explicit \`brain:guarded-automerge\` label, containing **1–6** regular UTF-8 Markdown documentation files under \`docs/genesis/\` or \`docs/rebuild/\`, total patch size **at most 240 changed lines**. This is intentionally narrower than all engineering work. It excludes executable source, workflows, CI, rulesets, dependencies, secrets, symlinks, renames, unrelated repositories, and customer-facing changes. Broader classes require separate threat modeling, tests and independent release review.

## Execution

From an immutable trusted-main checkout, with a previously authorized short-lived GitHub token scoped to this repository and PR permissions:

\`\`\`sh
python -m brain.v9.guarded_merge --pr 123 --expected-main <exact-accepted-production-SHA>
# Review sanitized admission result.
python -m brain.v9.guarded_merge --pr 123 --expected-main <same-SHA> --apply
\`\`\`

The deployed `.github/workflows/v9-guarded-native-automerge.yml` responds only to successful completion of the existing independent verifier, checks out trusted protected-main code without persisted credentials, verifies pinned controller blobs and restricts candidates to explicitly opted-in PRs. It is **not scheduled**, executes no candidate PR code, and uses `contents:read`, `pull-requests:write` within the existing repository-scoped `GITHUB_TOKEN`. The current deployed controller safely produces zero writes when acceptance is absent, but misreads the token's omitted REST `allow_auto_merge` property as disabled. Draft PR #724 corrects that defect with a separately authenticated, identity-checked, read-only GraphQL query before *any* native enrollment mutation. The repository setting is already enabled; **do not change settings, credentials or branch protection to work around this visibility defect**.

## Safety and activation gates

- Protected current main is `3ea4dc4d0ddcb3470dc0d884bb2702efaef6dc4d`, distinct from the previously accepted `59417cbd…` and `0c1184d2…` sources. Their prior receipts cannot transfer. An earlier canceled `3ea4dc4d…` core invalidated the first acceptance window; any later clean original-source window requires its own complete independent provenance, terminal replay and separately governed receipt.
- The GraphQL correction PR #724 must pass exact-head Foundation and independently issued App checks, actual review, and all protected release gates before it can merge. That protected merge creates a **new** production source, which requires its own six-hour acceptance before the fixed controller can enroll the documentation-only PR #723. No acceptance can be borrowed from an earlier SHA.
- The deployed event-only workflow is protected by `brain.validate` rules covering exact blob pins, trusted-main checkout, restricted permissions and no direct merge API, Cron, or untrusted PR triggers. Candidate #724 must preserve these controls. No new ChatGPT tasks or paid resources are created.
- A PR that changes after admission, fails check provenance, has unreviewed files, altered acceptance or unresolved threads **fails closed**; missing data never proves a safe merge.
- When a GraphQL enrollment write has an uncertain outcome, reconcile actual PR state before any retry. There is no automatic retry in this component.
- Enrollment is not a product deployment or a v9 capability completion claim. Deployment requires project-specific tests, publication readback and fresh source-bound reliability acceptance.

## Recovery

Discard PR #724's review branch to abandon only the unmerged correction; it does **not** roll back PR #722's deployed workflow. If the deployed controller misbehaves, suspend its enrollment path using an authorized, protected and independently verified change; inspect existing GitHub-native per-PR auto-merge enrollment separately. Do not disable branch protection, reset protected main, or rewrite state history.

### Authenticated repository setting readback under GitHub Actions

The original guarded workflow initially returned `REPOSITORY_AUTO_MERGE_SETTING_DISABLED` even though the owner-enabled setting was true: an actual `GITHUB_TOKEN` REST GET returned repository identity but **omitted** the admin-only `allow_auto_merge` field. This is not proof of disabled auto-merge. Independent read-only GitHub Actions probe 39269404271 confirmed the same scoped token can query GraphQL `Repository.autoMergeAllowed=true`, together with the exact numeric repository ID, canonical name and non-archived state; original REST ruleset/check/PR reads also passed.

Draft PR #724 makes the controller require authenticated GraphQL `autoMergeAllowed` with strict repository identity, and reject missing, malformed, conflicting or wrong-repository responses. A missing REST field is unknown, never proof of enabled or disabled. The fix adds bounded read-only API queries without changing scopes, grants, schedules, native merge method or source-acceptance authority. **Until independently accepted and merged, this is candidate behavior, not the deployed production implementation.**

### Restricted Actions-token ruleset bypass census (2026-10-20)

Real post-#724 guarded-controller workflow [39346555735](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39346555735) found labeled documentation canary #723, but returned `BLOCKED:PROTECTED_RULESET_MISMATCH` with zero provider writes. An original same-permission Actions-token read-only [probe 39346712051](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39346712051) proved REST omitted the `bypass_actors` field despite returning the active ruleset and required independent-check policy. Original authenticated [GraphQL probe 39347172040](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39347172040) proved `RepositoryRuleset.bypassActors` is readable by the unchanged restricted token. The exact repository ID 1387747549, name, non-archived state and exact ruleset ID 24182301/name/enforcement were independently verified; GraphQL `bypassActors(first:100).totalCount=0` and `hasNextPage=false`, with complete ruleset pagination. Missing REST field means unknown, not permission bypass nor false failure. This candidate requires authenticated read-only GraphQL zero-bypass proof and cross-checks any explicit REST bypass list; conflicting, truncated, incorrect-identity or ambiguous responses deny all merge enrollment. It rechecks at final admission and changes no trust boundary, schedule, required checks or credentials. It is only a separately reviewed draft until current main source `4393488059c8f7f02ce665a514a10198feae270c` earns its own genuine six-hour acceptance; merging this candidate starts another new source-specific six-hour window. Do not enroll or manually merge the canary.
