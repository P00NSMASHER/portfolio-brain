import inspect

from state_journal import smoke_dispatch


def test_barrier_precedes_dispatch():
    source = inspect.getsource(smoke_dispatch.main)
    assert source.index("wait_for_canonical_freshness()") < source.index("dispatch_and_wait")


def test_barrier_is_fail_closed():
    source = inspect.getsource(smoke_dispatch.wait_for_canonical_freshness)
    assert "STALE_CANONICAL_STATE_PENDING_REDUCTION" in source
    assert "Canonical freshness check failed" in source
