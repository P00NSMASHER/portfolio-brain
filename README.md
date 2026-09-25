# Portfolio Brain

Private autonomous portfolio intelligence control plane for PRJ-000.

This Step 1 foundation is intentionally non-operational. Nothing here grants downstream write authority, schedules autonomous work, invokes a model, deploys infrastructure, contacts customers, moves money, or trades.

## Foundation

- `FOUNDATION_SKELETON.json` declares the intended top-level architecture.
- `registry/PROJECT_REGISTRATION_CONTRACT.json` is the deny-by-default Step 1 registration contract.
- `docs/ARCHITECTURE_CONTRACT.md` defines hard evidence and authority boundaries.
- `tests/validate_foundation.py` is the deterministic foundation validator.
- `.github/workflows/foundation-ci.yml` runs read-only bounded validation.
- `PORTFOLIO_BUILD_STATE.json` is the durable master cursor.

Empty implementation directories are represented by the skeleton manifest until their numbered build step creates real content.
