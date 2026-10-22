# Native controller canary — source a654d582

This is a deliberately inert documentation-only change.

- Source: `a654d582817dacaa0ad9bc3e45f9cd217efffb67`
- Target: existing strict protected `main` process.
- Scope: one new Markdown file; no runtime, secrets, workflow, permission, or schedule changes.
- The branch is a staging artifact, not a release or acceptance certificate.
- A PR must not be opened or enrolled before independent source-specific six-hour acceptance.
- Once eligible, only the existing trusted-main controller may enroll GitHub-native auto-merge.
- GitHub's original auto-merge event and both issuer-pinned checks must be inspected afterward.
