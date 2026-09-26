import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from registry.validate_contracts import ContractValidationError, validate_autonomy_profile, validate_objective, validate_metric

def load_schema(name):
    return json.loads((ROOT/"schemas"/name).read_text())

AUT={
 "schema_version":"1.0.0","autonomy_profile_id":"AUT-000","project_id":"PRJ-000",
 "default_policy":"DENY","runtime_enabled":False,
 "permissions":{
   "OBSERVE":{"decision":"ALLOWED","conditions":["read-only sanitized state"]},
   "EXPERIMENT":{"decision":"BOUNDED","conditions":["isolated non-consequential tests only"]},
   "MODIFY":{"decision":"ISOLATED_BRANCH_ONLY","conditions":["no direct main writes"]},
   "ACT":{"decision":"HUMAN_APPROVAL_REQUIRED","conditions":["explicit human approval required"]}
 },
 "human_approval_required_for":["PRODUCTION_DEPLOYMENT_MEANINGFUL_RISK","CUSTOMER_COMMUNICATION","MOVE_MONEY"],
 "hard_prohibitions":[],
 "separation_of_duties":{"builder_may_self_approve":False,"independent_verifier_required_for_promotion":True}
}
OBJ={
 "schema_version":"1.0.0","objective_id":"OBJ-000","project_id":"PRJ-000",
 "title":"Build Portfolio Brain","statement":"Build a durable portfolio control plane.",
 "status":"ACTIVE","priority":"CRITICAL",
 "success_conditions":["Durable verified state advances without interactive prompting."],
 "constraints":["Consequential ACT remains human-gated."],
 "evidence_requirements":["Exact commits and passing deterministic tests."],
 "provenance":{"source_type":"OWNER_DECLARATION","source_ref":"primary mission"}
}
MET={
 "schema_version":"1.0.0","metric_id":"MET-000","project_id":"PRJ-000",
 "name":"Verified cycle completions","description":"Count of completed portfolio cycles backed by verification receipts.",
 "kind":"OUTCOME","unit":"cycles","direction":"HIGHER_IS_BETTER",
 "source":{"source_type":"EVIDENCE_RECEIPT","source_ref":"portfolio events"},
 "verification_requirement":"VERIFIED","aggregation":"COUNT","status":"PROPOSED"
}

class Step2ContractTests(unittest.TestCase):
    def test_schemas_are_closed(self):
        for name in ["AUTONOMY_SCHEMA.json","OBJECTIVE_SCHEMA.json","METRIC_SCHEMA.json"]:
            self.assertFalse(load_schema(name)["additionalProperties"])

    def test_valid_autonomy(self): validate_autonomy_profile(copy.deepcopy(AUT))
    def test_valid_objective(self): validate_objective(copy.deepcopy(OBJ))
    def test_valid_metric(self): validate_metric(copy.deepcopy(MET))

    def test_autonomy_default_must_deny(self):
        bad=copy.deepcopy(AUT); bad["default_policy"]="ALLOW"
        with self.assertRaises(ContractValidationError): validate_autonomy_profile(bad)

    def test_runtime_enabled_is_boolean_and_can_be_true_operationally(self):
        enabled=copy.deepcopy(AUT); enabled["runtime_enabled"]=True
        validate_autonomy_profile(enabled)
        bad=copy.deepcopy(AUT); bad["runtime_enabled"]="yes"
        with self.assertRaises(ContractValidationError): validate_autonomy_profile(bad)

    def test_act_cannot_be_autonomously_allowed(self):
        bad=copy.deepcopy(AUT); bad["permissions"]["ACT"]["decision"]="ALLOWED"
        with self.assertRaises(ContractValidationError): validate_autonomy_profile(bad)

    def test_builder_cannot_self_approve(self):
        bad=copy.deepcopy(AUT); bad["separation_of_duties"]["builder_may_self_approve"]=True
        with self.assertRaises(ContractValidationError): validate_autonomy_profile(bad)

    def test_objective_requires_evidence(self):
        bad=copy.deepcopy(OBJ); bad["evidence_requirements"]=[]
        with self.assertRaises(ContractValidationError): validate_objective(bad)

    def test_objective_rejects_authority_smuggling(self):
        bad=copy.deepcopy(OBJ); bad["may_deploy"]=True
        with self.assertRaises(ContractValidationError): validate_objective(bad)

    def test_metric_requires_source(self):
        bad=copy.deepcopy(MET); bad["source"]["source_ref"]=""
        with self.assertRaises(ContractValidationError): validate_metric(bad)

    def test_metric_verification_is_explicit(self):
        bad=copy.deepcopy(MET); bad["verification_requirement"]="TRUST_MODEL"
        with self.assertRaises(ContractValidationError): validate_metric(bad)

if __name__=="__main__":
    unittest.main()
