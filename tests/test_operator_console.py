import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import operator_console.operator_console as console
from scheduler.autonomous_scheduler import build_context,load_state,schedule_cycle

ROOT=Path(__file__).resolve().parents[1]


class OperatorConsoleTests(unittest.TestCase):
    def test_workflow_is_owner_gated_and_not_part_of_public_pages(self):
        workflow=(ROOT/".github/workflows/operator-console.yml").read_text()
        self.assertIn("github.actor == github.repository_owner",workflow)
        self.assertIn("environment: portfolio-operator",workflow)
        self.assertIn("actions: write",workflow)
        self.assertIn("pull-requests: write",workflow)
        self.assertIn("operator_console.operator_console",workflow)
        pages=(ROOT/".github/workflows/command-center-pages.yml").read_text()
        self.assertNotIn("operator-console",pages)
        self.assertNotIn("operator_console",pages)

    def test_exact_queue_item_can_be_cancelled_durably(self):
        state,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-26T12:00:00Z")
        work=receipt["selected_work"][0]
        with tempfile.TemporaryDirectory() as td:
            state_path=Path(td)/"scheduler.json";out=Path(td)/"out.json"
            state_path.write_text(json.dumps(state))
            result=console.cancel_queue_item(state_path=str(state_path),output_path=str(out),work_id=work["scheduler_work_id"])
            written=json.loads(out.read_text())
        self.assertEqual(result["new_state"],"CANCELLED")
        cancelled=next(x for x in written["work_items"] if x["scheduler_work_id"]==work["scheduler_work_id"])
        self.assertEqual(cancelled["state"],"CANCELLED")

    def test_kill_switch_change_is_local_proposal_edit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"runtime").mkdir()
            (root/"runtime/KILL_SWITCH.json").write_text(json.dumps({
                "schema_version":"1.0.0","disabled":False,"reason":None,"changed_at":None,"changed_by":None
            }))
            with patch.object(console,"ROOT",root):
                result=console.prepare_kill_switch(subsystem="runtime",disabled=True,actor="P00NSMASHER",reason="maintenance",at="2026-09-26T12:00:00Z")
            body=json.loads((root/"runtime/KILL_SWITCH.json").read_text())
        self.assertTrue(body["disabled"])
        self.assertEqual(body["changed_by"],"P00NSMASHER")
        self.assertTrue(body["reason"].startswith("operator-reason:sha256:"))
        self.assertNotIn("maintenance",json.dumps(body))
        self.assertEqual(result["path"],"runtime/KILL_SWITCH.json")

    def test_approval_persists_hash_not_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"operator_console").mkdir()
            (root/"operator_console/OWNER_APPROVALS.json").write_text(json.dumps({
                "schema_version":"1.0.0","ledger_id":"portfolio-owner-approvals","approvals":[]
            }))
            (root/"operator_console/OPERATOR_POLICY.json").write_text(json.dumps({
                "allowed_approval_actors":["P00NSMASHER"]
            }))
            with patch.object(console,"ROOT",root):
                row=console.prepare_approval(
                    source_ref="EXP-TEST",project_id="PRJ-005",approval_code="CONSEQUENTIAL_CHILD_FACING_CHANGE",
                    actor="P00NSMASHER",reason="approved after review",at="2026-09-26T12:00:00Z"
                )
            ledger=json.loads((root/"operator_console/OWNER_APPROVALS.json").read_text())
        self.assertEqual(row["status"],"ACTIVE")
        self.assertTrue(row["reason_hash"].startswith("sha256:"))
        self.assertNotIn("approved after review",json.dumps(ledger))

    def test_budget_proposal_must_still_pass_cost_policy(self):
        original=json.loads((ROOT/"cost_governor/COST_GOVERNOR_POLICY.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"cost_governor").mkdir()
            (root/"cost_governor/COST_GOVERNOR_POLICY.json").write_text(json.dumps(original))
            with patch.object(console,"ROOT",root):
                result=console.prepare_budget(cost_usd=12,model_calls=44,api_calls=88,reason="bounded operator proposal")
            changed=json.loads((root/"cost_governor/COST_GOVERNOR_POLICY.json").read_text())
        self.assertEqual(changed["portfolio_ceiling"]["cost_usd"],12)
        self.assertEqual(changed["portfolio_ceiling"]["model_calls"],44)
        self.assertEqual(changed["portfolio_ceiling"]["api_calls"],88)
        self.assertTrue(result["reason_hash"].startswith("sha256:"))


if __name__=="__main__":
    unittest.main()
