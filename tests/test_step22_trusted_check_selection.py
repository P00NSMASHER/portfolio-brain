import unittest
from acceptance.step22_live_collect import select_trusted_check

HEAD="a"*40

def row(cid, *, name="validate", app_id=15368, head=HEAD, conclusion="success", at="2026-10-01T12:00:00Z"):
    return {"id":cid,"name":name,"status":"completed","conclusion":conclusion,"head_sha":head,"completed_at":at,"app":{"id":app_id}}

class Step22TrustedCheckSelectionTests(unittest.TestCase):
    def test_latest_success_is_selected_when_success_is_repeated(self):
        selected=select_trusted_check([
            row(1,at="2026-10-01T10:00:00Z"),
            row(2,at="2026-10-01T11:00:00Z"),
            row(3,at="2026-10-01T12:00:00Z"),
        ],name="validate",app_id=15368,head_sha=HEAD)
        self.assertEqual(selected["check_run_id"],3)

    def test_later_failure_blocks_older_success(self):
        with self.assertRaisesRegex(RuntimeError,"superseded by non-success"):
            select_trusted_check([
                row(1,at="2026-10-01T11:00:00Z"),
                row(2,conclusion="failure",at="2026-10-01T12:00:00Z"),
            ],name="validate",app_id=15368,head_sha=HEAD)

    def test_wrong_app_or_head_cannot_satisfy_anchor(self):
        with self.assertRaisesRegex(RuntimeError,"trusted check missing"):
            select_trusted_check([
                row(1,app_id=999),
                row(2,head="b"*40),
            ],name="validate",app_id=15368,head_sha=HEAD)

if __name__=="__main__":
    unittest.main()
