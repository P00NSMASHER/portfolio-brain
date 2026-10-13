# Cross-project improvement loop

Portfolio Brain must convert research into falsifiable project work without becoming
an unreviewed deployment bot. The canonical SQLite writer and four durable core
repository observations remain unchanged. A separate read-only stage observes four
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

`brain/PROJECTS.json` maps those repositories to ten active logical projects,
including Product Factory and Research Labs. Multiple logical projects may share a
repository, but every project has one explicit research target, improvement focus,
success metric, and desired direction.

## Value contract

The project queue distinguishes:
- `SOURCE_UNOBSERVED`
- `BASELINE_REQUIRED`
- `CANDIDATE_NEEDS_PROJECT_TEST`
- `MEASURED_OUTCOME_RECORDED`

A candidate is only structural evidence until project-specific tests run. An
operator-reported outcome can change queue status but is not independent
verification. Baseline and measured-result fields are deliberately null until a
separate before/after measurement exists.

The recurring stage is read-only and `continue-on-error`: an extended project
provider failure is preserved in artifacts but cannot prevent the canonical Brain
state transaction from publishing. It creates no new scheduler, writer, credential,
permission, paid call, downstream mutation, customer message, trade, or production
merge authority.

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
