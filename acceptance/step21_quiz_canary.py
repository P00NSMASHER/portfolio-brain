"""Harmless clean-room Step 21 canary implementation.

This module is acceptance-only and is not imported by production runtime paths.
It binds a tiny deterministic quiz-scoring pattern to the exact public Hunter
finding/proposal used by the existing value-proof contract.
"""
SOURCE_FINDING_ID = "HFD-CONTROLLED-HCP-QUIZLI"
SOURCE_PROPOSAL_ID = "HEXP-C0347811489FAD406302"
SOURCE_REPOSITORY = "pwenker/quizli"
SOURCE_REVISION = "d6538b13c16c093935ac2d0f175ac041aa5be4ef"
CAPABILITY_KEY = "capability-coverage:quiz"
AUTHORITY_GRANTED = False
PRODUCTION_IMPORTED = False

def bounded_quiz_score(correct: int, total: int) -> float:
    if type(correct) is not int or type(total) is not int:
        raise TypeError("quiz counts must be integers")
    if total <= 0 or correct < 0 or correct > total:
        raise ValueError("quiz counts out of bounds")
    return round(correct / total, 6)
