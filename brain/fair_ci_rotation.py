"""Fair evidence sampling under the existing GitHub-native Brain cycle.

The canonical state sequence can advance by multiple events per run, leading
to stable modulo-N blind spots. A trusted normal brain-cycle GitHub RUN_NUMBER
increments for each run independent of event count and needs no new provider
calls, credentials, or persistent writer.
"""
from __future__ import annotations

from brain.core import require

MAX_SEQUENCE = 2**63 - 1


def rotation_counter(canonical_sequence, *, environment=None, real_adapter=False):
    require(type(canonical_sequence) is int
            and 0 <= canonical_sequence <= MAX_SEQUENCE
            and type(real_adapter) is bool, "FAIR_ROTATION_SOURCE_INVALID")
    env = {} if environment is None else environment
    require(type(env) is dict, "FAIR_ROTATION_ENV_INVALID")
    # Only the actual active workflow with its real adapter may use GitHub's
    # independent monotonic run number. Simulated adapters remain deterministic.
    if (real_adapter and env.get("GITHUB_ACTIONS") == "true"
            and env.get("GITHUB_WORKFLOW") == "brain-cycle-v2"):
        value = env.get("GITHUB_RUN_NUMBER")
        if type(value) is str and value.isascii() and value.isdigit():
            parsed = int(value)
            if 1 <= parsed <= MAX_SEQUENCE:
                return {"index": parsed, "basis": "GITHUB_WORKFLOW_RUN_SEQUENCE",
                        "extra_provider_requests": 0}
        return {
            "index": canonical_sequence,
            "basis": "INVALID_RUN_ID_FALLBACK_CANONICAL",
            "extra_provider_requests": 0,
        }
    return {"index": canonical_sequence,
            "basis": "CANONICAL_STATE_SEQUENCE",
            "extra_provider_requests": 0}
