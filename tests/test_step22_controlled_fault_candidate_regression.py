from acceptance.step22_controlled_fault_target import acceptance_value


def test_controlled_fault_target_returns_candidate():
    assert acceptance_value() == "CANDIDATE"
