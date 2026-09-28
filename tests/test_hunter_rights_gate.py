import unittest

from hunting.rights_gate import build_rights_record, validate_rights_record

def candidate(spdx=None):
    return {
      "id":1,
      "full_name":"example/project",
      "private":False,
      "license":None if spdx is None else {"spdx_id":spdx},
    }

def inspection():
    return {
      "revision":"a"*40,
      "tree_sha":"b"*40,
      "paths":["LICENSE","src/core.py","tests/test_core.py","package-lock.json"],
      "truncated":False,
    }

class RightsGateTests(unittest.TestCase):
    def test_mit_is_permissive_but_never_auto_authorized(self):
        text="MIT License\nCopyright (c) 2026 Example Corp\nPermission is hereby granted, free of charge, to any person obtaining a copy"
        r=build_rights_record(candidate("MIT"),inspection(),{"license_path":"LICENSE","license_text":text})
        validate_rights_record(r)
        self.assertEqual(r["rights_classification"],"PERMISSIVE_DEPENDENCY")
        self.assertTrue(r["commercial_use_allowed"])
        self.assertTrue(r["modification_allowed"])
        self.assertFalse(r["automatic_reuse_authority_granted"])
        self.assertEqual(r["copyright_owner"],"Example Corp")
        self.assertTrue(r["license_text_hash"].startswith("sha256:"))
        self.assertIn("package-lock.json",r["dependency_manifest_paths"])

    def test_agpl_requires_review_and_marks_network_copyleft(self):
        r=build_rights_record(candidate("AGPL-3.0-only"),inspection())
        validate_rights_record(r)
        self.assertEqual(r["rights_classification"],"COPYLEFT_REVIEW")
        self.assertTrue(r["network_copyleft"])
        self.assertTrue(r["source_disclosure_required"])

    def test_no_license_fails_closed(self):
        r=build_rights_record(candidate(None),inspection())
        validate_rights_record(r)
        self.assertEqual(r["rights_classification"],"NO_LICENSE_NO_REUSE")
        self.assertFalse(r["commercial_use_allowed"])
        self.assertFalse(r["modification_allowed"])
        self.assertEqual(r["allowed_integration_mode"],"ARCHITECTURE_STUDY_ONLY_NO_CODE_REUSE")

    def test_restricted_source_available_requires_separate_permission(self):
        r=build_rights_record(candidate("PolyForm-Noncommercial-1.0.0"),inspection())
        validate_rights_record(r)
        self.assertEqual(r["rights_classification"],"SEPARATE_PERMISSION_REQUIRED")
        self.assertIsNone(r["commercial_use_allowed"])

if __name__=="__main__":
    unittest.main()
