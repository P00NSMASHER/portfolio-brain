# Bot-authored knowledge review | code-only security library

**State: safe review helper, not a deployed authorization or merge workflow.**

This module and its tests originate from historical [PR #691](https://github.com/P00NSMASHER/portfolio-brain/pull/691). The proposed new `.github/workflows/portfolio-bot-knowledge-verifier.yml` is **not installed** in the active source; the release never adds an independent App token, GitHub merge writer, new schedule or source-acceptance receipt. No bot-generated knowledge update receives permission to merge merely because a Python predicate is true.

## What the library checks

`verification.bot_knowledge_admission.inspect(...)` accepts only an explicit original provider snapshot for one in-repository, non-draft, bot-authored proposal. It checks the exact matching branch/fingerprint, the current protected-source ancestry, precisely one changed knowledge-data file, bounded public source records, duplicate-free/non-finite-free JSON, schema v2, 12-source ceiling, public reference structure and source-bound fingerprint.

`foundation_green(...)` separately requires **exactly one** successful `validate` check for the immutable head, issued by Foundation App **15368**, with a complete bounded check page. A duplicate `validate` status, stale head, wrong issuer or missing result fails closed. Its output is only evidence for review, never authority to publish App **5121826** checks or merge anything.

The historical signed source-acceptance gate is separate and not transferable. The user has explicitly paused new 12-hour observations. No part of this helper can re-arm observers, approve a protected source, issue credentials, change workflow inventory or override a human reviewer.

## Tests and integration limits

The package includes offline negative tests for substituted authors, forks, conflicting check issuers/heads, stale ancestry, extra code changes, invalid schema, duplicate JSON fields and non-finite values. It requires no live GitHub requests, payments or connection to other repositories.

A future bot-authorized production integration would require a separate source-bound protected PR, original authenticated API reads, independent App approval, positive and adversarial tests, and explicit authorization for any new merge or credential authority. Nothing in this reviewed code grants those capabilities.

**Documentation claim:** a reliable standalone admission check exists; an unattended protected bot-release pipeline does **not** follow from including it.
