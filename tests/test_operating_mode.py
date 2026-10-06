import copy,json,unittest
from pathlib import Path
from operations.validate_operating_mode import OperatingModeValidationError,scheduled_workflow_inventory,validate_gmail_gateway_status,validate_operating_mode,validate_reasoning_fallback,workflow_schedule_crons,workflow_top_level_triggers
ROOT=Path(__file__).resolve().parents[1]

class OperatingModeTests(unittest.TestCase):
    def test_operational_contract_passes(self):
        result=validate_operating_mode()
        self.assertEqual(result["approved_recurring_workflows"],12)
        self.assertEqual(result["truthful_blocked_workflows"],7)
        self.assertGreaterEqual(result["workload_controlled_services"],9)
        self.assertEqual(result["durable_state_artifacts"],6)
        self.assertEqual(result["gmail_gateway_account_ref"],"PRIMARY_GMAIL_CONNECTOR")
        self.assertEqual(result["gmail_gateway_status"],"LIVE_GATEWAY_PROVEN")
        self.assertEqual(result["enabled_nonzero_models"],3)
        self.assertFalse(result["interactive_chatgpt_runtime_dependency"])
        self.assertEqual(result["release_status"],"OPERATIONAL")
        self.assertEqual(result["promoted_main_sha"],"cdd7adc71472f61a07f3641e9ff414091fc1bc35")
        self.assertEqual(result["reasoning_fallback_provider"],"CHATGPT_SCHEDULED_FALLBACK")
        self.assertFalse(result["reasoning_fallback_authority_granted"])
        self.assertFalse(result["reasoning_fallback_evidence_upgraded"])

    def test_reasoning_fallback_cannot_grant_itself_authority_or_evidence(self):
        data=json.loads((ROOT/"operations/CHATGPT_REASONING_FALLBACK.json").read_text())
        for field in ("authority_granted","evidence_upgraded"):
            poisoned=copy.deepcopy(data)
            poisoned[field]=True
            with self.subTest(field=field),self.assertRaises(OperatingModeValidationError):
                validate_reasoning_fallback(poisoned)

    def test_reasoning_fallback_rejects_private_connector_material(self):
        data=json.loads((ROOT/"operations/CHATGPT_REASONING_FALLBACK.json").read_text())
        for leaked in ("contact@example.com","18d3a4b5c6d7e8f9"):
            poisoned=copy.deepcopy(data)
            poisoned["top_bottleneck"]+=f" {leaked}"
            with self.subTest(leaked=leaked),self.assertRaises(OperatingModeValidationError):
                validate_reasoning_fallback(poisoned)
        poisoned=copy.deepcopy(data)
        poisoned["gmail_message_id"]="18d3a4b5c6d7e8f9"
        with self.assertRaises(OperatingModeValidationError):
            validate_reasoning_fallback(poisoned)

    def test_all_recurring_workflows_have_expected_trigger_class(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        self.assertEqual(set(p["approved_recurring_workflows"]),{
          "runtime-hourly-sync","runtime-daily-learning","runtime-weekly-synthesis",
          "hunter-autonomous-cycle","portfolio-autonomous-scheduler",
          "portfolio-cost-watchdog","portfolio-notification-cycle","command-center-pages",
          "agent-heartbeat-sweep","portfolio-state-reducer","portfolio-state-checkpoint-candidate",
          "verified-feedback-bootstrap"
        })

    def test_event_driven_inventory_includes_autonomous_repair_without_schedule(self):
        policy=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        self.assertEqual(set(policy["event_driven_workflows"]),{
          "runtime-event-observe","portfolio-autonomous-repair","portfolio-independent-verifier"
        })
        repair=ROOT/".github/workflows/portfolio-autonomous-repair.yml"
        triggers=workflow_top_level_triggers(repair)
        self.assertIn("workflow_run",triggers)
        self.assertIn("workflow_dispatch",triggers)
        self.assertNotIn("schedule",triggers)

    def test_autonomous_repair_remains_pr_only_and_independently_gated(self):
        policy=json.loads((ROOT/"repair/AUTONOMOUS_REPAIR_POLICY.json").read_text())
        self.assertTrue(policy["enabled"])
        self.assertFalse(policy["interactive_chatgpt_dependency"])
        self.assertFalse(policy["merge_authority"])
        self.assertFalse(policy["deployment_authority"])
        self.assertFalse(policy["default_branch_write_authority"])
        self.assertEqual(policy["foundation_check"],{"name":"validate","integration_id":15368})
        self.assertEqual(policy["independent_check"],{"name":"portfolio-phase1-gate","integration_id":5121826})

    def test_independent_verifier_is_workflow_run_only_and_credential_isolated(self):
        verifier=ROOT/".github/workflows/portfolio-independent-verifier.yml"
        triggers=workflow_top_level_triggers(verifier)
        self.assertEqual(triggers,{"workflow_run"})
        text=verifier.read_text().lower()
        self.assertIn("actions/create-github-app-token@v2",text)
        self.assertIn("secrets.portfolio_verifier_private_key",text)
        self.assertIn("docker run --rm --network none --cap-drop=all --security-opt=no-new-privileges",text)
        self.assertIn("path: verifier-control",text)
        self.assertIn("verification/independent_verifier.py",text)
        self.assertLess(
            text.index("run candidate regressions in network-disabled containers"),
            text.index("mint short-lived independent verifier app token"),
        )

    def test_active_schedule_inventory_matches_operating_policy(self):
        policy=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        window=json.loads((ROOT/"operations/STEP23_DELIVERY_WINDOW.json").read_text())
        actual=scheduled_workflow_inventory(ROOT/".github/workflows")
        expected={name:[entry["cron"],*window["temporary_crons"].get(name,[])]
                  for name,entry in policy["approved_recurring_workflows"].items()}
        expected["portfolio-schedule-delivery"]=["7,17,27,37,47,57 * * * *"]
        expected["step23-live-soak-observer"]=window["observer_crons"]
        self.assertEqual(actual,expected)
        control=json.loads((ROOT/"operations/STEP23_CONTROL.json").read_text())
        self.assertEqual(control["status"],"ARMED_FIXED")
        self.assertEqual(control["next_soak_start"],"2026-10-06T03:00:00Z")
        self.assertEqual(control["qualification_method"],"OWNER_FIXED_EXACT_MAIN_AFTER_DELIVERY_REPAIR")
        observer=ROOT/".github/workflows/step23-live-soak-observer.yml"
        self.assertEqual(workflow_top_level_triggers(observer),{"workflow_run","schedule","workflow_dispatch"})
        self.assertEqual(workflow_schedule_crons(observer),window["observer_crons"])
        observer_text=observer.read_text()
        self.assertIn("acceptance.step23_delivery_qualification",observer_text)
        self.assertIn("acceptance.step23_live_collect",observer_text)
        self.assertIn('"required_successes_per_workflow":3',observer_text)
        monitor=(ROOT/".github/workflows/portfolio-schedule-delivery.yml").read_text()
        self.assertIn("actions: read",monitor)
        self.assertIn("workflow_run:",monitor)
        self.assertIn("github.event_name == 'push'",monitor)
        self.assertIn("--repair",monitor)
        self.assertIn("--without-cost-state",monitor)
        reducer=(ROOT/".github/workflows/portfolio-state-reducer.yml").read_text()
        self.assertIn("cancel-in-progress: false",reducer)

    def test_learning_crons_avoid_known_hourly_writer_collisions(self):
        policy=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())["approved_recurring_workflows"]
        minute=lambda name:policy[name]["cron"].split()[0]
        self.assertNotEqual(minute("runtime-daily-learning"),minute("command-center-pages"))
        self.assertNotEqual(minute("runtime-weekly-synthesis"),minute("runtime-hourly-sync"))

    def test_singleton_cost_state_lane_does_not_fan_out_specialized_push_runs(self):
        for name in ("portfolio-autonomous-scheduler","agent-heartbeat-sweep"):
            triggers=workflow_top_level_triggers(ROOT/".github/workflows"/f"{name}.yml")
            self.assertNotIn("push",triggers,name)
            self.assertIn("schedule",triggers,name)
            self.assertIn("workflow_dispatch",triggers,name)

    def test_trigger_parser_ignores_commented_push(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path=Path(directory)/"scheduled.yml"
            path.write_text('name: scheduled\non:\n  schedule:\n    - cron: "17 * * * *"\n  # push:\n  workflow_dispatch:\njobs: {}\n')
            self.assertEqual(workflow_top_level_triggers(path),{"schedule","workflow_dispatch"})

    def test_schedule_parser_ignores_comments_and_unrelated_cron_text(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path=Path(directory)/"comment-only.yml"
            path.write_text('name: comment-only\n# schedule:\n#   - cron: "* * * * *"\non:\n  push:\n    branches: ["main"]\njobs: {}\n')
            self.assertIsNone(workflow_schedule_crons(path))

    def test_alternate_yaml_extension_cannot_bypass_schedule_inventory(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path=Path(directory)/"rogue.yaml"
            path.write_text('name: rogue\non:\n  schedule:\n    - cron: "* * * * *"\njobs: {}\n')
            self.assertEqual(scheduled_workflow_inventory(directory),{"rogue":["* * * * *"]})

    def test_duplicate_workflow_stems_across_extensions_fail_closed(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            for suffix in ("yml","yaml"):
                (Path(directory)/f"duplicate.{suffix}").write_text('name: duplicate\non:\n  push:\njobs: {}\n')
            with self.assertRaises(OperatingModeValidationError):
                scheduled_workflow_inventory(directory)

    def test_quoted_schedule_keys_are_still_governed(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path=Path(directory)/"quoted.yaml"
            path.write_text('name: quoted\n"on":\n  \'schedule\':\n    - "cron": "17 * * * *"\njobs: {}\n')
            self.assertEqual(workflow_schedule_crons(path),["17 * * * *"])

    def test_inline_or_aliased_trigger_maps_fail_closed(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            inline=Path(directory)/"inline.yml"
            inline.write_text('name: inline\non: {schedule: [{cron: "* * * * *"}]}\njobs: {}\n')
            with self.assertRaises(OperatingModeValidationError):
                workflow_schedule_crons(inline)
            aliased=Path(directory)/"aliased.yml"
            aliased.write_text('name: aliased\non:\n  <<: *triggers\njobs: {}\n')
            with self.assertRaises(OperatingModeValidationError):
                workflow_schedule_crons(aliased)

    def test_blocked_workflows_report_failure_truthfully(self):
        workload_names=[
            "hunter-autonomous-cycle","portfolio-autonomous-scheduler",
            "portfolio-notification-cycle","command-center-pages","agent-heartbeat-sweep",
        ]
        for name in workload_names:
            body=(ROOT/".github/workflows"/f"{name}.yml").read_text().lower()
            self.assertIn("steps.workload.outputs.allowed != 'true'",body,name)
            self.assertIn("exit 1",body,name)
            self.assertNotIn("cost_governor.workflow_gate",body,name)

        runtime=(ROOT/".github/workflows/runtime-worker.yml").read_text().lower()
        self.assertIn("workload_control.workload_gate preflight",runtime)
        self.assertIn("cost_governor.workflow_gate preflight",runtime)
        self.assertIn("steps.admission.outputs.allowed != 'true'",runtime)
        self.assertIn("exit 1",runtime)

        proof=(ROOT/".github/workflows/model-value-proof.yml").read_text().lower()
        self.assertIn("steps.cost.outputs.allowed != 'true'",proof)
        self.assertIn("exit 1",proof)

        factory=(ROOT/".github/workflows/software-factory-candidate.yml").read_text().lower()
        self.assertIn("workload_control.workload_gate preflight",factory)
        self.assertIn("run: exit 3",factory)

    def test_high_risk_boundaries_and_machine_gated_merge_remain(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        boundaries=set(p["permanent_authority_boundaries"])
        self.assertNotIn("CUSTOMER_COMMUNICATION_REQUIRES_HUMAN_APPROVAL",boundaries)
        self.assertIn("PAYMENT_CASH_MOVEMENT_REQUIRES_HUMAN_APPROVAL",boundaries)
        self.assertIn("LIVE_MARKET_TRADING_AND_BROKERAGE_EXECUTION_PROHIBITED",boundaries)
        self.assertIn("DEPLOYMENT_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER",boundaries)
        self.assertIn("MERGE_REQUIRES_PROTECTED_PR_AND_INDEPENDENT_VERIFIER",boundaries)
        self.assertNotIn("DEPLOYMENT_AND_MERGE_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER",boundaries)

    def test_gmail_gateway_is_connector_bound_and_no_smtp_worker_exists(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        gmail=p["external_connector_gateways"]["gmail"]
        self.assertEqual(gmail["provider"],"CHATGPT_GMAIL_CONNECTOR")
        self.assertEqual(gmail["account_ref"],"PRIMARY_GMAIL_CONNECTOR")
        self.assertEqual(gmail["execution_task_id"],"6ab377c25df08191a6e2aa1537d9d2ef")
        self.assertFalse((ROOT/".github/workflows/portfolio-action-worker.yml").exists())

    def test_live_gmail_gateway_proof_tracks_sanitized_ledger(self):
        status=json.loads((ROOT/"operations/OPERATING_MODE_STATUS.json").read_text())["connector_gateways"]["gmail"]
        ledger=json.loads((ROOT/"action_engine/GMAIL_GATEWAY_LEDGER.json").read_text())
        self.assertEqual(status["status"],"LIVE_GATEWAY_PROVEN")
        self.assertEqual(status["proof_sequence"],ledger["sequence"])
        self.assertEqual(status["proof_at"],ledger["updated_at"])
        self.assertFalse(status["raw_connector_identifiers_persisted"])

    def test_stale_gmail_gateway_proof_fails_closed(self):
        policy=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())["external_connector_gateways"]["gmail"]
        status=json.loads((ROOT/"operations/OPERATING_MODE_STATUS.json").read_text())["connector_gateways"]["gmail"]
        ledger=json.loads((ROOT/"action_engine/GMAIL_GATEWAY_LEDGER.json").read_text())
        status=copy.deepcopy(status);status["proof_sequence"]-=1
        with self.assertRaisesRegex(OperatingModeValidationError,"proof sequence stale"):
            validate_gmail_gateway_status(policy,status,ledger)

    def test_trigger_only_command_center_refresh_does_not_spawn_runtime_work(self):
        workflow=(ROOT/".github/workflows/runtime-event-observe.yml").read_text()
        self.assertIn('"operations/COMMAND_CENTER_REFRESH_REQUEST.json"',workflow)

    def test_chatgpt_tasks_are_advisory_not_runtime_dependency(self):
        p=json.loads((ROOT/"operations/OPERATING_MODE_POLICY.json").read_text())
        s=json.loads((ROOT/"operations/OPERATING_MODE_STATUS.json").read_text())
        self.assertFalse(p["interactive_chatgpt_runtime_dependency"])
        self.assertTrue(s["operational_without_interactive_chatgpt"])
        self.assertEqual(s["external_chatgpt_tasks_role"],"BOUNDED_GMAIL_GATEWAY_PLUS_ADVISORY_MONITORING")

    def test_post_promotion_evidence_is_recorded(self):
        s=json.loads((ROOT/"operations/OPERATING_MODE_STATUS.json").read_text())
        self.assertEqual(s["final_ci_run_id"],36202440293)
        self.assertEqual(s["post_promotion_runtime_run_id"],36202440452)
        names={x["name"] for x in s["post_promotion_runtime_artifacts"]}
        self.assertIn("portfolio-runtime-state",names)
        self.assertIn("portfolio-cost-governor-state",names)

if __name__=="__main__":unittest.main()
