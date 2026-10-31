"""Tests for owner-only, offline source/finances ingestion.

All records are synthetic. Never exercise a live account or source export.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from personal_investing.private_sources import (
    REPO_ROOT, _money, find_text, ingest_finances, report, scan_sources,
)


class PrivateSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base / "Know Me"
        self.src.mkdir()
        self.db = self.base / "private" / "owner.sqlite"

    def test_text_binary_office_and_archive_are_clearly_distinguished(self):
        (self.src / "Master Intelligence.txt").write_text(
            "Personal priority: spend time on hobbies.", encoding="utf-8")
        (self.src / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
        with ZipFile(self.src / "archive.zip", "w") as z:
            z.writestr("../../outside.txt", "DO NOT EXTRACT")
        with ZipFile(self.src / "notes.docx", "w") as z:
            z.writestr("word/document.xml",
                       '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                       "<w:body><w:p><w:r><w:t>Personal goals</w:t></w:r></w:p></w:body></w:document>")
        (self.src / "Patient_Clinical_Private.txt").write_text(
            "NEVER INDEX", encoding="utf-8")
        (self.src / "browser_cookies.json").write_text(
            '{"cookie": "SECRET"}', encoding="utf-8")
        result = scan_sources(self.src, self.db)
        self.assertEqual(result["files_seen"], 6)
        self.assertEqual(result["status"]["text_indexed"], 2)
        self.assertEqual(result["status"]["metadata_only"], 2)
        self.assertEqual(result["status"]["blocked"], 2)
        self.assertFalse((self.base / "outside.txt").exists())
        matches = find_text("goals", self.db)
        self.assertEqual([x["file"] for x in matches], ["notes.docx"])
        self.assertEqual(find_text("NEVER INDEX", self.db), [])
        self.assertEqual(find_text("SECRET", self.db), [])
        with sqlite3.connect(self.db) as db:
            archive = db.execute(
                "SELECT status FROM sources WHERE relpath='archive.zip'").fetchone()
            self.assertEqual(archive, ("metadata_only",))

    def test_idempotent_reread_and_search_input_is_literal(self):
        (self.src / "facts.txt").write_text("salary and budget", encoding="utf-8")
        scan_sources(self.src, self.db)
        (self.src / "facts.txt").write_text("savings account", encoding="utf-8")
        scan_sources(self.src, self.db)
        self.assertFalse(find_text("salary", self.db))
        self.assertTrue(find_text("savings", self.db))
        self.assertFalse(find_text("%", self.db))
        self.assertEqual(report(self.db)["files"], {"text_indexed": 1})

    def test_symlink_outside_folder_is_skipped(self):
        outside = self.base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            (self.src / "alias.txt").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        result = scan_sources(self.src, self.db)
        self.assertEqual(result["files_seen"], 0)

    def test_source_inside_repo_must_not_be_used_as_private_storage(self):
        with self.assertRaisesRegex(ValueError, "OUTSIDE"):
            scan_sources(self.src, REPO_ROOT / "private_runtime" / "should-not-write.sqlite")

    def test_finance_snapshot_is_local_and_cannot_mutate_accounts(self):
        payload = {
            "source": "OWNER_EXPORTED_READ_ONLY",
            "captured_at": "2026-10-31T02:00:00-04:00",
            "coverage": {"freshness": "unknown", "transactions": "sample only"},
            "accounts": [
                {"id": "SAMPLE-BANK-1", "institution": "Synthetic Credit Union",
                 "name": "Checking", "type": "depository",
                 "balance_usd": "1234.56", "available_usd": None,
                 "balance_date": ""}
            ],
            "holdings": [
                {"id": "SAMPLE-HOLD-1", "account_ref": "SAMPLE-RETIREMENT-1",
                 "security": "Synthetic Example", "ticker": "SIM",
                 "quantity": "2.50", "value_usd": "100.00",
                 "price_date": "2026-10-30"}
            ],
            "transactions": [
                {"id": "SAMPLE-TXN-1", "account_ref": "SAMPLE-BANK-1",
                 "date": "2026-10-29", "description": "Synthetic grocery purchase",
                 "signed_amount": "42.33", "pending": False,
                 "category": "groceries"}
            ],
            "recurring": [
                {"id": "SAMPLE-RECURRING-1", "description": "Synthetic subscription",
                 "frequency": "monthly", "amount_usd": "10", "next_date": "2026-11-15"}
            ]
        }
        source = self.base / "finances.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = ingest_finances(source, self.db)
        self.assertEqual(result["imported"], {"accounts": 1, "holdings": 1, "transactions": 1, "recurring": 1})
        self.assertEqual(report(self.db)["finance"]["transactions"], 1)
        self.assertEqual(source.read_text(encoding="utf-8"), json.dumps(payload))
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT signed_amount FROM finance_transactions").fetchone()[0], "42.33")

    def test_credentials_and_infinite_values_are_fail_closed(self):
        src = self.base / "finance.json"
        for bad in (
            {"source": "OWNER_EXPORTED_READ_ONLY", "captured_at": "2026-10-31", "access_token": "no"},
            {"source": "OWNER_EXPORTED_READ_ONLY", "captured_at": "2026-10-31",
             "accounts": [{"id": "a", "balance_usd": "NaN"}]},
            {"source": "UNVERIFIED_LIVE", "captured_at": "2026-10-31"},
            {"source": "OWNER_EXPORTED_READ_ONLY", "captured_at": "2026-10-31",
             "transactions": [{"id": "bad", "signed_amount": "0", "pending": "false"}]},
        ):
            src.write_text(json.dumps(bad), encoding="utf-8")
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ingest_finances(src, self.db)
        self.assertEqual(report(self.db)["finance"]["transactions"], 0)

    def test_no_partial_mutation_on_invalid_later_rows(self):
        src = self.base / "finance.json"
        payload = {"source": "OWNER_EXPORTED_READ_ONLY", "captured_at": "2026-10-31",
                   "accounts": [{"id": "valid", "institution": "Synthetic",
                                 "balance_usd": "1"}],
                   "transactions": [{"id": "bad", "signed_amount": "Infinity"}]}
        src.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            ingest_finances(src, self.db)
        self.assertEqual(report(self.db)["finance"]["accounts"], 0)

    def test_finance_amount_precision_and_no_arbitrary_numeric_nan(self):
        self.assertEqual(_money("12345.678901"), "12345.678901")
        for bad in ("Infinity", "-Infinity", "NaN", "1e1000", "hello"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                _money(bad)


if __name__ == "__main__":
    unittest.main()
