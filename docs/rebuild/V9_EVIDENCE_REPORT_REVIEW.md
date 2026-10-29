> October 29 integration note: original review notes below are historical. Prepared on main 25e697c in PR #787; fresh checks and independent review are required. No release authority or live acceptance is granted.

# V9 source-specific evidence report — independent-review candidate

**Status: DRAFT ONLY.** This branch is derived from protected source `4393488059c8f7f02ce665a514a10198feae270c`. It adds an offline, read-only deterministic summary tool and adversarial tests. It does **not** modify the running Brain or its workflows, create a schedule, call GitHub/Cloudflare, manufacture provider originals, or authorize a merge.

The report consumes the `proof-census.json` and optionally the `proof-provisional.json` from the independent, source-pinned technical reviewer. It rejects duplicate JSON keys, NaN, wrong source, malformed run/state identity, implausible gaps, timing-status conflicts, inconsistent original state/replay receipts and attempts to inject approval flags. It fingerprints normalized input for change tracking; SHA256 is not a provider signature.

For a real early-window proof, from an isolated checkout:

```sh
python -m verification.v9_release_report \
  --source 4393488059c8f7f02ce665a514a10198feae270c \
  --census proof-census.json \
  --replay proof-provisional.json \
  --output v9-release-evidence-summary.json
```

Technical readiness is never release approval. Even after ≥21,600 seconds of successful genuine automatic monitors and a final independent terminal raw SQLite/event/ledger/report replay, **an independent original Cloudflare provider census, a separately governed owner acceptance on the exact source, and fresh required GitHub protected checks remain mandatory**. No source receipt is written by this tool, no existing acceptance is updated, and no prior-source certificate transfers.

Existing true negative controls remain visible: historical canceled core and test-harness failures are not silently turned into successes. This branch must not be merged while active source-specific soak/release holds remain. Run `python -m unittest discover -s tests -p test_v9_release_report.py -v` offline to reproduce the 10 hostile tests.
