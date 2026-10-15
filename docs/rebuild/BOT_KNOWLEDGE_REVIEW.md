# Narrow unattended Brain knowledge upgrade review

The existing Brain scheduler creates a bot-authored, exact-source knowledge-only
PR and explicitly dispatches Foundation CI. On October 14, bot-created PR #688
had a successful dispatch validation but no completed independent
`portfolio-phase1-gate`; the separate trusted reviewer was activated by
`workflow_run` for human PRs, not reliably for that GitHub-token-created
dispatch. Do not mark source green CI as an accepted protected merge.

This proposal adds an **explicit main-owned dispatch** for knowledge-only bot
PRs, reusing the same independently installed verifier App 5121826 and original
Foundation check from Actions App 15368. It does not create a cron or remove
the existing `portfolio-independent-verifier.yml` workflow.

Controls: exact bot author, main as base, bot branch matched to a full
SHA-256 knowledge fingerprint, current-main ancestry, **exactly one modified
file** (`brain/REUSE_KNOWLEDGE.json`), bounded schema and public source refs,
validated source hashes, a real successful Foundation `validate` at the
candidate SHA, network-disabled/capability-dropped full + Phase 1 +
operating-mode tests, independent verification run from main (not candidate),
a separately minted verifier App token after tests, and a SHA-guarded
branch-protection merge. Any missing provider evidence, changed base, other
file mutation, failed check, unverified source or lack of privileges fails
closed. The merge response must report `merged=true` and resulting main
needs separate readback before claiming a completed live upgrade.

The bot may propose safe **read-only structural reuse knowledge**, not
arbitrary code patches, paid calls, real customer contact, credential changes,
money actions, trading, financial source promotion, protected V5/V6 signed
soak evidence or independent security approval. Source status remains
**DRAFT / NOT DEPLOYED** until the preexisting protected-main release
authority has independently cleared the unchanged original signed-soak gate.
Bot self-review is deliberately restricted to knowledge-data-only PRs,
not arbitrary assistant-generated code.

This is a source-pinned independent gate improvement, not proof that PR #688
merged or that autonomous remediation can handle every human-only task.
