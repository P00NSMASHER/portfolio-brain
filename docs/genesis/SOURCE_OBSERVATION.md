# Source observations and executable capability reporting

The third increment adds a real read-only HTTPS adapter and connects it to durable
mission planning. It does not activate an unattended v9 executor or grant writes.

## Executable interfaces

`python -m brain.v9 observe-plan --mission mission.json --journal /private/kernel.sqlite`

The command validates the mission and existing journal before network access, reads
an already authorized token from `V9_GITHUB_READ_TOKEN`, observes exact canonical
repository identities, actual pull permission and default-branch heads twice, then
projects the journal against those observed heads. A changed source blocks planning.
The journal is read-only. The token is not printed, persisted, placed on the command
line, or sent to any host besides api.github.com. No credentials are created.
Missing credentials block; ChatGPT connector access does not establish this runtime
credential. This implementation has unit/integration tests, not a live authenticated
execution of its direct HTTPS transport in the implementation session.

`observe_repositories` additionally accepts explicit file paths. It binds contents
to the immutable commit and Git tree, rejects symlink/submodule modes and truncated
trees, and verifies Git blob and SHA256 digests. GitHub's Contents API can return a
symlink target as a normal file, so Contents type alone is insufficient:
https://docs.github.com/en/rest/repos/contents

Requests are GET-only, fixed-host, no redirects or proxies. Limits: 16 repositories,
16 paths per repository, 1MiB per response, at most336 requests, 15-second response
budget and60-second observation budget. These are cooperative deadlines and late
response rejection, not a process sandbox or hard wall-clock guarantee: OS DNS,
connection and header processing can delay return. Oversized recursive trees block
rather than partially certify files. Permission/head observations are point-in-time;
a future independently authorized writer must recheck and reconcile provider writes.
The injectable test transport is labeled INJECTED_TRANSPORT_OBSERVATION, never
represented as authenticated runtime evidence. No remote file content is executed.

`python -m brain.v9 registry --root /path/to/portfolio-brain`

This validates the fixed matrix/scorecard paths, all66 capability identities and
four tier ranges, declared statuses, source/test references, bounded JSON, resource
limits and metric evidence requirements. Unknown remains null. Files and evidence
references are declarations, not proof of passing tests. Reported source revisions
are explicit; absent revisions stay unknown rather than borrowing baseline source.
The command cannot promote maturity or grant release authority. Symlinks/traversal
are rejected; local filesystem checks assume no hostile concurrent replacement.

## Validation and authority

Automated tests include permission denial, wrong canonical identities, changed
heads, corrupt blobs, symlink/submodule/truncated tree, invalid JSON/base64, secret
non-disclosure, redirect refusal, response/time budgets, readonly journal integrity,
invalid mission before provider calls, missing token, duplicate capability IDs,
missing evidence, path traversal and unsupported metric claims. Independent review
executed53 v9 tests successfully before documentation additions. Exact final CI and
source revisions are retained in PR718; no candidate can issue its own acceptance.

Separate authenticated connector reads during implementation rechecked Brain main
`d25b54041341089482ad55e5d270171879e186b1` and PermitPlate main
`cf0b459217245a7799550104cc37a9bad462bdf2`, read explicit files at those revisions,
and rechecked unchanged heads. Brain contracts blob:
`98dc71990bc44a72a85590f37a6bdd277cf600ec`; PermitPlate workflow blob:
`167cf0a263b41da50927b300decdbce6ecadeaf9`. These support source discovery only;
they are not a live run of the new HTTPS adapter, a target repair or a deployment.

## Adoption and recovery

Issue702 records the d25 source hold released on2026-10-18 at05:39Z following14
qualifying automatic cores spanning22799seconds and independent terminal SQLite
replay. This acceptance belongs only to d25. The v9 branch may now proceed through
existing protected review and delivery, with a fresh source-specific observation
window for any new production source. Existing schedules and release controls stay
unchanged. The prior hold text in earlier receipts remains historical evidence.

Failure does not mutate the journal or provider. Preserve the original error and
observations; fix source/input or obtain an already authorized valid credential
before retrying. Never retry403/denied permissions by expanding credentials.
Remaining dependencies: actual approved runtime credential/environment, independent
execution admission, transactional provider-write reconciliation, original target
acceptance and served-behavior verification. No full tier is claimed complete.
