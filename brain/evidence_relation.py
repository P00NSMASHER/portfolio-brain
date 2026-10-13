"""Fixed, noncausal relation between original CI evidence and one bounded recheck.

A reobserved check is NOT a confirmed fix, first failure time, continuous
outage, common cause, repair authority, trade or release acceptance. This
pure function reads neither provider state nor the canonical SQLite ledger.
"""
from __future__ import annotations

_ORIGINAL = frozenset({
    "INITIAL_ADVERSE_TRANSITION",
    "PERSISTENT_ADVERSE_OBSERVED",
    "UNBASELINED_ADVERSE_OBSERVED",
    "EVIDENCE_GAP_REVALIDATION",
    "RECOVERY_OBSERVED_NOT_RESOLUTION",
})
_OUTCOMES = frozenset({
    "STILL_ADVERSE", "SUCCESS_OBSERVED_NOT_RESOLUTION",
    "CHECK_NOT_COMPLETED", "OTHER_CONCLUSION_NOT_RESOLUTION",
    "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK",
})
_RELATIONS = frozenset({
    "NEW_ADVERSE_REOBSERVED",
    "PERSISTENT_ADVERSE_REOBSERVED",
    "UNBASELINED_ADVERSE_REOBSERVED",
    "ORIGINAL_ADVERSE_NOT_REOBSERVED",
    "RECOVERY_NOT_REPRODUCED",
    "RECOVERY_REOBSERVED_NOT_FIX_VERIFIED",
    "GAP_RECHECK_ADVERSE",
    "GAP_RECHECK_SUCCESS_NOT_FIX_VERIFIED",
    "CURRENT_EVIDENCE_INCOMPLETE",
})


def source_followup_relation(original_class, current_outcome):
    """Classify checked-state relation, not cause or independently proven fix.

    The original class must come from a replay-verified same-source plan;
    the current outcome must come from one exact-commit GitHub recheck.
    """
    if (type(original_class) is not str or original_class not in _ORIGINAL
            or type(current_outcome) is not str
            or current_outcome not in _OUTCOMES):
        raise ValueError("CI_EVIDENCE_RELATION_UNVERIFIED")
    if current_outcome not in {
        "STILL_ADVERSE", "SUCCESS_OBSERVED_NOT_RESOLUTION"
    }:
        return "CURRENT_EVIDENCE_INCOMPLETE"
    if original_class == "RECOVERY_OBSERVED_NOT_RESOLUTION":
        return ("RECOVERY_NOT_REPRODUCED"
                if current_outcome == "STILL_ADVERSE"
                else "RECOVERY_REOBSERVED_NOT_FIX_VERIFIED")
    if original_class == "EVIDENCE_GAP_REVALIDATION":
        return ("GAP_RECHECK_ADVERSE"
                if current_outcome == "STILL_ADVERSE"
                else "GAP_RECHECK_SUCCESS_NOT_FIX_VERIFIED")
    if current_outcome == "SUCCESS_OBSERVED_NOT_RESOLUTION":
        return "ORIGINAL_ADVERSE_NOT_REOBSERVED"
    return {
        "INITIAL_ADVERSE_TRANSITION": "NEW_ADVERSE_REOBSERVED",
        "PERSISTENT_ADVERSE_OBSERVED": "PERSISTENT_ADVERSE_REOBSERVED",
        "UNBASELINED_ADVERSE_OBSERVED": "UNBASELINED_ADVERSE_REOBSERVED",
    }[original_class]


def allowed_relations():
    """Fixed vocabulary for names-free public summaries."""
    return _RELATIONS
