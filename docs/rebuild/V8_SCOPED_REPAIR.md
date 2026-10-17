# V8 runtime: authenticated scoped repair proposal

## Reviewed one-source real defect

One existing CaptureBrief documentation defect is reproducible: authoritative
DEPLOYMENT-TARGET.md says the current website runs on GitHub Pages from the
gh-pages branch, while PUBLIC-RELEASE.md still directs Netlify deployment.
An operator following that obsolete handoff could publish to the wrong site.

The approved original CaptureBrief source is
4a7c5d6c223b8488995ab221dc169ba32ae828f8. The owned file is
PUBLIC-RELEASE.md; the authoritative reference is DEPLOYMENT-TARGET.md.
Expected original Git blobs are independently fixed in the reviewed adapter:

- Canonical: f4182f742af5e793cb98efcf4b3dac5bfc0d9dd9
- Misleading release document: 11eb0d1674bc7b2cf9ccb1a5aa907060f1e833c1

The stdlib-only source recipe replaces exactly the known incorrect text and
the obsolete current-site handoff. Everything outside these reviewed blocks,
including the historical release-packaging and product safety explanations,
is preserved. The old source fails the regression; the patched source passes.
The regression resides in the trusted Brain review tests; the downstream
CaptureBrief Product Core CI includes changes to PUBLIC-RELEASE.md.

## Genuine automatic trigger, not a ChatGPT task

The trusted workflow v8-scoped-repair.yml has only a workflow_run completed
trigger from the existing Brain cycle. It does **not** create a cron, ChatGPT
task, cloud service, trading routine or external communications workflow.

Before accessing the runtime App credential, its original protected main
checkout and two stdlib-only code modules are verified by immutable Git
object identities. An independent, read-only origin collector checks the
original same-main successful Brain core, exact source, required job steps,
original run attempt, and authenticated native GitHub schedule or separately
signed original Cloudflare/clock origin. A push run, unverified manual
dispatch, stale main, nonmatching core, failed step or changed workflow
cannot reach the writer token.

Only after that preflight passes does the existing runtime App mint an
automatically revoked token for precisely **P00NSMASHER/capturebrief**,
with Contents and Pull Requests write permissions. The adapter independently
verifies one-repo token inventory and App installation identity, target
source and old document Git blob hashes, stable main, exact before/after
content, original GitHub new branch+commit readbacks, one-file compare
identity, actual bot-authored draft PR and unchanged main.

No arbitrary source code is retrieved or executed, and the provider API
route allowlist excludes workflow files, other repositories, merges, releases,
deletes, branch overrides, payments, secrets, and third-party endpoints.
No website files, private customer records, tasks or production main are
modified by the proposal job. Unfinished/ambiguous intents are blocked for
owner reconciliation rather than blindly retried or duplicated.

## What counts as verified completion

1. After protected adoption, wait for a genuine new automatic Brain core and
   a matching **original workflow_run**. A passing PR cannot substitute.
2. Read the original scoped-repair workflow job, per-repo token evidence,
   sanitized ZIP receipt, and actual bot-authored CaptureBrief draft PR.
3. Independently verify the exact one-file diff, old failing and new passing
   regression, CaptureBrief Product Core checks and reviewer/release holds.
4. If separately authorized, deliver via the owner's normal protected
   approach, then confirm the actual CaptureBrief default-branch original
   bytes and no website or customer delivery occurred.
5. For the final newly merged Brain source, collect new independently
   corroborated automatic production completions over at least six hours,
   with <=90-minute gaps, original artifacts and full terminal strict
   SQLite/ledger/report replay. Earlier accepted source evidence is
   historical and is **not** transferable.

This is **one real deterministic autonomous draft repair**, not general
self-editing AI, independent code review, protected merges or production
deployment. Proving broader autonomous coding capabilities requires separate
reviewed recipes, source-specific tests and least-privilege permissions.
Do not label any incomplete outcome ACCEPTED.

## Resource limits

No new paid service, account, key, external contact or schedule is created.
The job reuses native GitHub Actions and the existing App installation, but
its additional Actions execution may consume plan-specific minutes; verify
account billing independently rather than assuming an unconditional $0 cost.
All existing protected-main, original six-hour acceptance, private-data
boundaries and no-bypass rules remain active.
