# Phase 1 owner setup and remaining acceptance

This repository uses a solo-maintainer trust model: GitHub requires pull-request integration, but **does not require a second human approval**. Independent verification is supplied by the separately credentialed GitHub App check `portfolio-phase1-gate`. The App is a distinct principal from GitHub Actions and from the repository-writing connection.

The attached `portfolio-main-protection.json` is the baseline ruleset import. It targets only `main`, blocks deletion and force-push, requires pull requests, requires conversation resolution, and requires up-to-date `validate` from GitHub Actions (App 15368). Its approving-review count is deliberately zero. After the verifier App is registered and publishes its first check, add `portfolio-phase1-gate` as a required status check from that exact App.

An authenticated administrator can import the file from repository Settings > Rules > Rulesets > New ruleset > Import a ruleset. Review it and select Create. Reuse an equivalent existing ruleset rather than creating duplicates. No token, password or App private key should be pasted into chat or committed to this repository.

## Independent verifier

The verifier App must be separately credentialed and have only the permissions needed for evidence reads and check publication. Candidate code must not control its private key or runtime. The release policy remains deny-all until the real App ID and trusted evidence sources are configured.

The verifier check replaces the previously proposed second-human-review requirement. This is intentional for a single-owner repository: independence comes from a separately protected principal and runtime, not from pretending the same owner can provide two identities.

## Read-only preflight

Run:

```sh
python -m verification.protection --output protection-observation.json
```

Without a real gate App ID, the result remains BLOCKED. After installation, pass its actual ID with `--gate-app-id`. CONFIGURATION_OBSERVED proves only that effective rules contain the expected settings and issuers. It is not a rejected-write test or Phase 1 acceptance.

## Acceptance

Required evidence remains: authorized ruleset installation; registered/installed verifier App; verifier check required from the exact App; safe negative enforcement proof; legitimate positive protected integration of the exact candidate; and post-integration checks. No Phase 2 work is included.
