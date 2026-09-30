"""Harmless non-production target for governed live repair acceptance.

The baseline value is intentionally stable on main. The controlled repair proof
may change it only on an isolated factory candidate branch, together with a new
regression test. No production runtime imports this module.
"""


def acceptance_value() -> str:
    return "BASELINE"
