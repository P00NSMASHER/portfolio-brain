import unittest
from pathlib import Path

class DeploymentTriggerTests(unittest.TestCase):
    def test_every_main_source_change_gets_deployment_evidence(self):
        text=(Path(__file__).resolve().parents[1]/".github/workflows/brain-cycle.yml").read_text()
        push=text.split("  push:\n",1)[1].split("\npermissions:",1)[0]
        self.assertIn('branches: ["main"]',push)
        self.assertNotIn("paths:",push)
        self.assertNotIn("paths-ignore:",push)
