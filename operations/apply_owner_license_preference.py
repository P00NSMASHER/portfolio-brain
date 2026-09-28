"""One-time, exact-base migration; removed from candidate before verification."""
from pathlib import Path
import json

ROOT = Path.cwd()
def replace(path, old, new):
    p=ROOT/path
    text=p.read_text(encoding='utf-8')
    if text.count(old)!=1:
        raise RuntimeError(f'{path}: expected one patch anchor, got {text.count(old)}')
    p.write_text(text.replace(old,new),encoding='utf-8')
def write(path, text):
    p=ROOT/path
    if p.exists(): raise RuntimeError(f'refusing to overwrite new file: {path}')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(text,encoding='utf-8')
def update_json(path, change):
    p=ROOT/path
    doc=json.loads(p.read_text(encoding='utf-8'))
    change(doc)
    p.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')

write('hunting/LICENSE_ADMISSION_POLICY.json',json.dumps({
    'schema_version':'1.0.0',
    'mode':'ADVISORY_OWNER_ASSUMED',
    'scope':'P00NSMASHER/portfolio-brain',
    'request_date':'2026-09-28',
    'decision_basis':'EXPLICIT_OWNER_REQUEST',
    'license_based_blocking':False,
    'rights_verification_claimed':False,
    'source_records_must_remain_unchanged':True,
    'security_access_budget_and_action_gates_unchanged':True,
    'note':'The owner requested that Brain not block work on licensing. This is a workflow assumption, not independent verification or a new legal grant.'
},indent=2)+'\n')
write('hunting/license_admission.py','''"""License workflow admission, deliberately separate from source-rights evidence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from hunting.rights_gate import validate_rights_record

POLICY_PATH = Path(__file__).with_name("LICENSE_ADMISSION_POLICY.json")

class LicenseAdmissionError(ValueError):
    pass

def load_policy() -> dict[str, Any]:
    p = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if p.get("schema_version") != "1.0.0" or p.get("scope") != "P00NSMASHER/portfolio-brain":
        raise LicenseAdmissionError("invalid license-admission policy scope/schema")
    if p.get("mode") not in {"ADVISORY_OWNER_ASSUMED", "ENFORCE"}:
        raise LicenseAdmissionError("unknown license-admission mode")
    if p.get("decision_basis") != "EXPLICIT_OWNER_REQUEST":
        raise LicenseAdmissionError("owner decision basis missing")
    if p.get("rights_verification_claimed") is not False:
        raise LicenseAdmissionError("workflow policy cannot verify source rights")
    if p.get("source_records_must_remain_unchanged") is not True:
        raise LicenseAdmissionError("source evidence preservation required")
    if p.get("security_access_budget_and_action_gates_unchanged") is not True:
        raise LicenseAdmissionError("license preference cannot change other controls")
    if p.get("license_based_blocking") is not (p["mode"] == "ENFORCE"):
        raise LicenseAdmissionError("license mode/blocking setting inconsistent")
    return p

def license_review_required() -> bool:
    return load_policy()["mode"] == "ENFORCE"

def admission(record: dict[str, Any], accepted_classes: Iterable[str] = ("PERMISSIVE_DEPENDENCY",)) -> dict[str, Any]:
    """Validate integrity, then admit under owner preference without changing facts."""
    validate_rights_record(record)
    p = load_policy()
    assumed = p["mode"] == "ADVISORY_OWNER_ASSUMED"
    allowed = assumed or record["rights_classification"] in set(accepted_classes)
    canonical = json.dumps(p,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return {
        "allowed": allowed,
        "status": "OPERATOR_ASSUMED" if assumed else ("POLICY_ALLOWED" if allowed else "POLICY_BLOCKED"),
        "license_based_blocking": not assumed,
        "rights_verification_claimed": False,
        "source_rights_hash": record["rights_hash"],
        "observed_rights_classification": record["rights_classification"],
        "policy_ref": "hunting/LICENSE_ADMISSION_POLICY.json",
        "policy_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
    }
''')
replace('challenger/champion_challenger.py',
    'from hunting.rights_gate import validate_rights_record',
    'from hunting.rights_gate import validate_rights_record\nfrom hunting.license_admission import admission as license_admission')
replace('challenger/champion_challenger.py',
    '    rights_ok=rights_record["rights_classification"] in set(p["integration_rights_classes"])',
    '    license_decision=license_admission(rights_record,p["integration_rights_classes"])\n    rights_ok=license_decision["allowed"]')
