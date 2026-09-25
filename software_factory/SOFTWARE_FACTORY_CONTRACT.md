# Autonomous Software Factory — Step 16

Step 16 adds bounded MODIFY capability without production authority.

## Lifecycle

`evidence-backed engineering demand -> QUEUED -> isolated factory branch -> candidate commit + regression receipts -> VERIFYING -> independent PASS -> READY_FOR_PR -> PR_OPEN`

`PR_OPEN` is the highest state available to the Step 16 executor. There is **no merge or deploy operation** in the executor.

Failed verification requeues work onto a fresh attempt branch until the bounded attempt limit is exhausted.

## Roles

- Portfolio Manager / future scheduler may identify and enqueue evidence-backed work.
- **Engineer is the only builder.**
- Tester, Auditor, or Red Team may independently verify.
- Builder cannot verify its own candidate.
- A PASS receipt must bind the exact commit, diff/test evidence and work identity before PR creation.

## Repository boundary

The checked-in repository policy enables candidate MODIFY only for `P00NSMASHER/portfolio-brain`.

All downstream repositories — Hunter/RecoveryWorks, StarBlox, ABVM, trading research, PermitPlate and CaptureBrief — remain write-disabled in Step 16. Onboarding any downstream repository requires an explicit future policy change and compatible credentials.

Candidate writes must use a `factory/` branch and an exact base SHA. The executor structurally rejects default-branch writes.

The v1 factory also rejects candidate changes to workflow/security/governance surfaces such as `.github/workflows/`, CODEOWNERS, kill switches, the provider registry and Portfolio build-state file. Those higher-risk self-modifications remain for the later repair/self-improvement gates.

## Tests

Candidate submission requires:

- exact candidate commit SHA;
- explicit changed paths;
- regression-test command(s);
- test receipt hash(es);
- immutable diff hash.

A README-only or untested candidate cannot become VERIFYING/PR-ready.

## GitHub executor

The narrow executor implements only:

- CREATE_BRANCH
- COMMIT_CANDIDATE
- CREATE_PR

It has no merge, deployment, repository-settings, secrets, destructive branch, or default-branch update operation.

A staged reusable workflow grants only `contents: write` and `pull-requests: write` to support those candidate operations. It is not on the default branch yet, so it is not active.

## Work identification

Step 15 currently places ENGINEERING_CAPACITY on HOLD. Therefore the checked-in factory ledger and current `identify_work()` result are empty. This is deliberate: the factory exists, but it does not invent engineering tasks merely to demonstrate activity.
