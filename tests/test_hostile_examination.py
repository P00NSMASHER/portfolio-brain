import copy,io,json,re,unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import hunting.autonomous_hunter as hunter
import uncertainty.highest_value_uncertainty as uncertainty
from cost_governor.cost_governor import CostGovernorError,load_state as load_cost_state,make_github_job_request,preflight
from action_engine.action_executor import ActionEngineError,make_email_request
from graph.universal_graph import UniversalGraphError,validate_graph,validate_node
from model_router.model_router import provider_registry,route_request
from notifications.github_sink import emit
from software_factory.github_executor import GitHubExecutor
from software_factory.software_factory import SoftwareFactoryError,hashv

ROOT=Path(__file__).resolve().parents[1]

class HostileExaminationTests(unittest.TestCase):
    def test_unverified_capability_edge_cannot_suppress_hunter_or_uncertainty_gap(self):
        graph=json.loads((ROOT/"graph/UNIVERSAL_GRAPH_LEDGER.json").read_text())
        nodes={n["canonical_key"]:n for n in graph["nodes"] if n["node_type"]=="PROJECT"}
        cap=next(n for n in graph["nodes"] if n["node_type"]=="CAPABILITY" and n["verification_state"]=="VERIFIED")
        graph=copy.deepcopy(graph)
        graph["edges"].append({
          "schema_version":"1.0.0","edge_id":"GE-HOSTILE-000001","source_node_id":nodes["PRJ-004"]["node_id"],
          "edge_type":"HAS_CAPABILITY","target_node_id":cap["node_id"],"attributes":{},
          "provenance_refs":["hostile:unverified-claim"],"verification_state":"INFERRED","status":"ACTIVE",
          "valid_from":"2026-09-25T22:00:00Z","valid_to":None,"supersedes_edge_id":None
        })
        hload=hunter.load; uload=uncertainty.load
        with patch.object(hunter,"load",side_effect=lambda p: graph if p=="graph/UNIVERSAL_GRAPH_LEDGER.json" else hload(p)):
            mapped=hunter._project_capability_map()
        with patch.object(uncertainty,"load",side_effect=lambda p: graph if p=="graph/UNIVERSAL_GRAPH_LEDGER.json" else uload(p)):
            _,_,cap_count,_,_=uncertainty._project_maps()
        self.assertNotIn("PRJ-004",mapped)
        self.assertEqual(cap_count["PRJ-004"],0)

    def test_verified_graph_edge_without_verification_anchor_is_rejected(self):
        graph=json.loads((ROOT/"graph/UNIVERSAL_GRAPH_LEDGER.json").read_text())
        bad=copy.deepcopy(graph)
        edge=next(e for e in bad["edges"] if e["verification_state"]=="VERIFIED")
        edge["provenance_refs"]=["trust-me"]
        with self.assertRaises(UniversalGraphError):
            validate_graph(bad["nodes"],bad["edges"])

    def test_verified_graph_node_without_verification_anchor_is_rejected(self):
        graph=json.loads((ROOT/"graph/UNIVERSAL_GRAPH_LEDGER.json").read_text())
        bad=copy.deepcopy(next(n for n in graph["nodes"] if n["verification_state"]=="VERIFIED"))
        bad["provenance_refs"]=["trust-me"]
        with self.assertRaises(UniversalGraphError):
            validate_node(bad)

    def test_notification_entity_cannot_inject_second_workflow_command(self):
        alert={"kind":"COST_HARD_STOP","severity":"CRITICAL","project_ids":["PRJ-000"],
               "entity_refs":["SAFE\n::error title=PWNED::INJECT"],"evidence_refs":["evidence:test"]}
        buf=io.StringIO()
        with redirect_stdout(buf):emit([alert])
        command_lines=[x for x in buf.getvalue().splitlines() if x.startswith("::")]
        self.assertEqual(len(command_lines),1)
        self.assertTrue(command_lines[0].startswith("::error title=Portfolio cost hard stop::"))

    def test_github_retry_group_reset_is_rejected(self):
        req=make_github_job_request(workflow_id="portfolio-autonomous-scheduler",job_id="schedule",run_id="123",
                                    attempt=1,project_ids=["PRJ-000"],estimated_minutes=1,authority_class="OBSERVE",
                                    at="2026-09-25T22:00:00Z")
        req["retry_group"]="github-job:forged:schedule"
        req["idempotency_key"]=req["retry_group"]+":attempt:1"
        with self.assertRaises(CostGovernorError):
            preflight(load_cost_state(),req,at="2026-09-25T22:00:00Z")

    def test_factory_deploy_operation_is_rejected_before_transport(self):
        body={"operation":"DEPLOY"}
        packet={**body,"action_hash":hashv(body)}
        with self.assertRaises(SoftwareFactoryError):
            GitHubExecutor("token",transport=lambda *args: self.fail("transport must not be reached")).validate_packet(packet)

    def test_disabled_model_provider_fails_closed(self):
        req={
          "schema_version":"1.0.0","request_id":"MRQ-HOSTILE-PROVIDER","project_ids":["PRJ-000"],
          "task_kind":"ARCHITECTURE","deterministic_sufficient":False,"consequence":"HIGH",
          "data_classification":"SANITIZED","authority_class":"OBSERVE","requires_independent_adversarial":False,
          "builder_independence_group":None,"max_cost_usd":10.0,"max_input_tokens":1000,"max_output_tokens":1000,
          "provider_allowlist":[],"evidence_refs":["hostile:provider-failure"]
        }
        reg=copy.deepcopy(provider_registry())
        for provider in reg["providers"]:
            if provider["provider_id"]=="openai":
                provider["enabled"]=False
        route=route_request(req,reg)
        self.assertEqual(route["status"],"BLOCKED_NO_ELIGIBLE_PROVIDER")


    def test_bounded_contact_rejects_child_project_and_high_risk_types_absent(self):
        with self.assertRaises(ActionEngineError):
            make_email_request(project_id="PRJ-005",target="adult@example.com",subject="x",body="y",campaign_id="hostile",evidence_refs=["hostile:action"],requested_at="2026-09-26T04:00:00Z")
        policy=json.loads((ROOT/"action_engine/ACTION_POLICY.json").read_text())
        self.assertEqual(set(policy["allowed_actions"]),{"CUSTOMER_EMAIL"})
        self.assertIn("MOVE_MONEY",policy["prohibited_action_types"])
        self.assertIn("LIVE_MARKET_TRADING",policy["prohibited_action_types"])


    def test_gmail_gateway_has_no_smtp_transport_surface(self):
        policy=json.loads((ROOT/"action_engine/ACTION_POLICY.json").read_text())
        self.assertEqual(policy["execution_provider"],"CHATGPT_GMAIL_CONNECTOR")
        self.assertEqual(policy["gmail_account"],"jayp19386@gmail.com")
        src=(ROOT/"action_engine/action_executor.py").read_text()
        self.assertNotIn("smtplib",src)
        self.assertNotIn("SMTP_",src)
        self.assertFalse((ROOT/".github/workflows/portfolio-action-worker.yml").exists())

    def test_market_research_act_remains_prohibited(self):
        profiles=json.loads((ROOT/"registry/autonomy_profiles.json").read_text())["profiles"]
        p=next(x for x in profiles if x["project_id"]=="PRJ-007")
        self.assertEqual(p["permissions"]["ACT"]["decision"],"PROHIBITED")
        project=next(x for x in json.loads((ROOT/"registry/projects.json").read_text())["projects"] if x["project_id"]=="PRJ-007")
        self.assertIn("NO_AUTONOMOUS_TRADING",project["hard_boundaries"])
        self.assertIn("NO_BROKER_ORDER_EXECUTION",project["hard_boundaries"])

    def test_child_facing_external_validation_remains_human_gated(self):
        candidates={c["uncertainty_id"]:c for c in uncertainty.generate_candidates()}
        for uid in ["UNC-EXTERNAL-PRJ-005","UNC-EXTERNAL-PRJ-006"]:
            self.assertEqual(candidates[uid]["actionability"],"HUMAN_APPROVAL_REQUIRED")
            self.assertIn("CONSEQUENTIAL_CHILD_FACING_CHANGE",candidates[uid]["approval_requirements"])

    def test_private_reference_graph_node_rejects_raw_secret_field(self):
        n={
          "schema_version":"1.0.0","node_id":"GN-CUSTOMER-HOSTILE1","node_type":"CUSTOMER",
          "canonical_key":"hostile-customer","label":"hostile-customer","project_ids":["PRJ-001"],
          "attributes":{"reference":"vault:1","redacted":True,"secret":"do-not-store"},
          "provenance_refs":["evidence:EVD-HOSTILE-0001"],"verification_state":"OBSERVED",
          "data_classification":"PRIVATE_REFERENCE_ONLY","status":"ACTIVE",
          "upstream_mapping":{"mode":"NATIVE","upstream_node_type":"CUSTOMER"}
        }
        with self.assertRaises(UniversalGraphError):validate_node(n)

    def test_hunter_contains_no_discovered_code_execution_surface(self):
        src=(ROOT/"hunting/autonomous_hunter.py").read_text().lower()
        self.assertNotIn("subprocess",src)
        self.assertIsNone(re.search(r"\bexec\s*\(",src))
        self.assertIsNone(re.search(r"\beval\s*\(",src))
        self.assertIn("does not execute discovered code",src)

if __name__=="__main__":unittest.main()
