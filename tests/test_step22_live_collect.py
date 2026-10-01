import unittest

from acceptance.step22_live_collect import select_trusted_check

HEAD = "a" * 40

def check(cid, *, name="validate", app_id=15368, head=HEAD, conclusion="success", completed_at="2026-10-01T12:00:00Z"):
    return {
        "id": cid, "name": name, "status": "completed", "conclusion": conclusion,
        "head_sha": head, "completed_at": completed_at, "app": {"id": app_id},
    }

class Step22TrustedCheckSelectionTests(unittest.TestCase):
    def test_multiple_successful_exact_head_reruns_select_latest(self):
        rows=[
            check(1,completed_at="2026-10-01T10:00:00Z"),
            check(2,completed_at="2026-10-01T11:00:00Z"),
            check(3,completed_at="2026-10-01T12:00:00Z"),
        ]
        selected=select_trusted_check(rows,name="validate",app_id=15368,head_sha=HEAD)
        self.assertEqual(selected["check_run_id"],3)

    def test_wrong_trust_anchor_cannot_satisfy_selection(self):
        rows=[check(1,app_id=999),check(2,head="b"*40)]
        with self.assertRaisesRegex(RuntimeError,"trusted check missing"):
            select_trusted_check(rows,name="validate",app_id=15368,head_sha=HEAD)

    def test_later_non_success_blocks_older_success(self):
        rows=[
            check(1,completed_at="2026-10-01T11:00:00Z"),
            check(2,conclusion="failure",completed_at="2026-10-01T12:00:00Z"),
        ]
        with self.assertRaisesRegex(RuntimeError,"superseded by non-success"):
            select_trusted_check(rows,name="validate",app_id=15368,head_sha=HEAD)

if __name__ == "__main__":
    unittest.main()
