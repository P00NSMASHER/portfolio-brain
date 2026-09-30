import unittest
from pathlib import Path
from unittest.mock import patch

from verification.independent_verifier import (
    IndependentVerifierError,
    publish_check,
    verify_exact_head,
)


ROOT = Path(__file__).resolve().parents[1]


class IndependentVerifierTests(unittest.TestCase):
    def responses(self, *, foundation_app=15368, foundation_conclusion="success", compare_files=None):
        main_sha="b"*40
        head_sha="c"*40
        if compare_files is None:
            compare_files=[]
        return [
            {
                "head":{"repo":{"full_name":"P00NSMASHER/portfolio-brain"},"sha":head_sha},
                "base":{"repo":{"full_name":"P00NSMASHER/portfolio-brain"},"ref":"main"},
            },
            {"commit":{"sha":main_sha}},
            {"merge_base_commit":{"sha":main_sha},"files":compare_files},
            {"check_runs":[{
                "name":"validate","conclusion":foundation_conclusion,
                "app":{"id":foundation_app},
            }]},
        ]

    def test_exact_head_requires_current_main_foundation_and_all_isolated_tests(self):
        with patch("verification.independent_verifier._api", side_effect=self.responses()):
            ok,summary=verify_exact_head(
                token="token",pr_number=7,expected_head_sha="c"*40,
                full_exit=0,phase1_exit=0,operating_exit=0,
            )
        self.assertTrue(ok)
        self.assertIn("Independent isolated verification passed",summary)

    def test_candidate_cannot_rewrite_verifier_trust_anchors(self):
        responses=self.responses(compare_files=[{"filename":"verification/independent_verifier.py"}])
        with patch("verification.independent_verifier._api", side_effect=responses):
            with self.assertRaisesRegex(IndependentVerifierError,"immutable verifier trust anchor"):
                verify_exact_head(
                    token="token",pr_number=7,expected_head_sha="c"*40,
                    full_exit=0,phase1_exit=0,operating_exit=0,
                )

    def test_non_verifier_changes_remain_eligible(self):
        responses=self.responses(compare_files=[
            {"filename":"runtime/state.py"},{"filename":"tests/test_runtime_new.py"}
        ])
        with patch("verification.independent_verifier._api", side_effect=responses):
            ok,_=verify_exact_head(
                token="token",pr_number=7,expected_head_sha="c"*40,
                full_exit=0,phase1_exit=0,operating_exit=0,
            )
        self.assertTrue(ok)

    def test_trust_anchor_scope_uses_current_main_compare_not_historical_pr_files(self):
        calls=[]
        responses=self.responses(compare_files=[{"filename":"verification/HOSTED_VERIFIER_BOOTSTRAP_PROOF.md"}])
        def fake_api(token,path,**kwargs):
            calls.append(path)
            return responses.pop(0)
        with patch("verification.independent_verifier._api", side_effect=fake_api):
            ok,_=verify_exact_head(
                token="token",pr_number=7,expected_head_sha="c"*40,
                full_exit=0,phase1_exit=0,operating_exit=0,
            )
        self.assertTrue(ok)
        self.assertFalse(any("/pulls/7/files" in path for path in calls))
        self.assertTrue(any(path.startswith("/compare/") for path in calls))

    def test_current_main_compare_file_cap_fails_closed(self):
        responses=self.responses(compare_files=[
            {"filename":f"runtime/generated-{index}.py"} for index in range(300)
        ])
        with patch("verification.independent_verifier._api", side_effect=responses):
            with self.assertRaisesRegex(IndependentVerifierError,"compare file listing hit verifier bound"):
                verify_exact_head(
                    token="token",pr_number=7,expected_head_sha="c"*40,
                    full_exit=0,phase1_exit=0,operating_exit=0,
                )

    def test_foundation_check_from_wrong_app_cannot_authorize_gate(self):
        with patch("verification.independent_verifier._api", side_effect=self.responses(foundation_app=999)):
            with self.assertRaisesRegex(IndependentVerifierError,"Foundation validation"):
                verify_exact_head(
                    token="token",pr_number=7,expected_head_sha="c"*40,
                    full_exit=0,phase1_exit=0,operating_exit=0,
                )

    def test_test_failure_produces_red_decision_not_green(self):
        with patch("verification.independent_verifier._api", side_effect=self.responses()):
            ok,summary=verify_exact_head(
                token="token",pr_number=7,expected_head_sha="c"*40,
                full_exit=1,phase1_exit=0,operating_exit=0,
            )
        self.assertFalse(ok)
        self.assertIn("full=1",summary)

    def test_publish_check_must_be_attributed_to_verifier_app_5121826(self):
        response={
            "id":123,"name":"portfolio-phase1-gate","head_sha":"c"*40,
            "app":{"id":5121826},
        }
        with patch("verification.independent_verifier._api", return_value=response) as api:
            result=publish_check(token="token",head_sha="c"*40,success=True,summary="pass")
        self.assertEqual(result["app"]["id"],5121826)
        payload=api.call_args.kwargs["payload"]
        self.assertEqual(payload["name"],"portfolio-phase1-gate")
        self.assertEqual(payload["conclusion"],"success")

    def test_hosted_verifier_auto_integrates_only_bot_repair_prs(self):
        text=(ROOT/".github/workflows/portfolio-independent-verifier.yml").read_text()
        permissions=text.split("permissions:",1)[1].split("concurrency:",1)[0]
        self.assertIn("contents: write",permissions)
        self.assertIn("pull-requests: write",permissions)
        self.assertNotIn("actions: write",permissions)
        self.assertIn('branch.startswith("factory/auto-repair-")',text)
        self.assertIn('"AUTO_REPAIR_FINGERPRINT:" in body',text)
        self.assertIn('pr.get("user",{}).get("login")=="github-actions[bot]"',text)
        self.assertIn("/update-branch",text)
        self.assertIn("steps.pr.outputs.autonomous == 'true'",text)
        self.assertIn("merge_method=merge",text)
        self.assertIn('-f sha="$CANDIDATE_SHA"',text)

    def test_verifier_still_uses_independent_app_gate_before_merge(self):
        text=(ROOT/".github/workflows/portfolio-independent-verifier.yml").read_text()
        self.assertLess(text.index("Publish exact-head independent gate"),text.index("Merge verified autonomous repair through branch protection"))
        self.assertIn('app-id: "5121826"',text)
        self.assertIn("secrets.PORTFOLIO_VERIFIER_PRIVATE_KEY",text)
        self.assertNotIn("git push origin main",text.lower())
        self.assertNotIn("--admin",text.lower())

    def test_hosted_verifier_copy_preserves_isolation_without_privileged_ownership_copy(self):
        text=(ROOT/".github/workflows/portfolio-independent-verifier.yml").read_text()
        self.assertNotIn("cp -a /src /work",text)
        self.assertEqual(text.count("cp -R --no-preserve=ownership /src/. /work/"),3)
        self.assertEqual(text.count("--network none"),3)
        self.assertEqual(text.count("--cap-drop=ALL"),3)
        self.assertEqual(text.count("--security-opt=no-new-privileges"),3)

    def test_publish_check_rejects_wrong_app_attribution(self):
        response={
            "id":123,"name":"portfolio-phase1-gate","head_sha":"c"*40,
            "app":{"id":15368},
        }
        with patch("verification.independent_verifier._api", return_value=response):
            with self.assertRaisesRegex(IndependentVerifierError,"independent verifier App"):
                publish_check(token="token",head_sha="c"*40,success=True,summary="pass")


if __name__=="__main__":
    unittest.main()
