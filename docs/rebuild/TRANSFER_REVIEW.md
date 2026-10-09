# Read-only Portfolio Brain cross-project transfer review

This source-candidate capability joins Portfolio Brain's **existing verified
SQLite ledger report** with GitHub's current, exact-revision pull-request and
check-run metadata. It is a **technical evidence observation**, not a learning
event, operator feedback, product deployment, license approval, revenue report,
or automatic code transfer.

## One supported first-party target

The initial target policy is deliberately narrow:

- `P00NSMASHER/github-value-hunt-ledger` (RETALLY)
- One public pull request against its actual default branch.
- Every changed file must be under `freight/`.
- Required observed GitHub Actions check names:
  `freight`, `recoveryworks`, `release-gate`, `contracts`, `verify`;
  those checks must be completed SUCCESS on the *exact PR head* and tied
  to the known GitHub Actions App.
- A correctly skipped `deploy` check is allowed, but never proves a deployment.
- Every other returned check must also have a terminal permitted conclusion.
  Incomplete check pagination, duplicate provider IDs, pending/failed checks,
  incorrect exact revision or unverifiable identity blocks technical success.

The target's PR description must **claim** the canonical source URL found
in Brain's immutable ledger report. That link is an attribution claim made
by a downstream PR author, **not independent proof** of code causation,
functional reuse, test execution, compliance or customer adoption.

The GitHub PR is checked **twice** around the changed-file and CI reads.
If its exact head revision, repo/base identity, open/closed/draft/merged
state, file count or attribution body changes mid-review, verification
fails closed with `TRANSFER_PR_CHANGED_DURING_REVIEW`. This refuses a
previously green review for a superseded PR revision or a withdrawn
source citation, without creating another scheduled poller or following
the new head automatically. Nonmaterial timestamps do not block.

Local receipt output is guarded separately: existing directory/parent
symlinks are rejected, the output directory is opened with
`O_DIRECTORY|O_NOFOLLOW`, and `transfer-review.json` is opened with
`O_NOFOLLOW` through the directory file descriptor. The receipt cannot
follow a malicious file symlink to overwrite the original SQLite authority.
The file and directory retain restrictive `0600`/`0700` modes.
These physical source/output protections are regression-tested.

## CLI

Run against an already-initialized, *same-source* canonical Brain SQLite
authority with a passing current report, not an unverified JSON snapshot.
The current Brain CLI checks its exact checked-out source SHA and clean active
tree, and `Store.read_report()` independently checks SQLite, ledger hash
chain, deterministic projection, freshness, source revision and pending events.

Save this small request as `transfer-request.json` outside the public
repository:

```json
{
  "schema_version": 1,
  "candidate_key": "Jacob-Met/workflow-checks:freight_packets/freightpkt/invoice_match.py",
  "target_repository": "P00NSMASHER/github-value-hunt-ledger",
  "pull_request_number": 343,
  "expected_head_sha": "9f68a2a0d22abd671ce7be353506a8b8cf9e5a52"
}
```

```bash
python -m brain transfer-review \
  --db brain-local/state.sqlite \
  --input transfer-request.json \
  --output brain-local/transfer-review \
  --expected-sha "$(git rev-parse HEAD)"
```

Read `brain-local/transfer-review/transfer-review.json` (local mode `0600`,
directory `0700`). The command uses the existing bounded GET-only GitHub
adapter. There are **no** target-system writes, GitHub POST calls, added
ledger events, attempt records, new report rows, credentials changes, paid
services, automated customer actions, or extra scheduled jobs.

If the report was built under a different Brain source revision, or has
expired, **do not** bypass its trust gate with a fabricated source SHA;
a new reviewed source revision must establish its own genuinely current
canonical report before this command is considered a source-verified result.
A missing SQLite path is rejected **before** Store initialization, so an
input typo cannot bootstrap an empty authority or generate a misleading
transfer outcome. The command does not drain input or write feedback,
report rows, attempt records or other canonical events.

