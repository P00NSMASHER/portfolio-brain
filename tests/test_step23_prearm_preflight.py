import inspect
import unittest
from unittest.mock import patch

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

    def test_all_step23_state_writers_wait_for_barrier_inside_writer_jobs(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        for filename,target in (
            ("portfolio-autonomous-scheduler.yml","portfolio-autonomous-scheduler"),
            ("hunter-autonomous-cycle.yml","hunter-autonomous-cycle"),
            ("agent-heartbeat-sweep.yml","agent-heartbeat-sweep"),
            ("portfolio-notification-cycle.yml","portfolio-notification-cycle"),
            ("command-center-pages.yml","command-center-pages"),
        ):
            with self.subTest(filename=filename):
                text=(root/".github/workflows"/filename).read_text()
                barrier=text.index("Wait for pre-arm reducer barrier after writer-lane acquisition")
                restore=text.index("Restore canonical",barrier)
                self.assertLess(barrier,restore)
                self.assertIn("acceptance.step23_wait_reducer_barrier",text)
                self.assertIn(f"--target {target}",text)
                self.assertIn("inputs.prearm_id != ''",text)
                self.assertRegex(text,r"(?m)^  actions: (?:read|write)$")

    def test_runtime_sync_forwards_and_waits_for_prearm_barrier(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        hourly=(root/".github/workflows/runtime-hourly-sync.yml").read_text()
        worker=(root/".github/workflows/runtime-worker.yml").read_text()
        self.assertIn("prearm_id: ${{ inputs.prearm_id }}",hourly)
        self.assertIn("Wait for pre-arm reducer barrier after writer-lane acquisition",worker)
        self.assertIn("--target runtime-hourly-sync",worker)
        self.assertIn("inputs.prearm_id != ''",worker)

    def test_transient_dispatch_500_is_confirmed_before_any_retry(self):
        exact="a"*40
        correlation="prearm-12345-2-runtime-hourly-sync"
        row={
            "id":77,"event":"workflow_dispatch","head_branch":"main",
            "head_sha":exact,"display_title":correlation,
            "status":"completed","conclusion":"success",
            "created_at":"2026-10-07T00:00:00Z","updated_at":"2026-10-07T00:01:00Z",
        }

        class FakeAPI:
            def __init__(self):
                self.posts=0
            def post(self,path,payload):
                self.posts+=1
                return 500
            def get(self,path):
                if path=="/branches/main":
                    return {"commit":{"sha":exact}}
                if "/runs?" in path:
                    return {"workflow_runs":[row]}
                raise AssertionError(path)

        api=FakeAPI()
        with patch.object(preflight,"wait_for_correlated_run",return_value=row), \
             patch.object(preflight.time,"sleep"):
            result=preflight.dispatch(
                api,workflow="runtime-hourly-sync",filename="runtime-hourly-sync.yml",
                exact_sha=exact,correlation=correlation,
            )
        self.assertEqual(api.posts,1)
        self.assertEqual(result["dispatch_attempts"],1)
        self.assertEqual(result["dispatch_transient_statuses"],[500])

    def test_transient_dispatch_retries_only_after_no_correlated_run_materializes(self):
        exact="a"*40
        correlation="prearm-12345-3-portfolio-autonomous-scheduler"
        row={
            "id":88,"event":"workflow_dispatch","head_branch":"main",
            "head_sha":exact,"display_title":correlation,
            "status":"completed","conclusion":"success",
            "created_at":"2026-10-07T00:00:00Z","updated_at":"2026-10-07T00:01:00Z",
        }

        class FakeAPI:
            def __init__(self):
                self.posts=0
            def post(self,path,payload):
                self.posts+=1
                return 500 if self.posts==1 else 204
            def get(self,path):
                if path=="/branches/main":
                    return {"commit":{"sha":exact}}
                if "/runs?" in path:
                    return {"workflow_runs":[]}
                raise AssertionError(path)

        api=FakeAPI()
        with patch.object(preflight,"wait_for_correlated_run",return_value=row), \
             patch.object(preflight.time,"sleep"):
            result=preflight.dispatch(
                api,workflow="portfolio-autonomous-scheduler",
                filename="portfolio-autonomous-scheduler.yml",
                exact_sha=exact,correlation=correlation,
            )
        self.assertEqual(api.posts,2)
        self.assertEqual(result["dispatch_attempts"],2)
        self.assertEqual(result["dispatch_transient_statuses"],[500])

    def test_persistent_transient_dispatch_failure_is_bounded_and_blocking(self):
        exact="a"*40
        correlation="prearm-12345-4-hunter-autonomous-cycle"

        class FakeAPI:
            def __init__(self):
                self.posts=0
            def post(self,path,payload):
                self.posts+=1
                return 503
            def get(self,path):
                if path=="/branches/main":
                    return {"commit":{"sha":exact}}
                if "/runs?" in path:
                    return {"workflow_runs":[]}
                raise AssertionError(path)

        api=FakeAPI()
        with patch.object(preflight.time,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"transient failure persisted"):
                preflight.dispatch(
                    api,workflow="hunter-autonomous-cycle",
                    filename="hunter-autonomous-cycle.yml",
                    exact_sha=exact,correlation=correlation,
                )
        self.assertEqual(api.posts,3)

    def test_queue_wait_does_not_consume_execution_timeout(self):
        source=inspect.getsource(preflight.wait_for_correlated_run)
        self.assertIn("queue_timeout",source)
        self.assertIn("execution_timeout",source)
        self.assertIn("execution_deadline = None",source)
        self.assertIn("execution_deadline = now + execution_timeout",source)

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
