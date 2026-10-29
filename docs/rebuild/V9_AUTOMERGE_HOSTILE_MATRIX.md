> October 29 integration note: original review notes below are historical. Prepared on main 25e697c in PR #787; fresh checks and independent review are required. No release authority or live acceptance is granted.

# Guarded native merge — hostile input test laboratory

**Dependent DRAFT review only.** This branch starts at the immutable, unmerged PR #725 head `24ae3d2ffae4175b200e364035dc85facea170da`. It adds only a new offline hostile-input test module; no production code, workflow, schedule, policy, GitHub permission or user-owned release setting changes.

The tests exercise hostile GraphQL repository and ruleset identities, duplicate/truncated/paginated ruleset records, numeric/bool/null/string bypass counts, untrusted REST bypass claims, final-rule mutation races, independent status-check issuer substitution, PR-head changes, arbitrary GraphQL mutations and REST/URI traversal smuggling. Every hostile case must produce **zero GitHub native merge mutations**. The positive original-token scenario must also deny acceptance until a separately governed source-specific receipt exists.

```sh
python -m unittest discover -s tests -p test_v9_guarded_merge_hostile_matrix.py -v
```

This is a synthetic security laboratory, not an independent human review or a live controller canary. The new suite must pass on the candidate source in isolation and receive independent CI before it can be proposed for adoption. Do not merge this branch into production or merge PR #725 before the existing original automatic-core six-hour acceptance and independent release gates. Broad code or deployment auto-merge remains disabled.
