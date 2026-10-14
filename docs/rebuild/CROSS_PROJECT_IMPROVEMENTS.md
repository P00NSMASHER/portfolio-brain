# Cross-project improvement loop

Portfolio Brain must convert research into falsifiable project work without becoming
an unreviewed deployment bot. The canonical SQLite writer and four durable core
repository observations remain unchanged. A separate read-only stage observes five
additional active public repositories using a fresh bounded GitHub adapter, so the
existing 24-request limit is not weakened and extended-source failures do not corrupt
or stale the canonical ledger.

## Covered repository bindings

Core durable state:
- P00NSMASHER/portfolio-brain
- P00NSMASHER/trading-platform
- P00NSMASHER/abvmschoolstarworld
- P00NSMASHER/github-value-hunt-ledger

Extended read-only observation:
- P00NSMASHER/PipsQuestWorld
- P00NSMASHER/permitplate-nyc
- P00NSMASHER/StarBlox
- P00NSMASHER/capturebrief
- P00NSMASHER/x402-product-factory

`brain/PROJECTS.json` maps those nine repositories to ten active logical projects,
including Product Factory and Research Labs. Multiple logical projects may share a
repository, but every project has one explicit research target, improvement focus,
success metric, and desired direction.

## Value contract

The project queue distinguishes:
- `SOURCE_UNOBSERVED`
- `BASELINE_REQUIRED`
- `CANDIDATE_NEEDS_PROJECT_TEST`
- `OPERATOR_FEEDBACK_RECORDED` (not verified measurement)

A candidate is only structural evidence until project-specific tests run. An
operator-reported outcome can change queue status but is not independent
verification. Baseline and measured-result fields are deliberately null until a
separate before/after measurement exists.

The recurring stage is read-only and `continue-on-error`: an extended project
provider failure is preserved in artifacts but cannot prevent the canonical Brain
state transaction from publishing. It creates no new scheduler, writer, credential,
permission, paid call, downstream mutation, customer message, trade, or production
merge authority.

## First-priority value experiments

RETALLY: validate false recovery recommendations and reviewer workload on an
exact-source labeled synthetic invoice fixture. Separately prove restricted
staging role boundaries. First-customer activation (RETALLY issue #323) remains
held; business registration is deliberately deferred until the first customer.

Product Factory: observe P00NSMASHER/x402-product-factory directly rather than
misattributing it to RETALLY. Audit source-pinned unmerged builds, mobile/desktop
role-separated review, restart persistence and artifact integrity. Browser CI
is not market demand. Actual buyer-confirmed pilots remain unmeasured.

Both have null baselines/results and no live activation authority. Five optional
sources normally require 20 GETs; the unchanged 24-GET adapter limit fails
closed on unusually paginated checks or retries, without harming canonical
publication.

## Intended operating loop

1. Observe exact project source.
2. Select one bounded project metric and establish a reproducible baseline.
3. Match current structural intelligence to that project.
4. Test one candidate in isolation against the baseline and adversarial controls.
5. Use normal project review to decide whether to adopt it.
6. Record only measured outcomes; leave revenue/time/customer value unknown when
   no evidence exists.
7. Feed operator-confirmed outcomes back into future candidate ranking.

This source change is a candidate until exact-head tests and normal protected review
pass. It does not inherit historical V4/V5/V6 acceptance.

## Source-bound live PR triage (additive optional sidecar)

The main production branch is **not** the same as active work in draft PRs.
After optional repository snapshots, the queue now samples a bounded first page
of 15 current open PRs in each focus repository (one read-only GitHub GET each),
then at most one exact-commit check-runs page for the top eligible PR in each.
For RETALLY, only PR titles explicitly naming RETALLY are candidates because the
shared repository also contains other products. Titles are never emitted to the
report or obeyed as instructions.

Every selected candidate preserves the **real PR number, exact head SHA, draft
status, target branch and source-bound check state**. Stacked dependencies are
labeled as observed branch-name relations, not independently verified ancestry.
Incomplete check pagination, duplicate or cross-SHA check identities, skipped
jobs, provider failures and exhausted budgets cannot turn into an acceptance
claim. All output is an operator review packet: there is no automatic merge,
customer outreach, paid charge, formation, deploy or code execution.

The five extra repository snapshots normally use 20 GETs; two PR pages and two
candidate check pages use at most four more. **The original total limit of 24
GETs remains unchanged, including retries and extra check pagination.** If
higher-priority reads exhaust the budget, focused PR evidence explicitly says
unverified. No extra schedulers, credentials or canonical ledger mutation.
Technical CI is not measured improvement or buyer validation.

## Value-first opportunity discovery and delivery packets

The optional source observer now ranks all qualifying PRs in the **latest 15
open PRs per priority repository** with a transparent project-specific title
heuristic. This is a *triage relevance score*, not independently established
demand, monetary return or probability of success. It prioritizes:

- RETALLY: first-customer onboarding and controls, independent invoice/fee
  review correctness, rollback/replay security, then marketing evidence.
- App Factory: joint idea discovery + deploy rehearsal, consented buyer
  validation, deployment proof, genuinely differentiated ideas and finally
  automation reliability.

Up to four distinct opportunity themes per project are retained and at most
three are converted into exact-PR-and-SHA-pinned operator work packets. Each
packet names the first reviewable change, a measurable falsification metric,
an explicit before/after or hostile test procedure, source artifacts to keep,
CI and stacked-branch evidence limitations, and actual business activation
holds. A secondary candidate never borrows the primary candidate's observed
CI. Malformed paths, forged URLs, duplicate identities and unverified hashes
cannot become actionable proof.

The App Factory is observed *first* in the five extended-repository phase so
optional research source pagination cannot starve the user's priority system.
The four canonical repositories and 24-total-GET bound remain untouched.

This is a technical **proposal-to-review** capability, not autonomous source
patching or approved downstream deployments. The report's technical review
packet count measures work packets **created**, not verified project adoption.
Measurement baseline, before/after improvement, independently verified buyer
outcomes, savings and revenue remain null/unknown until established by actual
project-specific tests and authorized evidence. Existing synthetic workflows
and historical CI cannot satisfy those independent gates.
