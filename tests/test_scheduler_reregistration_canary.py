"""Static guarantees for the read-only native schedule canary."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class SchedulerReregistrationCanaryTests(unittest.TestCase):
    def test_all_eight_canaries_are_read_only_and_suppress_operational_jobs(self):
        window=json.loads((ROOT/"operations/STEP23_DELIVERY_WINDOW.json").read_text())
        self.assertEqual(window["status"],"CANARY_REQUIRED")
        self.assertEqual(len(window["temporary_crons"]),8)
        for name,crons in window["temporary_crons"].items():
            self.assertEqual(len(crons),1)
            cron=crons[0]
            text=(ROOT/".github/workflows"/f"{name}.yml").read_text()
            self.assertIn("Prove native schedule delivery only",text)
            self.assertIn(f"github.event.schedule == '{cron}'",text)
            self.assertIn(f"github.event.schedule != '{cron}'",text)

    def test_registration_recovery_forces_disable_then_enable(self):
        source=(ROOT/"operations/schedule_delivery.py").read_text()
        workflow=(ROOT/".github/workflows/portfolio-schedule-delivery.yml").read_text()
        self.assertIn("/disable",source)
        self.assertIn("WORKFLOW_DISABLE_NOT_CONFIRMED",source)
        self.assertIn("WORKFLOW_REENABLE_NOT_CONFIRMED",source)
        self.assertIn("--force-reregister-active",workflow)
        self.assertIn("CANARY_REQUIRED: liveness dispatch intentionally suppressed",workflow)

if __name__=="__main__":
    unittest.main()