replace('challenger/champion_challenger.py',
    '      "stage":"RIGHTS_EVIDENCE_VERIFIED",',
    '      "stage":"RIGHTS_POLICY_ADMISSION",\n      "license_admission":license_decision,')
def challenger_policy(p):
    p['required_sequence']=[('RIGHTS_POLICY_ADMISSION' if s=='RIGHTS_EVIDENCE_VERIFIED' else s) for s in p['required_sequence']]
    p['license_admission_policy']='hunting/LICENSE_ADMISSION_POLICY.json'
    p['rights_classes_apply_only_in_enforce_mode']=True
update_json('challenger/CHALLENGER_POLICY.json',challenger_policy)
replace('challenger/CHAMPION_CHALLENGER_CONTRACT.md',
    '- Discovery never grants reuse rights.',
    '- Discovery never grants reuse rights. License workflow admission follows `hunting/LICENSE_ADMISSION_POLICY.json`: the owner has disabled license-based blocking, with the basis recorded as `OPERATOR_ASSUMED`, never independently VERIFIED. Source rights facts remain unchanged.')
replace('hunting/autonomous_hunter.py',
    'from hunting.rights_gate import build_rights_record, validate_rights_record',
    'from hunting.rights_gate import build_rights_record, validate_rights_record\nfrom hunting.license_admission import license_review_required, admission as license_admission')
replace('hunting/autonomous_hunter.py',
    '    rights_classification=finding.get("rights",{}).get("rights_classification","NO_LICENSE_NO_REUSE")',
    '    rights_classification=finding.get("rights",{}).get("rights_classification","NO_LICENSE_NO_REUSE")\n    review_required=license_review_required()\n    license_requirement=["License/rights verification"] if review_required else ["License admission: OPERATOR_ASSUMED under owner preference; not independently verified."]')
replace('hunting/autonomous_hunter.py',
    '"success_condition":"Independent exact-revision inspection confirms the implementation behavior, meaningful tests/negative controls, lawful reuse terms, and a bounded integration path.",',
    '"success_condition":("Independent exact-revision inspection confirms implementation behavior, meaningful tests/negative controls, lawful reuse terms, and a bounded integration path." if review_required else "Independent exact-revision inspection confirms implementation behavior, meaningful tests/negative controls, and a bounded integration path; license admission is OPERATOR_ASSUMED, not verified."),')
replace('hunting/autonomous_hunter.py',
    '"failure_condition":"The candidate is README-only, lacks meaningful tests, does not satisfy the capability need, has incompatible rights, or creates unsafe authority expansion.",',
    '"failure_condition":("The candidate is README-only, lacks meaningful tests, does not satisfy the capability need, has incompatible rights, or creates unsafe authority expansion." if review_required else "The candidate is README-only, lacks meaningful tests, does not satisfy the capability need, or creates unsafe authority expansion."),')
replace('hunting/autonomous_hunter.py',
    '"evidence_requirements":["Exact source revision","Implementation-level evidence","Meaningful tests or negative controls","License/rights verification",',
    '"evidence_requirements":["Exact source revision","Implementation-level evidence","Meaningful tests or negative controls",*license_requirement,')
replace('hunting/autonomous_hunter.py',
    'rights_evidence=provider.rights_evidence(cand,inspection) if callable(getattr(provider,"rights_evidence",None)) else {}',
    'rights_evidence=provider.rights_evidence(cand,inspection) if license_review_required() and callable(getattr(provider,"rights_evidence",None)) else {}')
replace('hunting/autonomous_hunter.py',
    '                    "rights_classification":rights["rights_classification"],',
    '                    "license_admission":license_admission(rights),\n                    "rights_classification":rights["rights_classification"],')
replace('experiments/experiment_engine.py',
    'from typing import Any',
    'from typing import Any\nfrom hunting.license_admission import license_review_required')
replace('experiments/experiment_engine.py',
    '"Independent inspection verifies implementation-level behavior, meaningful tests/negative controls, exact revision, and a lawful bounded reuse path relevant to the gap.",',
    '("Independent inspection verifies implementation-level behavior, meaningful tests/negative controls, exact revision, and a lawful bounded reuse path relevant to the gap." if license_review_required() else "Independent inspection verifies implementation-level behavior, meaningful tests/negative controls, exact revision, and a bounded integration path. License admission is OPERATOR_ASSUMED, not verified."),')
