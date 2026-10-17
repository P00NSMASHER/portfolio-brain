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

A separate runtime App installation is present. An independently gated, one-time
write canary has proved that one-repository Contents/PR write tokens can create,
read back, close, and fully remove an isolated draft PR in `capturebrief`.
This proves a bounded credential operation, **not** an installed unattended
cross-project repair executor. Installation covers all owner repositories:
only mint one-repository tokens for explicitly approved targets. Do not grant administration, secrets management, verification-check
publication, or protection bypass. Grant workflow editing or deployment access
only through a separately reviewed project-specific adapter and release gates.

Keep credentials in the provider's supported secret store; never place them in
source, reports, issue comments, or chat. The Chat GitHub connector's session authorization cannot be transferred to
GitHub Actions. Provider-side runtime App provisioning, read-only token minting, and one
reversible scoped write were independently exercised. Additional repair/execution
authority requires separate source-specific reviews and provider evidence.

Before enabling unattended repairs, recheck the installation's actual target
inventory and permissions, exact source, protected branch rules, and independent
verifier identity for each separately approved adapter. The one-time `capturebrief`
draft-PR canary and denied out-of-scope branch write are proved below, but are
not reusable authorization for new targets or unsupervised write decisions.
Reconcile uncertain writes before retry. Merge and deployment remain gated by
the target project's protections and independent production verification.
No runtime deployment or automated substantive repair is verified here.

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
verified with original hosted provider evidence. A separate bounded write
canary passed later; neither proof establishes deploy permissions or autonomous
repair delivery.

Candidate `v8-runtime-preflight` is manual-only and main-only. After protected
review/merge, it first checks the exact reviewed Git blob of the standalone
probe, then runs it with isolated Python (`-I`) outside the repository package.
It mints a short-lived **read-only, one-repository** token for each
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
- **Verified by this read test:** runtime secret authentication and bounded read-only observation for eight sources. See the separately verified, one-repository write canary below. **Still unverified:** automated substantive repairs, deployment, merge, private task API, outcome learning, terminal production acceptance and five-gigabyte live storage. Production `main`, schedules, tasks and acceptance clocks were not changed by this proof.


## Original hosted reversible runtime write verification — 2026-10-17 UTC

- [Original run 38994453674](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38994453674), attempt 1, completed SUCCESS, exact tested source `701d8d76dd5b6c6b46546b0027e86b10443cd151`. Before minting a write credential, the job checked the original exact-head Foundation App `15368` and independent verifier App `5121826` successful checks and open same-repo draft PR identity.
- Runtime App `5352505`, installation `172257326`, created a short-lived token limited to `P00NSMASHER/capturebrief`, with Contents/PR write scope and automatic revocation. Its original token inventory contained **one repository**.
- The token's attempted Git-ref write outside scope, in `P00NSMASHER/portfolio-brain`, received **HTTP 403**. No denied branch remained.
- `portfolio-brain-v8-runtime[bot]` created the one-file non-executable branch `v8-runtime-canary-38994453674` and [CaptureBrief draft PR #46](https://github.com/P00NSMASHER/capturebrief/pull/46), commit `5fc5f8a5dc854921329a48d2aa68358f6a720e8c`. It independently read back the file and PR, then **closed the PR without merging** and **deleted the temporary branch**. GitHub provider readback confirms author, closed draft state, and no merge. No production file changed.
- Original nonsecret proof artifact `12086078230`, name `v8-runtime-write-canary-38994453674`, ZIP SHA-256 `676f176402ce83e64e27780e400502928f25ff7d61b65e6f3e9d57e1f341f958`. Downloaded original ZIP 570 bytes, matching provider digest and passing CRC, then parsed the original JSON: `cross_repo_write_denied_http=403`, `scoped_token_repository_count=1`, `draft_verified_then_closed=true`, `temporary_branch_deleted=true`, `acceptance_started=false`.
- Independent repository readback after cleanup: CaptureBrief main `4a7c5d6c223b8488995ab221dc169ba32ae828f8`, Portfolio Brain main `98cce23ac031ccf9ffa7008a83e9a9b25571d568`; neither changed. One-shot PR activation marker, temporary CI job and temporary implementation/tests were removed from the candidate branch. Original non-secret evidence remains in the GitHub provider run and issue tracker.

This is **proof of one reversible, repository-scoped draft-PR write capability**. It is **not** proof of autonomous code repair, production merges/deploys, installed target-specific repair orchestration, a private task service, an active new soak, or an overall V8 release certification. Independent release/acceptance gates remain in force.

## Focused code audit: response integrity and credential isolation

The previous read-only probe validated repository inventory and source, but
accepted a successful HTTP response for Actions, Checks, Statuses or Pull
Requests **without validating its response body**. A malformed HTTP 200
response could falsely produce `AUTHENTICATED_READ_CANARY_PASSED`. That
false-positive path is now closed by explicit response schemas, exact source
status SHA checking, and adversarial tests covering incomplete, wrong-type,
wrong-count, misidentified and error-shaped responses.

The GitHub Actions workflow checks the reviewed Git object digest of
`brain/v8/runtime_probe.py` **before** minting any App credential, copies
only that approved stdlib-only code outside the repository checkout, and runs
it with `python -I`. The trusted token action stays pinned and automatically
revokes the per-repository read-only token. Manual/main-only triggers,
production scheduling, existing release gates and the all-project registry
remain unchanged. GitHub-hosted final-head CI and independent verifier checks are required
for each changed commit. Historical original canary receipts are source-bound.

## Live stricter runtime readback — original provider PASS

- [GitHub Actions original run 38999469004](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38999469004) (attempt 1, SUCCESS) tested candidate source `0aef2d03a0aa3065f3b3ef807e48834fd09479ba`. Both exact-head Foundation App 15368 and independent verifier App 5121826 checks passed before minting credentials.
- All **eight of eight** repository-scoped matrix jobs completed SUCCESS with the **revised** strict response validator and isolated `python -I` execution. The App tokens were read-only, minted per repository and automatically revoked. Original job conclusions were independently read from GitHub; the one-shot PR marker and temporary CI job were then removed.
- The production `main` source, recurring schedules, state branch, external clock and acceptance evidence were unchanged. This confirms the reviewed credential can perform strictly validated **read operations**; it does not authorize automatic code repair, merges/deployment, or certify six-hour unattended recovery. Future production source requires its own independent validation and acceptance.
