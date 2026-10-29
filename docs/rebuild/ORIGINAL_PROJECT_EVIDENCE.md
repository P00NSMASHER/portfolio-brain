# Original GitHub project evidence: measured synthetic work versus real-world value

The optional, **offline/read-only** evaluator `python -m brain.project_evidence`
accepts exactly two previously downloaded *original GitHub Actions ZIP archives*.
It requires explicit source/run/artifact identity and a SHA-256 digest copied from
the live GitHub provider metadata, and checks ZIP SHA-256, ZIP CRC, entry
allowlists, JSON uniqueness, case-level replay, false-review burden, source
digest shapes, and every no-revenue/no-customer/no-outreach invariant.

**Source boundary:** An operator-supplied expected digest is not an
independently authenticated provider statement. The operator must separately
reconfirm the artifact ID, run event/attempt, head SHA, exact original provider
digest, workflow identity, and release controls against the GitHub API. This
module proves local bytes match those stated facts; it never upgrades synthetic
results to buyer value or authorizes merges, payments, outreach or deployment.

## Independently inspected original source-bound artifacts (2026-10-14)

- **RETALLY:** [draft PR #461](https://github.com/P00NSMASHER/github-value-hunt-ledger/pull/461),
  head `2c681c38d75e483dbf5185d12112ac1c152012be`.
  [GitHub run 38605576151](https://github.com/P00NSMASHER/github-value-hunt-ledger/actions/runs/38605576151);
  original [artifact 11915258490](https://github.com/P00NSMASHER/github-value-hunt-ledger/actions/runs/38605576151/artifacts/11915258490).
  ZIP SHA-256 `0b38b36ffb484476c0814352f3b23a8fd5dff59874fdcdbe144a62b6e8411969`.
  Original downloaded ZIP digest and CRC independently matched. Raw report
  contains 12 developer-labeled synthetic cases: designed review cases
  **2/5 flagged by baseline vs 5/5 flagged by candidate**, known-benign
  consolidated/rebill cases **0/2 vs 2/2 flagged**, and 5/5 nonmatching
  controls remained unflagged. **This is extra *review sensitivity with extra
  benign burden*, not a demonstrated improvement in real-world accuracy,
  workload, claims, recovered dollars or paying customers.**
- **Product Factory:** [draft PR #46](https://github.com/P00NSMASHER/x402-product-factory/pull/46),
  head `c5b2b72e1df2cca55292e71bea3fcc7994242d84`.
  [GitHub run 38605466468](https://github.com/P00NSMASHER/x402-product-factory/actions/runs/38605466468);
  original [artifact 11915272910](https://github.com/P00NSMASHER/x402-product-factory/actions/runs/38605466468/artifacts/11915272910).
  ZIP SHA-256 `bda7216d2ae7932a0d8a55c8b69e3e713c9fe8e208926d230d5ac8e4a486e63a`.
  Original downloaded ZIP digest/CRC independently matched. It contains 11
  source-digested *qualitative review hypotheses*: 3 document, 4 quote and 4
  inventory. Actual consented conversations, externally confirmed workflow
  completions, buyer demand, customers and collected revenue are absent/unknown.

GitHub artifact retention is time-limited (configured 14 days); save legitimate
original archives and provider metadata privately if ongoing audit is needed.

## CLI manifest schema (review only)

```json
{
  "schema_version": 1,
  "scope": "EXACT_SOURCE_GITHUB_ARTIFACT_REVIEW",
  "sources": {
    "retally": {
      "repository": "P00NSMASHER/github-value-hunt-ledger",
      "head_sha": "2c681c38d75e483dbf5185d12112ac1c152012be",
      "run_id": 38605576151,
      "artifact_id": 11915258490,
      "artifact_name": "retally-review-2c681c38d75e483dbf5185d12112ac1c152012be-38605576151",
      "zip_sha256": "0b38b36ffb484476c0814352f3b23a8fd5dff59874fdcdbe144a62b6e8411969",
      "zip_path": "/absolute/private/path/retally.zip"
    },
    "product-factory": {
      "repository": "P00NSMASHER/x402-product-factory",
      "head_sha": "c5b2b72e1df2cca55292e71bea3fcc7994242d84",
      "run_id": 38605466468,
      "artifact_id": 11915272910,
      "artifact_name": "buyer-review-agenda-38605466468",
      "zip_sha256": "bda7216d2ae7932a0d8a55c8b69e3e713c9fe8e208926d230d5ac8e4a486e63a",
      "zip_path": "/absolute/private/path/factory.zip"
    }
  }
}
```

```sh
python -m brain.project_evidence --manifest /absolute/private/manifest.json \
  --output /absolute/private/evidence-report
```

The evaluator does not fetch new data, execute project source, contact buyers,
issue payments, alter durable SQLite state or issue work schedules. The result
is an operator-private report suitable for independent security/release review.
Its primary value is distinguishing *reproducible technical proof* from
*verified business value* and choosing the next falsification step.

**Next research priorities:** RETALLY needs independently adjudicated invoice
labels and timed human-review burden, including legitimate multi-load examples.
App Factory needs separately consented buyer conversations and verifiable
workflow-completion outcomes before another increase in app count is treated as
an improvement. Real-customer activation remains behind existing business,
contract, authorization, hosting and financial gates.