replace('experiments/experiment_engine.py',
    '"Insufficient public evidence, unresolved rights, correlated/self-authored proof, or ambiguous mapping remains INCONCLUSIVE."',
    '("Insufficient public evidence, unresolved rights, correlated/self-authored proof, or ambiguous mapping remains INCONCLUSIVE." if license_review_required() else "Insufficient public evidence, correlated/self-authored proof, or ambiguous mapping remains INCONCLUSIVE. License status alone is non-blocking under owner preference.")')
replace('transfer/cross_project_transfer.py',
    'from pathlib import Path',
    'from pathlib import Path\nfrom hunting.license_admission import license_review_required')
replace('transfer/cross_project_transfer.py',
    '"hard_blockers":blockers,"rights_review_required":True,',
    '"hard_blockers":blockers,"rights_review_required":license_review_required(),')
replace('transfer/cross_project_transfer.py',
    '"failure_condition":"The target-context experiment produces independently VERIFIED no-value or regression evidence, or the capability cannot satisfy the target need without violating rights/data/authority boundaries.",',
    '"failure_condition":("The target-context experiment produces independently VERIFIED no-value or regression evidence, or the capability cannot satisfy the target need without violating rights/data/authority boundaries." if license_review_required() else "The target-context experiment produces independently VERIFIED no-value or regression evidence, or cannot satisfy the target need within data/access/authority boundaries."),')
replace('transfer/cross_project_transfer.py',
    '"inconclusive_condition":"Target evidence, rights, implementation identity, measurement window, or verifier evidence is insufficient for a definitive value conclusion.",',
    '"inconclusive_condition":("Target evidence, rights, implementation identity, measurement window, or verifier evidence is insufficient for a definitive value conclusion." if license_review_required() else "Target evidence, implementation identity, measurement window, or verifier evidence is insufficient for a definitive value conclusion."),')
replace('transfer/cross_project_transfer.py',
    '"Rights/license verification before code or asset reuse.",',
    '("Rights/license verification before code or asset reuse." if license_review_required() else "License admission: OPERATOR_ASSUMED under owner preference, not verified; other controls remain required."),')
replace('transfer/cross_project_transfer.py',
    'req(p["rights_review_required"] is True,"rights review gate missing");',
    'req(type(p["rights_review_required"]) is bool and (p["rights_review_required"] or not license_review_required()),"rights review setting inconsistent with admission policy");')
def transfer_policy(p):
    p['license_admission_policy']='hunting/LICENSE_ADMISSION_POLICY.json'
    p['implementation_gates']=[('LICENSE_WORKFLOW_ADMISSION_PER_OWNER_POLICY' if s=='RIGHTS_AND_LICENSE_VERIFICATION_REQUIRED_BEFORE_CODE_OR_ASSET_REUSE' else s) for s in p['implementation_gates']]
    p['invariants']=[('License workflow admission follows explicit owner preference without claiming independently verified source rights; applicable Step 16 target onboarding remains required.' if s=='Actual code or asset reuse requires rights/license verification and applicable Step 16 target-repository onboarding.' else s) for s in p['invariants']]
update_json('transfer/TRANSFER_POLICY.json',transfer_policy)
replace('transfer/validate_transfer.py',
    'from transfer.cross_project_transfer import build_transfer_state,policy',
    'from transfer.cross_project_transfer import build_transfer_state,policy\nfrom hunting.license_admission import license_review_required')
replace('transfer/validate_transfer.py',
    'all(x["rights_review_required"] and not x["implementation_allowed"] for x in state["proposals"])',
    'all(x["rights_review_required"] is license_review_required() and not x["implementation_allowed"] for x in state["proposals"])')
replace('tests/test_champion_challenger.py',
    'import hashlib\nimport unittest',
    'import hashlib\nimport unittest\nfrom unittest.mock import patch\nfrom hunting.license_admission import load_policy as load_license_policy')
replace('tests/test_champion_challenger.py',
    '    def test_no_license_blocks_before_adapter_or_promotion(self):\n        d,adapter,replay_receipt,canary=self.happy_inputs()',
    '    def test_no_license_blocks_in_explicit_enforcement_mode(self):\n        strict=load_license_policy()\n        strict["mode"]="ENFORCE"\n        strict["license_based_blocking"]=True\n        override=patch("hunting.license_admission.load_policy",return_value=strict)\n        override.start()\n        self.addCleanup(override.stop)\n        d,adapter,replay_receipt,canary=self.happy_inputs()')
