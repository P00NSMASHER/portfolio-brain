"""Hostile admission matrix for PR #725's unpublished controller.

Depends intentionally on the exact scoped PR #725 source, not protected main.
All provider calls are in-memory, all mutations must remain zero on denial.
"""
import copy
import unittest

from brain.v9 import guarded_merge as gm
from test_brain_v9_guarded_merge import FakeProvider, BASE, PR


class Tamper(FakeProvider):
    def __init__(self, transform=None):
        super().__init__()
        self.repo_setting_hidden = True
        self.ruleset_bypass_hidden = True
        self.transform = transform or (lambda response, n: response)

    def graphql(self, query, variables):
        value = super().graphql(query, variables)
        if query == gm.RULESET_QUERY:
            return self.transform(copy.deepcopy(value), self._ruleset_reads)
        return value


class HostileRulesetMatrix(unittest.TestCase):
    def denied(self, provider, reason="PROTECTED_RULESET_GRAPHQL_UNVERIFIED"):
        with self.assertRaisesRegex(gm.Denied, reason):
            gm.run(provider, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(provider.mutations, 0)
        self.assertFalse(provider.enabled)

    def test_realistic_restricted_token_positive_still_requires_source_gate(self):
        f = Tamper()
        f.no_acceptance = True
        self.denied(f, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED")
        self.assertEqual(f._ruleset_reads, 1)

    def test_forged_graphql_identity_and_enforcement_fail_closed(self):
        defects = [
            ("id_int_as_bool", lambda r: r["data"]["repository"].update(databaseId=True)),
            ("wrong_name", lambda r: r["data"]["repository"].update(nameWithOwner="attacker/repo")),
            ("archived", lambda r: r["data"]["repository"].update(isArchived=True)),
            ("ruleset_numeric_bool", lambda r: r["data"]["repository"]["rulesets"]["nodes"][0].update(databaseId=True)),
            ("ruleset_wrong_id", lambda r: r["data"]["repository"]["rulesets"]["nodes"][0].update(databaseId=1)),
            ("ruleset_disabled", lambda r: r["data"]["repository"]["rulesets"]["nodes"][0].update(enforcement="DISABLED")),
            ("ruleset_wrong_name", lambda r: r["data"]["repository"]["rulesets"]["nodes"][0].update(name="fake")),
        ]
        for title, edit in defects:
            with self.subTest(title=title):
                def change(response, _):
                    edit(response)
                    return response
                self.denied(Tamper(change))

    def test_truncated_or_contradictory_graphql_rule_collections_fail(self):
        defects = [
            ("missing_data", lambda r: r.pop("data")),
            ("graphql_error", lambda r: r.update(errors=[{"message": "insufficient scope"}])),
            ("missing_nodes", lambda r: r["data"]["repository"]["rulesets"].pop("nodes")),
            ("list_is_dict", lambda r: r["data"]["repository"]["rulesets"].update(nodes={})),
            ("missing_page", lambda r: r["data"]["repository"]["rulesets"].pop("pageInfo")),
            ("truncated", lambda r: r["data"]["repository"]["rulesets"]["pageInfo"].update(hasNextPage=True)),
            ("ambiguous_duplicate", lambda r: r["data"]["repository"]["rulesets"]["nodes"].append(copy.deepcopy(r["data"]["repository"]["rulesets"]["nodes"][0]))),
            ("missing_ruleset", lambda r: r["data"]["repository"]["rulesets"].update(nodes=[])),
            ("too_many_nodes", lambda r: r["data"]["repository"]["rulesets"].update(nodes=[{"databaseId":0}]*101)),
        ]
        for title, edit in defects:
            with self.subTest(title=title):
                def change(response, _):
                    edit(response)
                    return response
                self.denied(Tamper(change))

    def test_nonzero_bypass_and_bad_json_types_never_enroll(self):
        for count in (True, False, None, -1, 1, 2, 999, "0", [], {}, 0.0):
            with self.subTest(count=repr(count)):
                f = Tamper(lambda r, n: self._edit_count(r, count))
                self.denied(f)

    @staticmethod
    def _edit_count(response, count):
        response["data"]["repository"]["rulesets"]["nodes"][0]["bypassActors"]["totalCount"] = count
        return response

    def test_missing_bypass_and_pagination_fail(self):
        mutations = [
            lambda r: r["data"]["repository"]["rulesets"]["nodes"][0].pop("bypassActors"),
            lambda r: r["data"]["repository"]["rulesets"]["nodes"][0]["bypassActors"].pop("pageInfo"),
            lambda r: r["data"]["repository"]["rulesets"]["nodes"][0]["bypassActors"]["pageInfo"].update(hasNextPage=True),
            lambda r: r["data"]["repository"]["rulesets"]["nodes"][0]["bypassActors"]["pageInfo"].update(hasNextPage="false"),
            lambda r: r["data"]["repository"]["rulesets"]["nodes"][0]["bypassActors"].update(totalCount=[]),
        ]
        for n, edit in enumerate(mutations):
            with self.subTest(n=n):
                def change(response, _):
                    edit(response)
                    return response
                self.denied(Tamper(change))

    def test_final_ruleset_race_blocks_a_native_write(self):
        def change(response, count):
            if count == 2:
                return self._edit_count(response, 1)
            return response
        self.denied(Tamper(change))
        f = Tamper(change)
        self.denied(f)
        self.assertEqual(f._ruleset_reads, 2)

    def test_rest_bypass_field_ambiguity_never_infers_no_bypass(self):
        for bypass in (True, False, None, [{"actor_id": 1}], "[]", {}, 0):
            with self.subTest(bypass=repr(bypass)):
                f = Tamper()
                f.ruleset_bypass_hidden = False
                f.rules["bypass_actors"] = bypass
                self.denied(f, "PROTECTED_RULESET_MISMATCH")

    def test_source_acceptance_must_exist_even_when_every_setting_is_true(self):
        f = Tamper()
        f.no_acceptance = True
        self.denied(f, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED")
        self.assertEqual(f._ruleset_reads, 1)

    def test_check_issuer_substitution_blocks_enrollment(self):
        f = Tamper()
        f.checks["check_runs"][0]["app"]["id"] = 1
        self.denied(f, "INDEPENDENT_HEAD_CHECK_FAILED")

    def test_changed_head_after_initial_read_blocks_enrollment(self):
        f = Tamper()
        f.change_head = True
        self.denied(f, "PR_CHANGED_DURING_ADMISSION")

    def test_multiple_malicious_query_mutations_are_outside_allowlist(self):
        client = gm.GitHub("a" * 32)
        dangerous = (
            'mutation { deleteRepository(input:{repositoryId:"x"}) { clientMutationId }}',
            'query { viewer { login } }',
            gm.RULESET_QUERY + "\n# attacker-controlled extra operation",
        )
        for query in dangerous:
            with self.subTest(query=query[:24]):
                with self.assertRaisesRegex(gm.Denied, "GITHUB_GRAPHQL_NOT_APPROVED"):
                    client.graphql(query, {})

    def test_uri_and_rest_operation_smuggling_rejected_before_network(self):
        client = gm.GitHub("a" * 32)
        for path in (
            "repos/P00NSMASHER/portfolio-brain/../../repos/attacker/repo",
            "repos/P00NSMASHER/portfolio-brain/%2e%2e/secrets",
            "repos/attacker/repo",
            "repos/P00NSMASHER/portfolio-brain#private",
        ):
            with self.subTest(path=path):
                with self.assertRaises(gm.Denied):
                    client._request("GET", path)
        with self.assertRaises(gm.Denied):
            client._request("PATCH", "repos/" + gm.REPO + "/pulls/723", {})


if __name__ == "__main__":
    unittest.main()
