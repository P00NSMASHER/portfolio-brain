"""Owner-facing results must reconcile the original core and its later observations."""
import json
from pathlib import Path
import tempfile
import unittest

from brain.v11 import origin_currentness, owner_inbox, results_dashboard as dashboard
from tests.test_brain_v11_currentness_window import Provider, REPO, RUN, SOURCE, original
from tests.test_brain_v11_owner_inbox import report
from tests.test_brain_v11_results import AT, MAIN, Fake


class OwnerResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "currentness.json"
        self.account = {"source_sha": MAIN, "run_id": 104, "state_tip_status": "LATEST_COMMIT_CONFIRMED"}
        self.runs = [{"run_id": 104, "outcome": "ORIGINAL_SUCCESS"}]
        self.cycle = report()
        job = self.cycle["owner_jobs"][0]
        job["source_sha"] = SOURCE
        proof = job["failure_evidence"]
        proof.update(run_id=RUN, source_sha=SOURCE,
                     url=f"https://github.com/{REPO}/actions/runs/{RUN}/job/{proof['job_id']}")
        (self.root / "v9-engineering.json").write_text(json.dumps(self.cycle))
        self.inbox = owner_inbox.build(self.cycle, expected_source=MAIN)
        self.set_verdict([original(RUN + 1, conclusion="success")])
        self.pr = {"id": "inquiry", "repository": "P00NSMASHER/github-value-hunt-ledger",
                   "source": "https://github.com/P00NSMASHER/github-value-hunt-ledger/pull/1093",
                   "problem": "<inquiry>", "owner": "PR owner", "state": "OPEN_WITH_EXISTING_OWNER",
                   "owner_decision": "AWAITING_CHAT_DECISION", "request": "Review the passing check.",
                   "current_check": "https://github.com/P00NSMASHER/github-value-hunt-ledger/actions/runs/1/job/2",
                   "acceptance": "Measure target behavior."}
        self.incident = dict(self.pr, id="failure", repository=REPO, source=proof["url"],
                             state="ORIGINAL_FAILURE_NEEDS_TRIAGE", request="Reproduce the failure.")
        self.packet = {"version": 1, "provider_writes": 0, "remaining": 1,
                       "decisions": [self.pr, self.incident]}
        self.save_packet()

    def save_packet(self):
        (self.root / "decisions.json").write_text(json.dumps(self.packet))

    def set_verdict(self, history):
        self.verdict = origin_currentness.evaluate(self.inbox, Provider(history))
        self.path.write_text(json.dumps(self.verdict))

    def review(self):
        return dashboard.owner_review(self.root, self.path, self.account, self.runs)

    def test_html_and_json_include_current_decision_and_hold_later_green(self):
        result = self.review()
        self.assertEqual(result["decisions"], [self.pr])
        self.assertEqual(result["remaining"], 1)
        self.assertFalse(result["writer_authorized"])
        self.assertEqual(result["currentness"], self.verdict["items"])
        data = dashboard.report(Fake(), expected_main=MAIN, generated_at=AT)
        html = dashboard.html_report(dict(data, owner_review=result))
        for expected in ("&lt;inquiry&gt;", self.pr["request"], self.pr["current_check"],
                         self.verdict["items"][0]["status"]):
            self.assertIn(expected, html)
        self.assertNotIn(self.incident["request"], html)
        self.set_verdict([original()])
        self.assertEqual(self.review()["decisions"], self.packet["decisions"])

    def test_exact_source_bound_or_unavailable(self):
        self.account["run_id"] += 1
        self.assertEqual(self.review()["decisions"], [])
        self.account["run_id"] -= 1
        self.account["state_tip_status"] = "HISTORICAL_DELIVERY_NOT_CURRENT"
        self.assertIsNone(self.review()["remaining"])
        self.account["state_tip_status"] = "LATEST_COMMIT_CONFIRMED"
        self.verdict["original_inbox_sha256"] = "0" * 64
        del self.verdict["verdict_sha256"]
        self.verdict["verdict_sha256"] = owner_inbox.digest(self.verdict)
        self.path.write_text(json.dumps(self.verdict))
        with self.assertRaisesRegex(dashboard.ReportError, "CURRENTNESS_UNBOUND"):
            self.review()
        self.packet["decisions"] *= 2
        self.save_packet()
        with self.assertRaisesRegex(dashboard.ReportError, "DECISION_PACKET_INVALID"):
            self.review()
        (self.root / "decisions.json").unlink()
        self.assertEqual(self.review()["status"], "OWNER_EVIDENCE_UNAVAILABLE")

    def test_protected_main_push_can_report_without_schedule_credit(self):
        api = Fake()
        api.runs = [dict(api.runs[0], event="push")]
        api.core_steps = [{"name": "Bind execution to unchanged current main", "conclusion": "success"}]
        result = dashboard.report(api, expected_main=MAIN, generated_at=AT)
        self.runs = result["core_run_verifications"]
        self.assertEqual(result["metrics"]["main_cycle_successes_in_sample"], 0)
        self.assertEqual(self.review()["decisions"], [self.pr])
        api.core_steps = []
        self.runs = dashboard.report(api, expected_main=MAIN, generated_at=AT)["core_run_verifications"]
        self.assertEqual(self.review()["decisions"], [])
