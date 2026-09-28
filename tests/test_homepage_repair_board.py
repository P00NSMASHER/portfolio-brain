"""The public repair board must surface deficits without granting authority."""
import unittest

from dashboard.command_center import build_command_center_snapshot, build_repair_issues, render_html
from dashboard.publication_gate import should_publish


class RepairBoardTests(unittest.TestCase):
    def test_stale_roles_become_issues_even_without_stalled_work(self):
        snapshot = build_command_center_snapshot()
        snapshot["agents"][0]["heartbeat_health"] = "STALE"
        snapshot["telemetry"]["queue"]["stalled_open_count"] = 0
        snapshot["system"]["stalled_agent_count"] = 0
        issues = build_repair_issues(snapshot)
        role = next(issue for issue in issues if issue["title"] == "Agent evidence is stale")
        self.assertIn(snapshot["agents"][0]["name"], role["detail"])
        self.assertIn("HEALTH_CHECK", role["prompt"])

    def test_public_page_has_visible_issue_board_and_local_freshness_check(self):
        page = render_html(build_command_center_snapshot())
        self.assertLess(page.index('id="repair-board"'), page.index('class="grid kpis"'))
        self.assertIn('id="publication-stale"', page)
        self.assertIn('Date.now() - captured', page)
        self.assertIn("Fix now", page)
        self.assertIn("https://chatgpt.com/?prompt=", page)
        self.assertIn("Show operations & diagnostics", page)
        self.assertNotIn("fetch(", page.lower())

    def test_static_page_republishes_if_unchanged_evidence_is_old(self):
        previous = {"state_sources": {"generated_at": "2026-09-27T10:00:00Z"}, "value": 2}
        current = {"state_sources": {"generated_at": "2026-09-27T10:59:59Z"}, "value": 2}
        self.assertFalse(should_publish(current, previous))
        current["state_sources"]["generated_at"] = "2026-09-27T11:00:00Z"
        self.assertTrue(should_publish(current, previous))


if __name__ == "__main__":
    unittest.main()
