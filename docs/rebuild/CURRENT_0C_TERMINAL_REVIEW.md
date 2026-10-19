# Current protected-source terminal replay: read-only review branch
- Pinned protected main: `0c1184d2e3c614de48a0cb8ce0e5d059a87c72ee`
- Original first qualifying source window begins with a genuine automatic monitor completion, not a push or dispatch ACK.
- The reviewer is adapted from historical draft PR #717. Only source pin, original transition cutoff, and adversarial fixture date are updated.
- The review workflow runs on this isolated branch only and uses read-only GitHub Actions permissions (contents, actions). No production commits, state writes, schedule, deployment, credentials, customer communications, or release commands.
- It independently audits original GitHub run attempts, job steps, artifact ZIP digests/CRC and delivery/Git ancestry before reconstructing the terminal state from pinned source and state commit.
- The original source verifier has an explicit, preserved policy: it does NOT certify independent Cloudflare telemetry and does NOT authorize release, merge, or unrestricted autonomy.
- External Cloudflare provider evidence must be reviewed separately and correlated before the acceptance issue can be concluded.