**Physical read-only guarantee:** `Store.__init__` normally writes SQLite
metadata, sets PRAGMAs and changes file permissions. `transfer-review`
therefore NEVER opens the supplied canonical database with `Store`. It
opens the original using SQLite `mode=ro` and `query_only=ON`, verifies
SQLite integrity and foreign keys, then uses SQLite's consistent backup
operation to create a `0600` database in a disposable private `0700`
temporary directory. The normal `Store.read_report()` and provider GET
checks operate only on this temporary copy; the temporary directory and
all SQLite handles are closed and cleaned up on success or failure.
Symlinked or nonexistent original authority paths are rejected. Regression
tests also assert the source database's original bytes, modification time,
file permissions, and immutable event/report/attempt counts never change.
This snapshot is not a second authoritative ledger or synchronized writer.

## Status interpretation

| Result | What is verified | What is NOT verified |
|---|---|---|
| `DRAFT_PR_CHECKS_PASSED_NOT_ADOPTED` | Source link claimed in a draft; GitHub reported required exact-head checks green | Merged/integrated/deployed product, customer utility or recovery |
| `OPEN_PR_CHECKS_PASSED_NOT_ADOPTED` | Same evidence, open non-draft PR | Integration, operator approval, release |
| `CLOSED_UNMERGED_NOT_ADOPTED` | PR was closed without a merge | Production use or value |
| `MERGED_PR_METADATA_ONLY_NOT_DEPLOYMENT` | GitHub PR metadata says merged | Runtime deployment, correct behavior, actual customer adoption |
| `TRANSFER_TECHNICAL_EVIDENCE_BLOCKED` | Mandatory origin/check evidence missing or unreliable | Any positive technical outcome |

No result can create `feedback` with
`USEFUL`, `NOT_USEFUL`, or `INTEGRATED`. Those remain the separately
validated `OPERATOR_REPORTED` pathway. No result asserts positive dollars,
settlements, fee eligibility, ROI, time saved or measured false-positive rate.
Published third-party license metadata is for review, not a grant of
authorization beyond the repository's actual terms and applicable rights.

## Real first demonstration awaiting new-version release

- Original externally scheduled Brain source v4 was
  `9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`; the genuine research core
  [#37865121397](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37865121397)
  identified a source-reviewed invoice matching module, pinned to
  `Jacob-Met/workflow-checks@a5fd61b0c361c8a9b8a6737b33ecc9efab46e0ad`.
- RETALLY [PR #343](https://github.com/P00NSMASHER/github-value-hunt-ledger/pull/343)
  proposes a **first-party**, **REVIEW-only**, zero-validated-dollar
  cross-shipment invoice-reference detector; exact head
  `9f68a2a0d22abd671ce7be353506a8b8cf9e5a52`.
- Its Repository Release Gate, Freight Commercial Contracts and site
  verification checks passed on the draft head; deployment was skipped.
  The source-to-PR chain is
  [recorded in RETALLY](https://github.com/P00NSMASHER/github-value-hunt-ledger/pull/343#issuecomment-6072140000)
  and [in Brain](https://github.com/P00NSMASHER/portfolio-brain/pull/658#issuecomment-6072143103).

Those source and PR facts may be used to test this module against mocked
provider payloads on an isolated candidate, but they do **not** establish
that the new command has been deployed or has read the real production
SQLite. Do not claim an automatic feedback update or real commercial value.

## Release and safety

This is a standalone reviewed source proposal, **not an alternative Brain
architecture or third data store**. It reuses the existing CLI, SQLite report
and GitHub GET adapter, and adds one focused source-to-PR assessment.
All historical v2 FAIL, v3 BLOCKED and v4 PASS acceptance verdicts stay
unchanged. A new protected source revision must have exact-head Foundation
CI, independent App approval and its own acceptance. No draft PR may
inherit the old v4 PASS or merge solely because local tests are green.
