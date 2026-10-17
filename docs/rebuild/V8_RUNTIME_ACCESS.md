# V8 runtime access and remaining activation requirements

## Verified configuration, 2026-10-16

The Brain cycle uses `github.token` for its own repository. Its monitor job
declares contents, pull requests, and actions write scopes. These declarations
do not prove an operation was permitted or performed. The authority receipt is
bound to the complete reviewed workflow digest; extra scopes, substituted
credentials, or other workflow edits require a new review before the receipt
can be issued. A digest change does not grant authority.

Cloudflare's connected account contains one Worker, `portfolio-brain-recovery`.
Its settings expose only the secret binding names `GITHUB_ACTIONS_TOKEN` and
`SIGNING_KEY_PKCS8`. No secret values were retrieved. The reviewed Worker code
uses these for the Brain recovery clock; their names alone do not establish
effective GitHub scopes. There is no verified cross-project repair executor in
that deployment. The independent verifier App must remain separate from any
repair executor and its credential must not be reused for repairs.

## Cross-project repair activation

An administrator must provision a separate supported runtime installation for
the repair executor, restricted to explicitly selected project repositories.
Start with repository contents and pull request access sufficient to propose
repairs. Do not grant administration, secrets management, verification-check
publication, or protection bypass. Grant workflow editing or deployment access
only through a separately reviewed project-specific adapter and release gates.

Keep credentials in the provider's supported secret store; never place them in
source, reports, issue comments, or chat. The current Chat GitHub connector does
not expose installation/credential provisioning, and its session authorization
cannot be transferred to a GitHub Actions runner. User approval already exists;
the missing step is provider-side provisioning, not another general approval.

Before enabling writes, verify the installation's actual repository inventory
and permissions, exact source, protected branch rules, and independent verifier
identity. Then perform one reversible draft-PR canary on an authorized branch,
test denial outside the allowed repositories, and independently verify original
provider receipts. Reconcile uncertain writes before retry. Merge and deployment
remain gated by the target project's protections and production verification.
No runtime write or deployment capability is verified by this document.

## ChatGPT tasks and acceptance

There is no supported unattended ChatGPT task API configured in this runner.
The existing private reconciliation adapter requires a supported Chat owner and
verified private durable storage before real task edits. Do not invent an API,
export session credentials, or claim a local adapter provides runtime access.

The user requires the upgrade plan to finish before a new six-hour acceptance
run starts. Candidate preparation and CI do not start that run. Preserve current
production schedules and historical evidence; unresolved runtime prerequisites
must remain explicit blockers rather than being marked complete by unit tests.

## Provider provisioning observed 2026-10-17 UTC

Authenticated GitHub settings show runtime App `portfolio-brain-v8-runtime`
(App ID `5352505`) installed on the owner's **all current and future repositories**
as installation `172257326`. The owner chose this scope. Observed permissions:
contents and pull requests read/write; actions, checks, statuses and metadata
read. The Actions secret name `PORTFOLIO_RUNTIME_PRIVATE_KEY` is present in
`P00NSMASHER/portfolio-brain`; its value was not inspected or tested here.
The independent verifier remains App `5121826`, installation `166155679`.

The earlier provisioning prerequisite is now satisfied at the settings level.
It is not proof that the stored credential authenticates in an unattended runner.

Candidate `v8-runtime-preflight` is manual-only and main-only. After protected
review/merge, it mints a short-lived **read-only, one-repository** token for each
of the eight explicit reviewed repositories. It rejects unexpected App identity
or token inventory, reads exact source and capability endpoints, emits only a
sanitized summary, and revokes the token at job completion. Its explicit token
scope prevents the all-repositories installation from automatically including
future projects. Provider response reads are bounded and redirects rejected.
No private key reaches project code or test processes; only the pinned token
creation action consumes it.

This candidate does not alter recurring Brain schedules, permit repairs, merge,
deploy, edit ChatGPT tasks, or start acceptance. The main-only runtime canary
cannot run from this draft branch. After its real run passes, independently
verify the original run receipt before preparing a separately gated draft-PR
write canary. No runtime authentication, repair success, or production health
improvement is claimed from the offline tests.
