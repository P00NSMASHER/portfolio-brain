# Guarded GitHub-native auto-merge admission — v9 candidate

**Status: source and tests only; not a deployed autonomous writer.** This component does not install a scheduler, add repository secrets, modify production workflows, or alter branch protection. The repository-level \`allow_auto_merge\` setting was observed **false** on 2026-10-19. No GitHub connector action available in this session can change that setting.

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

No GitHub Actions job or automatic trigger invokes this CLI yet. Do not run it from candidate PR source. Turn on the GitHub repository setting **Settings → General → Pull Requests → Allow auto-merge** only through a user-authorized administrator connection; do not use an unrelated runtime secret or weaken rulesets. After enabling the setting, observe \`allow_auto_merge=true\` via GitHub readback before enabling any unattended enrollment path.

## Safety and activation gates

- Source acceptance for newly merged \`59417cbd…\` is pending. The accepted \`0c1184d2…\` receipt does not transfer.
- The current code must pass exact-head Foundation and independently issued verifier checks, then the guarded protected merge procedure. Once merged, it starts another new-source acceptance period.
- A future independently reviewed workflow may invoke this code on trusted-main only, after runtime token scope is established, with no PR-source execution. It must never self-issue its approval or mint verifier checks. No new ChatGPT tasks or paid resources are created.
- A PR that changes after admission, fails check provenance, has unreviewed files, altered acceptance or unresolved threads **fails closed**; missing data never proves a safe merge.
- When a GraphQL enrollment write has an uncertain outcome, reconcile actual PR state before any retry. There is no automatic retry in this component.
- Enrollment is not a product deployment or a v9 capability completion claim. Deployment requires project-specific tests, publication readback and fresh source-bound reliability acceptance.

## Recovery

Discard the unmerged candidate branch to roll back development. Once deployed, disable the future workflow and revoke its scoped runtime token if admission behaves incorrectly; GitHub native per-PR auto-merge state must be inspected separately. Do not reset protected main or history.
