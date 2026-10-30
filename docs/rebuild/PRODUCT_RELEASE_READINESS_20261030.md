# Portfolio Brain | product scope and release evidence

**Date:** October 30, 2026. **Status:** active core with independently tested maintenance; optional review libraries and seller code remain disabled and undeployed.

## What the actual product is

Portfolio Brain's protected `main` runs a nonpaid public-source research and repair prioritization engine. It has deterministic preflight, scoped project monitoring, a bounded evidence-backed improvement queue, repeated readback checks for original GitHub data, a durable public-state branch, original signed-core evidence and independently reviewed protected release controls. Existing system and browser UI artifacts may be read-only; no new paid service, cross-project code writer or trading authority is implied.

The last protected maintenance source at the beginning of this backlog reconciliation was `87c67053b53eabc1b2f73fa23743b14c8314ed4f`, merged through [PR #797](https://github.com/P00NSMASHER/portfolio-brain/pull/797). Original [Foundation push 41122715285](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41122715285) and [core push 41122714839](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/41122714839) both passed. Original public-state branch and SHA-256 artifact were verified separately. These results are limited to the actual tested source; candidate changes require new checks.

## Optional components, deliberately isolated

| Component | What is verified | What is *not* authorized or certified |
|---|---|---|
| Bot knowledge admission from #691 | Bounded offline JSON/source checks; duplicate-check and non-finite hostility regressions | No new bot verifier workflow, App token, automatic protected merge or 12-hour acceptance |
| Native admission from #730 | Inert two-stage model, read-only final approval checks, local SQLite intent journaling, Linux-safe adversarial tests | No live enrollment, revocation, native GitHub mutation or Windows ACL machine certification; Windows integration test is skipped on Linux |
| Standalone seller from #484 | Isolated source, Node syntax, network-free mocked origin/payment protocol, Express route tests in optional local `npm test` | No new Render deployment or active workflow; live upstream Census 502 remains historical; no real payment/settlement certification |
| Portfolio Brain core | Existing automatic core, research, state and protection workflows continue | No permission to market the whole portfolio as revenue-producing or faultless |

## Repair-mode hard hold

The user explicitly requested **no new 12-hour observation until separately authorized**. The protected 12-hour observer and its producer both contain a literal job-level `false &&` guard, in addition to a consent variable. The guard is effective even if a repository variable was set in the past. The existing core and scoped repair schedules are unchanged.

Do not manually dispatch an observer or treat a skipped job as acceptance. A future re-arm requires **explicit user direction** plus a new reviewed protected code change, independent tests and a fresh source-specific window. Historical failed original run evidence is preserved in [issue #796](https://github.com/P00NSMASHER/portfolio-brain/issues/796); the prior custom release-governance discrepancy is preserved in [issue #795](https://github.com/P00NSMASHER/portfolio-brain/issues/795).

## Local operator flow

Python 3.12, no paid service required. These are local, manual commands for reproducing nonsecret behavior, not production observer dispatches:

```sh
python -m brain preflight --output brain-local/preflight --expected-sha "$(git rev-parse HEAD)"
python -m brain init --db brain-local/state.sqlite --output brain-local/bootstrap
python -m brain monitor --db brain-local/state.sqlite --output brain-local/monitor
python -m brain projects --db brain-local/state.sqlite --output brain-local/projects
python -m brain doctor --db brain-local/state.sqlite --output brain-local/doctor
python -m unittest discover -s tests -p "test_*.py" -v
```

Standalone seller protocol tests are deliberately network-free, without requiring Express:

```sh
cd services/agent-data-tools-standalone
npm run test:protocol
```

Full standalone Express contract tests require `npm install`; live upstream testing is separately opt-in and not part of default CI.

## What finishing means

A code release needs a current protected base, complete source diff review, exact-head Foundation `validate` from App 15368, independently issued `portfolio-phase1-gate` from App 5121826, original test artifacts, protected main ruleset 24182301 active with no bypass, and successful actual-main postmerge verification. No old PR's green check transfers to a new candidate SHA.

Product completeness must not be confused with deployment: Windows/native admission, real seller payments, third-party upstreams and authorization to contact customers require separate hands-on validation and user approval. An optional module may be *feature-complete as code* without being activated. We keep the user-facing operational claims accurate rather than inventing missing proof.
