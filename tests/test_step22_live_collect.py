import unittest

from acceptance.step22_live_collect import select_trusted_check


HEAD = "a" * 40


def check(cid, *, name="validate", app_id=15368, head=HEAD, conclusion="success", completed_at="2026-10-01T12:00:00Z"):
    return {
        "id": cid,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": head,
        "completed_at": completed_at,
        "app": {"id": app_id},
    }


class Step22TrustedCheckSelectionTests(unittest.TestCase):
    def test_multiple_successful_exact_head_reruns_select_latest(self):
        rows = [
            check(1, completed_at="2026-10-01T07:00:00Z"),
            check(2, completed_at="2026-10-01T11:00:00Z"),
            check(3, completed_at="2026-10-01T12:00:00Z"),
        ]
        selected = select_trusted_check(rows, name="validate", app_id=15368, head_sha=HEAD)
        self.assertEqual(selected["check_run_id"], 3)
        self.assertEqual(selected["head_sha"], HEAD)
        self.assertEqual(selected["conclusion"], "success")

    def test_wrong_app_name_or_head_cannot_satisfy_trust_anchor(self):
        rows = [
            check(1, app_id=999),
            check(2, name="other"),
            check(3, head="b" * 40),
        ]
        with self.assertRaisesRegex(RuntimeError, "trusted check missing"):
            select_trusted_check(rows, name="validate", app_id=15368, head_sha=HEAD)

    def test_later_non_success_blocks_older_success(self):
        rows = [
            check(1, completed_at="2026-10-01T11:00:00Z"),
            check(2, conclusion="failure", completed_at="2026-10-01T12:00:00Z"),
        ]
        with self.assertRaisesRegex(RuntimeError, "superseded by non-success"):
            select_trusted_check(rows, name="validate", app_id=15368, head_sha=HEAD)

    def test_later_success_overrides_earlier_failure(self):
        rows = [
            check(1, conclusion="failure", completed_at="2026-10-01T11:00:00Z"),
            check(2, completed_at="2026-10-01T12:00:00Z"),
        ]
        selected = select_trusted_check(rows, name="validate", app_id=15368, head_sha=HEAD)
        self.assertEqual(selected["check_run_id"], 2)


if __name__ == "__main__":
    unittest.main()
