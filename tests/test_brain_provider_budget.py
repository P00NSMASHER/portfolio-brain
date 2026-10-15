"""Strict provider budget preservation under normal and retry paths."""
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from brain.adapters import GitHub
from brain.core import BrainError


class StrictProviderBudgetTests(unittest.TestCase):
    def test_exhausted_budget_does_not_increment_counter_or_call_network(self):
        calls=[]
        api=GitHub(transport=lambda _: calls.append("unexpected") or {})
        api.requests=24
        with self.assertRaises(BrainError):
            api.get("/repos/P00NSMASHER/portfolio-brain/branches/main")
        self.assertEqual(api.requests,24)
        self.assertEqual(calls,[])

    def test_retry_at_last_slot_does_not_make_twenty_fifth_read(self):
        calls=[]
        def failing(path):
            calls.append(path)
            raise HTTPError("https://api.github.com",503,
                            "unavailable",{"Retry-After":"0"},None)
        api=GitHub(transport=failing)
        api.requests=23
        with patch("brain.adapters.time.sleep",return_value=None):
            with self.assertRaises(BrainError):
                api.get("/repos/P00NSMASHER/portfolio-brain/branches/main")
        self.assertEqual(api.requests,24)
        self.assertEqual(len(calls),1)

    def test_last_legitimate_slot_is_still_usable_once(self):
        calls=[]
        api=GitHub(transport=lambda path: calls.append(path) or {
            "commit":{"sha":"a"*40}
        })
        api.requests=23
        result=api.get("/repos/P00NSMASHER/portfolio-brain/branches/main")
        self.assertEqual(result["commit"]["sha"],"a"*40)
        self.assertEqual(api.requests,24)
        self.assertEqual(len(calls),1)

if __name__=="__main__":
    unittest.main()
