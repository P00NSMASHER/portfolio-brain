from state_journal import smoke_dispatch

def test_barrier_exists():
    assert callable(smoke_dispatch.wait_for_canonical_freshness)