write('hunting/validate_license_admission.py','''"""Deterministic synthetic controls; no source-rights verification is asserted."""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
from hunting.license_admission import admission, load_policy
from hunting.rights_gate import build_rights_record, RightsGateError

LICENSES = ("MIT", "Apache-2.0", "GPL-3.0-only", "AGPL-3.0-only", "BUSL-1.1", "PolyForm-Noncommercial-1.0.0", "LicenseRef-Proprietary", "NOASSERTION", None)

def validate() -> dict:
    policy = load_policy()
    if policy["mode"] != "ADVISORY_OWNER_ASSUMED":
        raise AssertionError("owner-requested advisory mode not active")
    controls = []
    for spdx in LICENSES:
        record = build_rights_record(
            {"full_name": "synthetic/license-control", "license": {"spdx_id": spdx}},
            {"revision": "a"*40, "paths": [], "tree_sha": "b"*40, "truncated": False},
        )
        before = copy.deepcopy(record)
        decision = admission(record)
        assert decision["allowed"] is True
        assert decision["status"] == "OPERATOR_ASSUMED"
        assert decision["rights_verification_claimed"] is False
        assert before == record
        assert record["automatic_reuse_authority_granted"] is False
        assert record["license_text_hash"] is None
        controls.append({"license_spdx": spdx, "admitted": True, "rights_record_preserved": True})
    tampered = copy.deepcopy(record)
    tampered["source_revision_sha"] = "c"*40
    try:
        admission(tampered)
    except RightsGateError:
        pass
    else:
        raise AssertionError("tampered rights evidence admitted")
    return {"schema_version":"1.0.0", "status":"PASS", "evidence_class":"SYNTHETIC_CONTROLS_ONLY", "source_commit":os.environ.get("GITHUB_SHA"), "policy_mode":policy["mode"], "rights_verification_claimed":False, "tampered_receipt_rejected":True, "controls":controls}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=validate()
    text=json.dumps(result,indent=2,sort_keys=True)+"\\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding="utf-8")
    print(text,end="")

if __name__=="__main__":
    main()
''')
write('tests/test_license_admission_policy.py','''import copy
import unittest
from unittest.mock import patch
from hunting.license_admission import admission, load_policy, license_review_required, LicenseAdmissionError, POLICY_PATH
from hunting.rights_gate import build_rights_record
from hunting.validate_license_admission import validate
from hunting.autonomous_hunter import experiment_proposal, run_cycle, load_seed_state
from transfer.cross_project_transfer import detect_transfer_hypotheses, validate_proposal
import test_champion_challenger as fixtures
from challenger.champion_challenger import assess_candidate, validate_assessment, ChallengerError

class OwnerLicensePolicyTests(unittest.TestCase):
    def test_all_license_classes_are_advisory_without_false_verification(self):
        self.assertEqual(len(validate()["controls"]),9)
        self.assertFalse(license_review_required())

    def test_challenger_no_license_reaches_review_but_not_promotion(self):
        d,adapter,replay,canary=fixtures.ChampionChallengerTests().happy_inputs()
        rights=fixtures.no_license_rights(d)
        before=copy.deepcopy(rights)
        assessment=assess_candidate(discovery=d,rights_record=rights,adapter_receipt=adapter,replay_receipt=replay,forward_canary_receipt=canary)
        validate_assessment(assessment)
        stage=assessment["stages"][1]
        self.assertEqual(stage["stage"],"RIGHTS_POLICY_ADMISSION")
        self.assertEqual(stage["license_admission"]["status"],"OPERATOR_ASSUMED")
        self.assertTrue(assessment["eligible_for_human_promotion_review"])
        self.assertFalse(assessment["automatic_promotion_allowed"])
        self.assertFalse(assessment["authority_granted"])
        self.assertFalse(assessment["active_policy_changed"])
        self.assertEqual(before,rights)
        self.assertFalse(rights["commercial_use_allowed"])

    def test_advisory_still_rejects_adapter_revision_mismatch(self):
        d,adapter,replay,canary=fixtures.ChampionChallengerTests().happy_inputs()
        adapter["source_revision_sha"]="f"*40
        with self.assertRaises(ChallengerError):
            assess_candidate(discovery=d,rights_record=fixtures.no_license_rights(d),adapter_receipt=adapter,replay_receipt=replay,forward_canary_receipt=canary)

    def test_transfer_license_review_is_disabled_but_implementation_is_not_authorized(self):
        proposals=detect_transfer_hypotheses()
        self.assertEqual(len(proposals),44)
        for p in proposals:
            validate_proposal(p)
            self.assertFalse(p["rights_review_required"])
            self.assertFalse(p["implementation_allowed"])
        self.assertEqual(sum(p["state"]=="BLOCKED" for p in proposals),4)

    def test_hunter_does_not_require_license_verification(self):
        proposal=experiment_proposal({"finding_id":"test","candidate_fingerprint":"sha256:"+"a"*64,"gap_id":"test","project_ids":["PRJ-001"]})
        self.assertNotIn("License/rights verification",proposal["evidence_requirements"])
        self.assertNotIn("incompatible rights",proposal["failure_condition"])
        self.assertIn("OPERATOR_ASSUMED",str(proposal))

    def test_hunter_skips_license_fetches_only(self):
        class Provider:
            requests=0
            def search(self,query):
                self.requests+=1
                return [{"id":1,"full_name":"synthetic/recovery","private":False,"license":None}]
            def inspect(self,candidate):
                return {"revision":"a"*40,"tree_sha":"b"*40,"paths":["src/recovery.py","tests/test_recovery.py"],"truncated":False}
            def rights_evidence(self,*args):
                raise AssertionError("advisory mode must not fetch license text")
        _,receipt=run_cycle(load_seed_state(),Provider(),at="2026-09-28T15:30:00Z")
        self.assertTrue(receipt["findings"])
        for finding in receipt["findings"]:
            self.assertEqual(finding["decision_trace"]["license_admission"]["status"],"OPERATOR_ASSUMED")
            self.assertFalse(finding["rights"]["automatic_reuse_authority_granted"])

    def test_unknown_or_forged_policy_mode_rejected(self):
        import json
        bad=load_policy()
        bad["mode"]="VERIFIED"
        with patch.object(type(POLICY_PATH),"read_text",return_value=json.dumps(bad)):
            with self.assertRaises(LicenseAdmissionError):
                load_policy()

if __name__=="__main__":
    unittest.main()
''')
p=ROOT/'README.md'
p.write_text(p.read_text(encoding='utf-8')+'''
## Owner-requested license workflow preference

`hunting/LICENSE_ADMISSION_POLICY.json` is the admission authority for **Brain-only license workflow decisions**. In `ADVISORY_OWNER_ASSUMED` mode, missing, copyleft, restricted, or custom license classifications do not block Hunter proposals, transfer planning, or shadow-challenger admission. Dedicated Hunter license-text fetches are skipped. The basis is recorded as `OPERATOR_ASSUMED`, not independently VERIFIED.

Source classifications, copyright notices, hashes, license text, and historical rights states are not rewritten. A legacy `UNKNOWN_REQUIRES_REVIEW` source state describes evidence, not the current license-admission setting. This preference does not verify third-party permission, change downstream repositories, allow unauthorized access, or bypass budget, security, source-integrity, independent-verification, factory, action, deployment, or promotion controls.

`ENFORCE` remains available by explicitly changing both `mode` and `license_based_blocking`; unknown or inconsistent settings fail validation. Deterministic synthetic controls run with `python -m hunting.validate_license_admission`.
''',encoding='utf-8')
replace('.github/workflows/foundation-ci.yml',
    '      - name: Validate Step 9 autonomous Hunter\n        run: python -m hunting.validate_hunter\n',
    '      - name: Validate Step 9 autonomous Hunter\n        run: python -m hunting.validate_hunter\n      - name: Validate owner license admission\n        run: python -m hunting.validate_license_admission --output hunting/out/license_admission_receipt.json\n')
p=ROOT/'.github/workflows/foundation-ci.yml'
p.write_text(p.read_text(encoding='utf-8')+'''      - name: Upload license admission controls
        uses: actions/upload-artifact@v4
        with:
          name: license-admission-${{ github.sha }}
          path: hunting/out/license_admission_receipt.json
          if-no-files-found: error
          retention-days: 30
''',encoding='utf-8')
print('Applied owner-requested license admission preference without changing source-rights evidence.')
