"""Shared bounds for provider reads and replayable repository observations."""

MAX_REQUESTS = 24
CHECKS_PER_PAGE = 100
# Repository metadata plus initial and final branch identity reads consume
# three requests. This is the largest complete snapshot one operation can
# obtain; the adapter also enforces the *remaining* shared request budget.
MAX_REPOSITORY_CHECKS = (MAX_REQUESTS - 3) * CHECKS_PER_PAGE
