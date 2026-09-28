# Phase 1 owner setup and remaining acceptance

The attached `portfolio-main-protection.json` is a baseline ruleset import, not proof that protection is installed. It targets only main, requires one approval, stale-approval dismissal, conversation resolution and up-to-date `validate` from GitHub Actions (App 15368), and blocks deletion and force-push with an empty bypass list. It does not require the branch-only `phase1-regressions` job or invent an independent App.

An authenticated administrator can import the file from repository Settings > Rules > Rulesets > New ruleset > Import a ruleset. Review it and select Create. Reuse/reconcile an existing equivalent ruleset instead of creating duplicates. This change intentionally blocks PRs without an eligible independent reviewer. The author cannot approve their own PR; another chat on the same account is not a different reviewer.

This is only the baseline settings portion. Before calling Phase 1 accepted, establish an independently protected verifier implementation and approved reviewer, configure real evidence-source allowlists, publish the dedicated verifier check, and add that check with its exact App source. Do not enter a placeholder App ID or add a nonexistent required check. The release policy remains deny-all until those prerequisites are legitimately configured. No token, password or App private key should be pasted into chat or committed to this repository.

## Read-only preflight

From a trusted local checkout with Python, run:

```sh
python -m verification.protection --output protection-observation.json
```

Without an approved gate App ID, the result is BLOCKED. After a real App is installed and its check is configured, pass its actual ID with `--gate-app-id`. This command reads public GitHub metadata without loading credentials from the environment. It does not edit rules, create a check, approve, merge, or deploy.

CONFIGURATION_OBSERVED means the effective repository-level rules contain the required settings and expected check issuers. It is not a rejected-write test, an independently verified deployment, or Phase 1 acceptance. A hidden `bypass_actors` field remains UNKNOWN. Use a separate authorized administration review to verify hidden bypass settings; do not grant the ordinary verifier administration-write permission just to make this observation green. Classic branch protection and inherited organization rules are not handled by this bounded adapter and must be independently verified before a compatible adapter is added.

## Continuation repair

A synthetic probe of the original PR167 verifier at e40fdf5d returned EVIDENCE_VALIDATED_NOT_MERGED even for an explicitly unprotected branch and a candidate behind current main. It never requested effective rules or commit ancestry. This was a code-level simulation, not an actual bypass of GitHub.

The continuation adds effective-rule checks, candidate ancestry, strict job/check/run-attempt linkage, and rereads mutable approvals, checks, runs, protection and PR state before returning a read-only verdict. GitHub remains responsible for atomic enforcement at merge time; metadata readbacks alone cannot eliminate all races. Checks must still be independently implemented rather than merely trusted by their displayed name.

## Acceptance remains separate

Required next evidence: authorized installation; independent verifier/reviewer identity; negative enforcement tests on safely scoped branches; legitimate positive protected integration of the exact reviewed revision; and post-integration checks. No Phase 2 repair, model spending, schedule change, rights-policy change, or merge is included in this continuation.

Primary implementation references:
- https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch
- https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset
- https://docs.github.com/en/rest/commits/commits#compare-two-commits
