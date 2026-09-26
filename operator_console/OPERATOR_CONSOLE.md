# Portfolio Brain Authenticated Operator Console

The Operator Console is intentionally separate from the public GitHub Pages command center.

## Authentication boundary

The console is implemented as the GitHub Actions workflow:

    .github/workflows/operator-console.yml

GitHub authentication and repository permissions are required to dispatch it, and the job additionally requires:

    github.actor == github.repository_owner

The public command center contains no operator link, control form, mutation endpoint, access token, or private payload.

## Operations

- STATUS — restores durable state and produces a sanitized operator report artifact.
- EVIDENCE_REPORT — produces the same sanitized drill-down evidence package.
- CANCEL_QUEUE_ITEM — cancels one exact QUEUED/ACTIVE scheduler work item by work ID and persists a new scheduler artifact.
- RERUN_WORKFLOW — triggers one allowlisted recurring workflow.
- EMERGENCY_STOP — requests cancellation of every active managed autonomous workflow run.
- PROPOSE_PAUSE / PROPOSE_RESUME — creates a reviewed pull request changing exactly one persistent kill switch.
- PROPOSE_BUDGET — creates a reviewed pull request changing the finite portfolio USD/model/API ceilings.
- PROPOSE_APPROVAL — creates a reviewed pull request containing a sanitized exact owner-approval record.

Persistent policy changes never modify main directly. They are committed to an operator branch and opened as a pull request so normal CI and repository review gates remain in force.

## Public/control boundary

Raw Gmail recipients, message bodies, credentials, secrets, and private customer/child payloads are not valid operator inputs. The free-text rationale is hashed before any persistent policy record is written.

Queue cancellation mutates only the durable scheduler artifact. It does not create ACT authority.

An owner approval may allow the scheduler to prepare evidence work for an exact previously human-gated source, but it does not itself send communications, deploy, move money, trade, merge code, or bypass the independent action-engine/channel policy.

## Access

Open the repository's Actions tab, choose **operator-console**, then choose **Run workflow** while authenticated as the repository owner.

## Visibility note

The control surface is not published on GitHub Pages and execution is owner-gated by GitHub Actions. Because this repository is public, workflow definitions, run metadata, logs, and artifacts can have GitHub-level visibility consistent with the repository and Actions settings. Therefore every operator report and receipt is sanitized and must never contain secrets or private payloads.
