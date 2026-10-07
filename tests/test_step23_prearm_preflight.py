import inspect
import unittest

from acceptance import step23_prearm_preflight as preflight


class Step23PrearmPreflightTests(unittest.TestCase):
    def test_correlation_ids_are_numeric_seeded_and_never_token_shaped(self):
        self.assertIsNotNone(preflight.CORRELATION.fullmatch("prearm-12345-initial-drain-1"))
        self.assertIsNotNone(preflight.CORRELATION.fullmatch("prearm-12345-2-runtime-hourly-sync"))
        self.assertIsNone(preflight.CORRELATION.fullmatch("prearm-initial-drain-1-ghs_secret"))
        self.assertIsNone(preflight.CORRELATION.fullmatch("prearm-12345-token.with.dots"))

    def test_drain_uses_auth_token_only_for_pending_state_reads(self):
        source=inspect.getsource(preflight.drain)
        self.assertIn("pending_event_count(github_token)",source)
        self.assertIn("correlation_seed",source)
        self.assertNotIn("{github_token}",source)
        self.assertNotIn("{token}",source)

    def test_clean_drain_returns_before_dispatching_reducer(self):
        source=inspect.getsource(preflight.drain)
        self.assertLess(
            source.index("if pending_event_count(github_token) == 0:"),
            source.index("for round_number in range"),
        )

    def test_preflight_uses_reducer_barriers_not_global_writer_silence(self):
        source=inspect.getsource(preflight.main)
        self.assertNotIn("wait_for_quiescence",source)
        self.assertIn("predrain",source)
        self.assertGreaterEqual(source.count("drain("),3)

    def test_hunter_and_command_center_barrier_inside_writer_jobs(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        for filename,target in (
            ("hunter-autonomous-cycle.yml","hunter-autonomous-cycle"),
            ("command-center-pages.yml","command-center-pages"),
        ):
            with self.subTest(filename=filename):
                text=(root/".github/workflows"/filename).read_text()
                barrier=text.index("Run pre-arm reducer barrier after writer-lane acquisition")
                restore=text.index("Restore canonical",barrier)
                self.assertLess(barrier,restore)
                self.assertIn("acceptance.step23_inline_reducer_barrier",text)
                self.assertIn(f"--target {target}",text)
                self.assertIn("inputs.prearm_id != ''",text)
                self.assertIn("actions: write",text)

    def test_writer_serialization_and_reducer_independence_are_explicit(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        for filename in (
            "portfolio-autonomous-scheduler.yml","hunter-autonomous-cycle.yml",
            "agent-heartbeat-sweep.yml","portfolio-notification-cycle.yml",
            "command-center-pages.yml",
        ):
            with self.subTest(filename=filename):
                text=(root/".github/workflows"/filename).read_text()
                self.assertIn("group: portfolio-state-writer-v1",text)
        runtime=(root/".github/workflows/runtime-worker.yml").read_text()
        self.assertIn("group: portfolio-state-writer-v1",runtime)
        watchdog=(root/".github/workflows/portfolio-cost-watchdog.yml").read_text()
        self.assertNotIn("state_journal.emitter",watchdog)
        reducer=(root/".github/workflows/portfolio-state-reducer.yml").read_text()
        self.assertIn("group: portfolio-state-reducer",reducer)
        self.assertNotIn("group: portfolio-state-writer-v1",reducer)

    def test_passive_delivery_events_cannot_cancel_active_preflight(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        text=(root/".github/workflows/step23-prearm-validation.yml").read_text()
        self.assertIn("github.event.workflow_run.event == 'push' && 'step23-prearm-validation'",text)
        self.assertIn("format('step23-prearm-passive-{0}', github.run_id)",text)
        self.assertIn(
            "cancel-in-progress: ${{ github.event_name == 'workflow_run' && github.event.workflow_run.event == 'push' }}",
            text,
        )


if __name__=="__main__":
    unittest.main()
