"""Harmless, unused target for the final Step 22 autonomous-repair proof.

Production runtime does not import this module. The acceptance lane deliberately
observes BASELINE as a controlled reproducible fixture and authorizes the
isolated repair candidate to change only this target to CANDIDATE plus a brand
new regression-test file.
"""


def acceptance_value() -> str:
    return "CANDIDATE"
