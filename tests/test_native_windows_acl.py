"""ACL policy tests; real Windows API acceptance is a separate device check."""
import importlib
import unittest

SID = 'S-1-5-21-1-2-3-1001'


class WindowsACLPolicyTests(unittest.TestCase):
    def module(self):
        try: mod = importlib.import_module('verification.native_windows_acl')
        except ImportError: mod = None
        self.assertIsNotNone(mod, 'Windows private-storage ACL verifier is missing')
        return mod

    def test_only_owner_system_and_administrators_are_accepted(self):
        self.module().validate_acl(SID, SID, [(0, 0x1f01ff, SID, 0),
            (0, 0x1f01ff, 'S-1-5-18', 0), (0, 0x1f01ff, 'S-1-5-32-544', 0)])

    def test_foreign_owner_is_denied(self):
        mod = self.module()
        with self.assertRaises(mod.ACLDenied): mod.validate_acl('S-1-5-18', SID, [(0, 1, SID, 0)])

    def test_null_empty_and_unknown_acl_are_denied(self):
        mod = self.module()
        for rules in (None, [], [(5, 1, SID, 0)]):
            with self.assertRaises(mod.ACLDenied): mod.validate_acl(SID, SID, rules)

    def test_world_users_and_authenticated_users_are_denied(self):
        mod = self.module()
        for other in ('S-1-1-0', 'S-1-5-32-545', 'S-1-5-11'):
            with self.assertRaises(mod.ACLDenied):
                mod.validate_acl(SID, SID, [(0, 1, SID, 0), (0, 1, other, 0)])

    def test_inherit_only_broad_grant_still_exposes_future_files(self):
        mod = self.module()
        with self.assertRaises(mod.ACLDenied):
            mod.validate_acl(SID, SID, [(0, 1, SID, 0), (0, 1, 'S-1-1-0', 8)])

    def test_owner_must_have_effective_allow_entry(self):
        mod = self.module()
        for rules in ([(1, 1, SID, 0)], [(0, 1, SID, 8)], [(0, 0, SID, 0)]):
            with self.assertRaises(mod.ACLDenied): mod.validate_acl(SID, SID, rules)

    def test_deny_entries_do_not_grant_access(self):
        self.module().validate_acl(SID, SID, [(0, 1, SID, 0), (1, 1, 'S-1-1-0', 0)])

    def test_malformed_sid_or_ace_is_denied(self):
        mod = self.module()
        for rules in ([None], [(False, 1, SID, 0)], [(0, True, SID, 0)],
                      [(0, 1, 'administrator', 0)], [(0, 1, SID, 999)]):
            with self.assertRaises(mod.ACLDenied): mod.validate_acl(SID, SID, rules)


if __name__ == '__main__': unittest.main()
