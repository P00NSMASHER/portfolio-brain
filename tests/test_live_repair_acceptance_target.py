from software_factory.live_repair_acceptance_target import acceptance_value


def test_acceptance_value_is_candidate():
    assert acceptance_value() == "CANDIDATE"
