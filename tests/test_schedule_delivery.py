"""Deterministic delivery tests; fixture successes confer no acceptance credit."""
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from operations import schedule_delivery as d

SHA = 'a' * 40
NOW = datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
WF = dict(id=31, name=d.CORE[0], path=f'.github/workflows/{d.CORE[0]}.yml', state='active')
RUN = dict(id=501, workflow_id=31, name=WF['name'], path=WF['path'], head_branch='main',
           head_sha=SHA, event='schedule', status='completed', conclusion='success',
           created_at='2026-10-05T22:58:00Z')
OLD = dict(id=d.RETIRED_RUN, head_sha=d.RETIRED_SHA, head_branch=d.RETIRED_BRANCH,
           path=d.RETIRED_PATH, status='completed', conclusion='failure')
ENV = dict(GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/main', GITHUB_REPOSITORY=d.REPO, GITHUB_SHA=SHA)
HEAD = {'commit': {'sha': SHA}}

class API:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
    def call(self, path, method='GET'):
        self.calls.append((path, method))
        if not self.responses:
            raise AssertionError('Unexpected request')
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

class DeliveryTests(unittest.TestCase):
    def summary(self, rows, wf=WF):
        return d.summarize(d.CORE[0], wf, rows, SHA, NOW)

    def test_native_success_is_not_acceptance(self):
        result = self.summary([RUN])
        self.assertTrue(result['native_success_on_revision'])
        self.assertEqual(result['soak_credit'], 0)

    def test_wrong_source_stale_skip_failure_and_dispatch_never_count(self):
        for change in ({'event': 'workflow_dispatch'}, {'event': 'push'}, {'head_sha': 'b'*40},
                       {'head_branch': 'feature'}, {'workflow_id': 32}, {'path': 'wrong'},
                       {'status': 'queued', 'conclusion': None}, {'conclusion': 'skipped'},
                       {'conclusion': 'failure'}, {'conclusion': 'cancelled'},
                       {'created_at': '2026-10-05T20:00:00Z'}):
            with self.subTest(change=change):
                self.assertFalse(self.summary([{**RUN, **change}])['native_success_on_revision'])

    def test_missing_event_is_distinct_from_waiting_execution(self):
        self.assertEqual(self.summary([])['stage'], 'NO_NATIVE_RUN_ON_CURRENT_REVISION')
        queued = {**RUN, 'status': 'queued', 'conclusion': None}
        self.assertEqual(self.summary([queued])['stage'], 'NATIVE_EVENT_CREATED_EXECUTION_PENDING')

    def test_missing_or_disabled_registration_is_explicit(self):
        self.assertEqual(self.summary([], None)['stage'], 'WORKFLOW_NOT_REGISTERED')
        self.assertEqual(self.summary([RUN], {**WF, 'state': 'disabled_manually'})['stage'], 'WORKFLOW_NOT_ACTIVE')

    def test_future_timestamp_and_latest_failure_are_not_healthy(self):
        with self.assertRaises(RuntimeError):
            self.summary([{**RUN, 'created_at': '2026-10-06T00:00:00Z'}])
        newer = {**RUN, 'id': 502, 'created_at': '2026-10-05T22:59:00Z', 'conclusion': 'failure'}
        self.assertFalse(self.summary([RUN, newer])['native_success_on_revision'])

    def test_active_registration_is_never_toggled(self):
        api = API(HEAD, OLD)
        d.repair(api, {d.CORE[0]: WF}, SHA, ENV)
        self.assertTrue(all(method == 'GET' for _, method in api.calls))

    def test_force_reregister_cycles_all_active_targets_and_reconfirms(self):
        workflows = {
            name: dict(id=100+i, name=name, path=f'.github/workflows/{name}.yml', state='active')
            for i,name in enumerate(d.CORE)
        }
        responses=[HEAD]
        for name in d.CORE:
            wf=workflows[name]
            responses += [{}, {**wf, 'state':'disabled_manually'}]
        responses += [HEAD]
        for name in d.CORE:
            wf=workflows[name]
            responses += [{}, wf]
        responses += [HEAD, {'workflows': list(workflows.values())}]
        api=API(*responses)
        actions=d.force_reregister(
            api, workflows, SHA, ENV,
            {'status':'CANARY_REQUIRED','reason':'FORCE_SCHEDULER_REGISTRATION_RESET'},
            sleep=lambda _:None,
        )
        self.assertEqual(len(actions),16)
        self.assertEqual(sum(method=='PUT' and path.endswith('/disable') for path,method in api.calls),8)
        self.assertEqual(sum(method=='PUT' and path.endswith('/enable') for path,method in api.calls),8)

    def test_force_reregister_is_owner_armed_and_protected_main_only(self):
        workflows={name:dict(id=100+i,name=name,path=f'.github/workflows/{name}.yml',state='active')
                   for i,name in enumerate(d.CORE)}
        with self.assertRaisesRegex(RuntimeError,'OWNER_ARMED'):
            d.force_reregister(API(),workflows,SHA,ENV,{'status':'CANARY_REQUIRED','reason':'wrong'},sleep=lambda _:None)
        with self.assertRaisesRegex(RuntimeError,'PROTECTED_MAIN_PUSH'):
            d.force_reregister(API(),workflows,SHA,{**ENV,'GITHUB_EVENT_NAME':'workflow_dispatch'},
                               {'status':'CANARY_REQUIRED','reason':'FORCE_SCHEDULER_REGISTRATION_RESET'},sleep=lambda _:None)

    def test_enable_acknowledgement_is_not_delivery(self):
        api = API(HEAD, OLD, HEAD, {}, WF)
        result = d.repair(api, {d.CORE[0]: {**WF, 'state': 'disabled_inactivity'}}, SHA, ENV)
        self.assertIn(('/actions/workflows/31/enable', 'PUT'), api.calls)
        self.assertEqual(result[1]['action'], 'REGISTRATION_REENABLED_DELIVERY_UNPROVEN')

    def test_enable_failure_or_missing_confirmation_fails_closed(self):
        for last in (PermissionError(), {**WF, 'state': 'disabled_manually'}):
            api = API(HEAD, OLD, HEAD, {}, last)
            with self.assertRaises((PermissionError, RuntimeError)):
                d.repair(api, {d.CORE[0]: {**WF, 'state': 'disabled_manually'}}, SHA, ENV)

    def test_only_the_exact_retired_auditor_can_be_cancelled(self):
        api = API(HEAD, {**OLD, 'status': 'in_progress'}, {}, OLD)
        d.repair(api, {}, SHA, ENV)
        self.assertEqual([path for path, method in api.calls if method == 'POST'],
                         [f'/actions/runs/{d.RETIRED_RUN}/cancel'])
        api = API(HEAD, {**OLD, 'status': 'in_progress', 'head_sha': 'b'*40})
        with self.assertRaises(RuntimeError):
            d.repair(api, {}, SHA, ENV)
        self.assertTrue(all(method == 'GET' for _, method in api.calls))

    def test_mutations_reject_other_events_changed_main_and_wrong_paths(self):
        for event in ('schedule', 'pull_request', 'workflow_dispatch'):
            with self.assertRaises(RuntimeError):
                d.repair(API(), {}, SHA, {**ENV, 'GITHUB_EVENT_NAME': event})
        with self.assertRaises(RuntimeError):
            d.repair(API({'commit': {'sha': 'b'*40}}), {}, SHA, ENV)
        with self.assertRaises(RuntimeError):
            d.repair(API(HEAD, OLD), {d.CORE[0]: {**WF, 'path': 'wrong'}}, SHA, ENV)

    def test_catalogue_fails_closed_on_missing_data_duplicates_or_wrong_names(self):
        for doc in ({}, {'workflows': [WF, WF]}, {'workflows': [{**WF, 'name': 'wrong'}]}):
            with self.assertRaises(RuntimeError):
                d.registry(API(doc))
        self.assertEqual(d.registry(API({'workflows': []})), {})
        self.assertEqual(d.registry(API({'workflows': [WF]}))[d.CORE[0]]['id'], 31)

    def test_fixed_arm_control_and_workflow_boundaries(self):
        control = json.loads((ROOT/'operations/STEP23_CONTROL.json').read_text())
        window = json.loads((ROOT/'operations/STEP23_DELIVERY_WINDOW.json').read_text())
        self.assertEqual(control['status'], 'PREARM_READY')
        self.assertIsNone(control['next_soak_start'])
        self.assertFalse(control['acceptance_complete'])
        self.assertEqual(window['max_soak_duration_seconds'], 7200)
        self.assertTrue(all(window['temporary_crons'][name] == [] for name in d.CORE))
        for name in d.CORE:
            text = (ROOT/f'.github/workflows/{name}.yml').read_text()
            self.assertNotIn('scheduler_canary:', text)
        for name in ('portfolio-state-reducer', 'portfolio-cost-watchdog', 'command-center-pages', 'portfolio-autonomous-repair'):
            self.assertNotIn('!startsWith(github.event.workflow_run.created_at', (ROOT/f'.github/workflows/{name}.yml').read_text())
        delivery_text = (ROOT/'.github/workflows/portfolio-schedule-delivery.yml').read_text()
        before_clock, clock_and_after = delivery_text.split('  clock:', 1)
        clock, recovery = clock_and_after.split('  recover:', 1)
        self.assertNotIn('actions: write', before_clock)
        self.assertIn('workflow_run:', before_clock)
        self.assertIn('7,17,27,37,47,57 * * * *', before_clock)
        self.assertIn('group: portfolio-schedule-delivery-${{ github.event_name }}', delivery_text)
        self.assertIn('actions: write', clock)
        self.assertIn('operations.schedule_clock', clock)
        self.assertIn("github.event.workflow_run.event == 'schedule'", clock)
        self.assertIn("github.event_name == 'push'", recovery)
        self.assertIn('--without-cost-state', recovery)
        self.assertNotIn('--force-reregister', recovery)
        observer = (ROOT/'.github/workflows/step23-live-soak-observer.yml').read_text()
        self.assertNotIn('  schedule:', observer)
        self.assertIn('workflow_run:', observer)
        self.assertIn('step23_delivery_qualification', observer)
        self.assertIn('step23_live_collect', observer)

if __name__ == '__main__':
    unittest.main()
