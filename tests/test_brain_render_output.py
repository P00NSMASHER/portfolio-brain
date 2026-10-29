"""Adversarial private report-output tests, including CLI error handling.

No remote calls, production files, external credentials, or paid services.
"""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.core import BrainError
from brain.render import write_report, write_private_test_log

SOURCE = "a" * 40


def report(label="PASS"):
    return {
        "status": label,
        "source_sha": SOURCE,
        "repositories": [],
        "repository_changes": [],
        "reuse_candidates": [],
        "business_opportunities": [],
        "learning": {"experiments": []},
    }


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class PrivateReportOutputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.out = self.root / "report"

    def test_new_bundle_is_private_and_preserves_existing_content_contract(self):
        original = report()
        write_report(original, self.out)
        self.assertEqual(mode(self.out), 0o700)
        for name in ("report.json", "report.md", "report.html"):
            self.assertTrue((self.out / name).is_file())
            self.assertEqual(mode(self.out / name), 0o600)
        self.assertEqual(json.loads((self.out / "report.json").read_text()), original)
        self.assertIn("# Portfolio Brain", (self.out / "report.md").read_text())
        self.assertIn("<!doctype html>", (self.out / "report.html").read_text())

    def test_rewrite_privately_replaces_existing_reports(self):
        write_report(report("PASS"), self.out)
        old_inode = (self.out / "report.json").stat().st_ino
        write_report(report("BLOCKED"), self.out)
        self.assertEqual(
            json.loads((self.out / "report.json").read_text())["status"],
            "BLOCKED",
        )
        self.assertNotEqual((self.out / "report.json").stat().st_ino, old_inode)
        self.assertEqual(mode(self.out), 0o700)
        self.assertTrue(all(mode(self.out / x) == 0o600 for x in
                            ("report.json", "report.md", "report.html")))
        self.assertEqual(set(p.name for p in self.out.iterdir()),
                         {"report.json", "report.md", "report.html"})

    def test_existing_shared_directory_is_refused_without_permission_change(self):
        self.out.mkdir(mode=0o755)
        os.chmod(self.out, 0o755)
        sentinel = self.out / "notes.txt"
        sentinel.write_text("keep")
        os.chmod(sentinel, 0o644)
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_EXISTING_DIRECTORY_NOT_PRIVATE"):
            write_report(report(), self.out)
        self.assertEqual(mode(self.out), 0o755)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(mode(sentinel), 0o644)
        self.assertEqual({p.name for p in self.out.iterdir()}, {"notes.txt"})

    def test_existing_private_directory_does_not_chmod_unrelated_files(self):
        self.out.mkdir(mode=0o700)
        os.chmod(self.out, 0o700)
        note = self.out / "notes.txt"
        note.write_text("retained")
        os.chmod(note, 0o644)
        write_report(report(), self.out)
        self.assertEqual(note.read_text(), "retained")
        self.assertEqual(mode(note), 0o644)
        self.assertEqual(mode(self.out), 0o700)

    def test_target_symlink_is_refused_before_any_report_is_created(self):
        for name in ("report.json", "report.md", "report.html"):
            with self.subTest(name=name):
                out = self.root / ("out-" + name)
                out.mkdir(mode=0o700)
                os.chmod(out, 0o700)
                source = self.root / ("original-" + name)
                source.write_text("do not overwrite")
                (out / name).symlink_to(source)
                with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_SYMLINK_HARDLINK"):
                    write_report(report(), out)
                self.assertEqual(source.read_text(), "do not overwrite")
                self.assertTrue((out / name).is_symlink())
                self.assertEqual({p.name for p in out.iterdir()}, {name})

    def test_broken_symlink_is_not_silently_replaced(self):
        self.out.mkdir(mode=0o700)
        os.chmod(self.out, 0o700)
        (self.out / "report.json").symlink_to(self.root / "nonexistent.sqlite")
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_SYMLINK_HARDLINK"):
            write_report(report(), self.out)
        self.assertTrue((self.out / "report.json").is_symlink())

    def test_existing_hard_link_cannot_truncate_sensitive_authority(self):
        self.out.mkdir(mode=0o700)
        os.chmod(self.out, 0o700)
        original = self.root / "authority.sqlite"
        original.write_bytes(b"preserve-original-sqlite-bytes")
        os.link(original, self.out / "report.json")
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_SYMLINK_HARDLINK"):
            write_report(report(), self.out)
        self.assertEqual(original.read_bytes(), b"preserve-original-sqlite-bytes")
        self.assertEqual((self.out / "report.json").stat().st_ino, original.stat().st_ino)
        self.assertEqual({p.name for p in self.out.iterdir()}, {"report.json"})

    def test_directory_or_parent_symlink_is_refused(self):
        real = self.root / "real"
        real.mkdir()
        direct = self.root / "alias"
        direct.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_SYMLINK_DIRECTORY_REFUSED"):
            write_report(report(), direct)
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_SYMLINK_DIRECTORY_REFUSED"):
            write_report(report(), direct / "report")
        self.assertEqual(list(real.iterdir()), [])

    def test_existing_regular_file_is_not_a_directory(self):
        self.out.write_text("not a folder")
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_UNSAFE_DIRECTORY"):
            write_report(report(), self.out)
        self.assertEqual(self.out.read_text(), "not a folder")

    def test_failed_json_replacement_keeps_previous_canonical_receipt(self):
        write_report(report("PASS"), self.out)
        before = (self.out / "report.json").read_bytes()
        real_replace = os.replace

        def fail_on_json(source, destination, **kwargs):
            if destination == "report.json":
                raise OSError("simulated JSON rename interruption")
            return real_replace(source, destination, **kwargs)

        with patch("brain.render.os.replace", side_effect=fail_on_json):
            with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_PRIVATE_WRITE_FAILED"):
                write_report(report("BLOCKED"), self.out)

        self.assertEqual((self.out / "report.json").read_bytes(), before)
        self.assertEqual(set(p.name for p in self.out.iterdir()),
                         {"report.json", "report.md", "report.html"})
        self.assertTrue(all(mode(self.out / x) == 0o600 for x in
                            ("report.json", "report.md", "report.html")))

    def test_unsafe_cli_output_does_not_create_secondary_failure_receipt(self):
        from brain.__main__ import main

        self.out.mkdir(mode=0o755)
        os.chmod(self.out, 0o755)
        db = self.root / "db" / "state.sqlite"
        with patch("brain.__main__.source_sha", return_value=SOURCE):
            with contextlib.redirect_stderr(io.StringIO()):
                result = main([
                    "init", "--db", str(db), "--output", str(self.out),
                ])
        self.assertEqual(result, 1)
        self.assertEqual(mode(self.out), 0o755)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_preflight_log_is_private_and_preserved_by_report_write(self):
        write_private_test_log(self.out, "Ran 3 tests\nOK\n")
        self.assertEqual(mode(self.out), 0o700)
        self.assertEqual(mode(self.out / "tests.txt"), 0o600)
        write_report(report(), self.out)
        self.assertEqual((self.out / "tests.txt").read_text(),
                         "Ran 3 tests\nOK\n")
        self.assertEqual(mode(self.out / "tests.txt"), 0o600)

    def test_preflight_log_alias_is_rejected_without_overwriting_source(self):
        self.out.mkdir(mode=0o700)
        os.chmod(self.out, 0o700)
        original = self.root / "original-sqlite.txt"
        original.write_text("untouched")
        (self.out / "tests.txt").symlink_to(original)
        with self.assertRaisesRegex(BrainError, "REPORT_OUTPUT_SYMLINK_HARDLINK"):
            write_private_test_log(self.out, "sensitive test output")
        self.assertEqual(original.read_text(), "untouched")
        self.assertEqual({p.name for p in self.out.iterdir()}, {"tests.txt"})

    def test_no_temporary_files_left_after_serialization_error(self):
        bad = report()
        bad["invalid_number"] = float("nan")
        with self.assertRaises(ValueError):
            write_report(bad, self.out)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
