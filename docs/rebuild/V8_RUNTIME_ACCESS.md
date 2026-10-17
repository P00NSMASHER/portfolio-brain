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

A separate runtime App installation is now present, but cross-project write
execution is not enabled or verified. Its installation covers all owner
repositories; mint only explicit one-repository tokens for approved targets.
Contents and pull request write access must be proved by a separately reviewed,
reversible draft-PR canary before enabling repair proposals. Do not grant administration, secrets management, verification-check
publication, or protection bypass. Grant workflow editing or deployment access
only through a separately reviewed project-specific adapter and release gates.

Keep credentials in the provider's supported secret store; never place them in
source, reports, issue comments, or chat. The Chat GitHub connector's session authorization cannot be transferred to
GitHub Actions. Provider-side runtime App provisioning and read-only token
minting have now been independently exercised; runtime write execution remains
a separate capability requiring original provider evidence.

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
`P00NSMASHER/portfolio-brain`. Its value was never inspected; its ability to
authenticate was subsequently verified in the original hosted run below.
The independent verifier remains App `5121826`, installation `166155679`.

Provisioning and bounded read-only unattended authentication have now been
verified with original hosted provider evidence. This is not proof of runtime
write actions, deploy permissions, or autonomous repair delivery.

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
deploy, edit ChatGPT tasks, or start acceptance. Its permanent main-only manual
workflow cannot run from the draft branch before protected adoption. The
one-time draft-branch test path used the exact immutable probe and was removed
after successful hosted verification.

## Original hosted read-only verification — 2026-10-17 UTC

- Original [Foundation Actions run 38992354373](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38992354373), attempt 1, completed SUCCESS, candidate head `dd18eaa35fdb4cf40ee08b9da3093fd8441e50ae`.
- Foundation `validate` and all **eight of eight** `v8-read-canary` jobs completed SUCCESS. The immutable reviewed `brain/v8/runtime_probe.py` Git blob was `c479f8c4f422a4e7de9bcb558127f8a2ab56378f`.
- Before private-key use, each job checked the original reviewed PR head plus completed exact-source `validate` (Foundation App `15368`) and `portfolio-phase1-gate` (separate verifier App `5121826`). Each minted and automatically revoked a one-repository, read-only short-lived token using App `5352505` / installation `172257326` and the stored GitHub secret.
- Authenticated reads verified App identity, token inventory of exactly one expected repository, default-branch source, and Actions, Checks, Statuses and Pull Requests endpoint access. The token read probes executed with isolated Python standard-library code. No private-key or token contents were collected or published.
- The one-time PR-body activation marker was removed, and the temporary Foundation-CI integration and its temporary tests were reverted to the existing `main` definition. Permanent `v8-runtime-preflight.yml` stays manual-only, main-only and pending protected review.
- **Verified:** runtime secret authentication and bounded read-only observation for eight sources. **Not verified:** runtime source writes, draft-PR creation, deployment, merge, private task API, outcome learning, terminal production acceptance or five-gigabyte live storage. Production `main`, scheduled cores, existing tasks and acceptance clocks were not changed by this proof.

