"""Regression coverage for existing event routing, not new runtime capabilities."""
import fnmatch
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.validate_publication import PublicationValidationError, validate_publication

ROOT = Path(__file__).resolve().parents[1]
CORE = {
    "portfolio-autonomous-scheduler", "runtime-hourly-sync", "agent-heartbeat-sweep",
    "hunter-autonomous-cycle", "portfolio-notification-cycle",
}


def workflow(name):
    return (ROOT / '.github/workflows' / (name + '.yml')).read_text()


def block(text, key):
    match = re.search(r'(?m)^  ' + re.escape(key) + r':\n((?:[ ]{4,}[^\n]*\n)+)', text)
    if match is None:
        raise AssertionError('uninspectable trigger block: ' + key)
    return match.group(1)


def upstreams(text):
    return re.findall(r'^      - "([^"\n]+)"$', block(text, 'workflow_run'), re.M)


def path_list(text, name):
    m = re.search(r'(?m)^    ' + re.escape(name) + r':\n((?:[ ]{6,}[^\n]*\n)+)', block(text, 'push'))
    if m is None:
        raise AssertionError('missing path filter: ' + name)
    return re.findall(r'^      - "([^"\n]+)"$', m.group(1), re.M)


class AutomationTriggerEfficiencyTests(unittest.TestCase):
    def test_core_completion_has_one_reporting_route_not_two(self):
        pages = upstreams(workflow('command-center-pages'))
        watchdog = upstreams(workflow('portfolio-cost-watchdog'))
        self.assertEqual(pages, ['portfolio-cost-watchdog'])
        self.assertEqual(set(watchdog), CORE)
        self.assertEqual(len(watchdog), len(CORE))
        for producer in CORE:
            paths = int(producer in pages) + int(producer in watchdog and 'portfolio-cost-watchdog' in pages)
            self.assertEqual(paths, 1, producer)

    def test_watchdog_and_pages_do_not_trigger_each_other_in_a_loop(self):
        self.assertNotIn('command-center-pages', upstreams(workflow('portfolio-cost-watchdog')))
        self.assertNotIn('portfolio-cost-watchdog', upstreams(workflow('portfolio-cost-watchdog')))
        self.assertNotIn('command-center-pages', upstreams(workflow('command-center-pages')))

    def test_failed_completions_remain_visible_and_fallbacks_survive(self):
        for name, cron in [('command-center-pages', '37 * * * *'), ('portfolio-cost-watchdog', '53 * * * *')]:
            text = workflow(name)
            event = block(text, 'workflow_run')
            self.assertIn('types: [completed]', event)
            self.assertIn('branches: ["main"]', event)
            self.assertNotIn('workflow_run.conclusion', text)
            self.assertIn('cron: "' + cron + '"', text)
            self.assertIn('\n  workflow_dispatch:', text)

    def test_watchdog_finishes_active_receipt_and_only_pending_reads_coalesce(self):
        text = workflow('portfolio-cost-watchdog')
        self.assertRegex(text, r'(?m)^  group: portfolio-cost-watchdog$')
        self.assertRegex(text, r'(?m)^  cancel-in-progress: false$')
        self.assertNotIn('queue: max', text)  # default single pending, not a new backlog
        self.assertNotIn('portfolio-state-writer-v1', text)
        self.assertIn('cost_governor.cancel_managed_jobs', text)
        self.assertIn('Upload sanitized workflow liveness receipt', text)
        self.assertIn('always()', text)

    def test_full_sync_paths_cover_the_targeted_observe_exclusions(self):
        covered = path_list(workflow('runtime-hourly-sync'), 'paths')
        ignored = path_list(workflow('runtime-event-observe'), 'paths-ignore')
        self.assertEqual(set(covered), {'adapters/**', 'runtime/**', '.github/workflows/runtime-hourly-sync.yml', '.github/workflows/runtime-worker.yml'})
        self.assertTrue(set(covered).issubset(ignored))

    def test_runtime_only_push_uses_full_sync_without_duplicate_observe(self):
        covered = path_list(workflow('runtime-hourly-sync'), 'paths')
        ignored = path_list(workflow('runtime-event-observe'), 'paths-ignore')
        for path in ['runtime/state.py', 'adapters/github_adapter.py', '.github/workflows/runtime-worker.yml']:
            self.assertTrue(any(fnmatch.fnmatchcase(path, p) for p in covered))
            self.assertTrue(any(fnmatch.fnmatchcase(path, p) for p in ignored))
        self.assertIn('mode: sync', workflow('runtime-hourly-sync'))

    def test_uncovered_and_mixed_changes_still_receive_targeted_observation(self):
        ignored = path_list(workflow('runtime-event-observe'), 'paths-ignore')
        for paths in [['README.md'], ['registry/projects.json'], ['runtime/state.py', 'README.md']]:
            self.assertTrue(any(not any(fnmatch.fnmatchcase(path, p) for p in ignored) for path in paths))
        self.assertIn('repository_dispatch:', workflow('runtime-event-observe'))
        self.assertIn('workflow_dispatch:', workflow('runtime-event-observe'))
        self.assertIn('portfolio_observe', workflow('runtime-event-observe'))

    def test_publication_validator_rejects_reintroduced_duplicate_route(self):
        original = Path.read_text
        def changed(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if str(path).endswith('/command-center-pages.yml'):
                text = text.replace('      - "portfolio-cost-watchdog"', '      - "portfolio-cost-watchdog"\n      - "runtime-hourly-sync"')
            return text
        with patch.object(Path, 'read_text', changed):
            with self.assertRaisesRegex(PublicationValidationError, 'publish once'):
                validate_publication()

    def test_pages_state_writer_and_publication_proof_not_bypassed(self):
        text = workflow('command-center-pages')
        self.assertIn('group: portfolio-state-writer-v1', text)
        self.assertIn('      cancel-in-progress: false\n      queue: max', text)
        self.assertIn('workload_control.workload_gate preflight', text)
        self.assertIn('Verify deployed source commit', text)
        self.assertIn('Stamp publication provenance', text)
        self.assertIn('contents: read', text)
        self.assertNotIn('contents: write', text)


if __name__ == '__main__':
    unittest.main()
