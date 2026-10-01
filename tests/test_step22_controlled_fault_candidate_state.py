from acceptance.step22_controlled_fault_target import acceptance_value


def test_acceptance_value_is_candidate():
    assert acceptance_value() == "CANDIDATE"
