"""Backup must never overwrite the canonical SQLite inode through an alias.

All assets are disposable local SQLite files; no GitHub, cloud, tokens, tasks
or production state are accessed. Tests exercise public and private modes.
"""
import contextlib
import hashlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.adapters import event
from brain.core import BrainError, Store

SOURCE = "a" * 40
NOW = "2026-10-09T18:00:00Z"
LATER = "2026-10-09T18:05:00Z"
REPO = "ExampleOrg/verified-state"


def record():
    return event("repository", REPO, {
        "repository": REPO, "head_sha": SOURCE, "default_branch": "main",
        "checks": [], "open_issues": 3,
        "source_ref": f"https://github.com/{REPO}/commit/{SOURCE}",
    }, SOURCE, now=NOW)


def perms(path):
    return stat.S_IMODE(path.stat().st_mode)


class PrivateBackupSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "state.sqlite"
        self.store = Store(self.source, visibility="PUBLIC")
        self.addCleanup(self.store.close)
        self.store.submit([record()], now=LATER)
        self.store.drain()
        self.saved = self.store.report(SOURCE, now=LATER)
        self.target = self.root / "backup.sqlite"

    def assert_clean_temp(self):
        self.assertEqual([x.name for x in self.root.iterdir()
                          if x.name.startswith(".brain-backup-")], [])

    def test_private_backup_is_verified_and_reopens_without_loss(self):
        digest = self.store.backup(self.target)
        self.assertEqual(digest, hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(perms(self.target), 0o600)
        self.assertEqual(self.store.read_report(SOURCE, now=LATER), self.saved)
        copied = Store(self.target, visibility="PUBLIC")
        try:
            self.assertEqual(copied.read_report(SOURCE, now=LATER), self.saved)
            self.assertEqual(copied.pending(), 0)
        finally:
            copied.close()
        self.assert_clean_temp()

    def test_repeat_replaces_only_the_backup_regular_inode(self):
        first_sha = self.store.backup(self.target)
        first_inode = self.target.stat().st_ino
        self.store.submit([event("repository", REPO, {
            **record()["payload"], "open_issues": 9,
        }, SOURCE, now=LATER)], now=LATER)
        self.store.drain()
        second_sha = self.store.backup(self.target)
        self.assertNotEqual(first_sha, second_sha)
        self.assertNotEqual(first_inode, self.target.stat().st_ino)
        self.assertEqual(perms(self.target), 0o600)
        self.assert_clean_temp()

    def test_direct_same_file_is_refused_without_ledger_mutation(self):
        before = self.source.read_bytes()
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SOURCE_ALIAS_REFUSED"):
            self.store.backup(self.source)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.store.read_report(SOURCE, now=LATER), self.saved)

    def test_hardlink_to_live_authority_is_never_opened_for_write(self):
        before = self.source.read_bytes()
        os.link(self.source, self.target)
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SYMLINK_HARDLINK"):
            self.store.backup(self.target)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.target.stat().st_ino, self.source.stat().st_ino)
        self.assertEqual(self.store.read_report(SOURCE, now=LATER), self.saved)
        self.assert_clean_temp()

    def test_hardlink_to_other_file_is_refused_without_modifying_other_file(self):
        other = self.root / "other.sqlite"
        other.write_bytes(b"not a database, do not replace")
        os.link(other, self.target)
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SYMLINK_HARDLINK"):
            self.store.backup(self.target)
        self.assertEqual(other.read_bytes(), b"not a database, do not replace")
        self.assert_clean_temp()

    def test_existing_symlink_to_unrelated_file_is_refused(self):
        other = self.root / "unrelated.txt"
        other.write_text("keep intact")
        self.target.symlink_to(other)
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SYMLINK_HARDLINK"):
            self.store.backup(self.target)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(other.read_text(), "keep intact")
        self.assert_clean_temp()

    def test_dangling_symlink_is_not_silently_replaced(self):
        self.target.symlink_to(self.root / "missing.sqlite")
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SYMLINK_HARDLINK"):
            self.store.backup(self.target)
        self.assertTrue(self.target.is_symlink())
        self.assert_clean_temp()

    def test_backup_destination_directory_is_not_a_file(self):
        self.target.mkdir()
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SYMLINK_HARDLINK"):
            self.store.backup(self.target)
        self.assertTrue(self.target.is_dir())
        self.assert_clean_temp()

    def test_symlinked_parent_is_refused_without_creating_backup(self):
        folder = self.root / "real"
        folder.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(folder, target_is_directory=True)
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_SYMLINK_DIRECTORY"):
            self.store.backup(alias / "backup.sqlite")
        self.assertEqual(list(folder.iterdir()), [])

    def test_group_writable_directory_rejected_without_mode_change(self):
        folder = self.root / "shared"
        folder.mkdir()
        os.chmod(folder, 0o775)
        with self.assertRaisesRegex(BrainError, "BACKUP_OUTPUT_DIRECTORY_NOT_PRIVATE_ENOUGH"):
            self.store.backup(folder / "backup.sqlite")
        self.assertEqual(perms(folder), 0o775)
        self.assertEqual(list(folder.iterdir()), [])

    def test_existing_nonwritable_by_others_folder_keeps_its_mode(self):
        folder = self.root / "readable"
        folder.mkdir()
        os.chmod(folder, 0o755)
        path = folder / "backup.sqlite"
        digest = self.store.backup(path)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(perms(folder), 0o755)
        self.assertEqual(perms(path), 0o600)

    def test_created_nested_destination_is_private(self):
        folder = self.root / "new" / "nested"
        path = folder / "backup.sqlite"
        self.store.backup(path)
        self.assertEqual(perms(folder), 0o700)
        self.assertEqual(perms(path), 0o600)

    def test_failed_atomic_replace_keeps_previous_verified_backup(self):
        self.store.backup(self.target)
        before = self.target.read_bytes()
        with patch("brain.core.os.replace", side_effect=OSError("simulated IO fault")):
            with self.assertRaisesRegex(BrainError, "BACKUP_PRIVATE_COPY_FAILED"):
                self.store.backup(self.target)
        self.assertEqual(self.target.read_bytes(), before)
        self.assert_clean_temp()
        self.assertEqual(self.store.read_report(SOURCE, now=LATER), self.saved)

    def test_failed_ledger_verification_preserves_previous_backup(self):
        self.store.backup(self.target)
        before = self.target.read_bytes()
        with patch.object(Store, "_verified_events", side_effect=BrainError(
                "synthetic invalid ledger")):
            with self.assertRaisesRegex(BrainError, "synthetic invalid ledger"):
                self.store.backup(self.target)
        self.assertEqual(self.target.read_bytes(), before)
        self.assert_clean_temp()

    def test_pending_events_are_backed_up_without_draining_source(self):
        pending = event("repository", REPO, {
            **record()["payload"], "open_issues": 7,
        }, SOURCE, now=LATER)
        self.store.submit([pending], now=LATER)
        self.assertEqual(self.store.pending(), 1)
        self.store.backup(self.target)
        self.assertEqual(self.store.pending(), 1)
        copied = Store(self.target, visibility="PUBLIC")
        try:
            self.assertEqual(copied.pending(), 1)
            self.assertEqual(
                copied.db.execute("SELECT count(*) FROM ledger").fetchone()[0],
                1,
            )
        finally:
            copied.close()

    def test_backup_cli_failure_does_not_drain_or_emit_secondary_report(self):
        from brain.__main__ import main
        pending = event("repository", REPO, {
            **record()["payload"], "open_issues": 8,
        }, SOURCE, now=LATER)
        self.store.submit([pending], now=LATER)
        self.assertEqual(self.store.pending(), 1)
        os.link(self.source, self.target)
        attempts_before = self.store.db.execute(
            "SELECT count(*) FROM attempts"
        ).fetchone()[0]
        with patch("brain.__main__.source_sha", return_value=SOURCE):
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(["backup", "--db", str(self.source),
                             "--output", str(self.target)])
        self.assertEqual(code, 1)
        self.assertEqual(self.store.pending(), 1)
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0],
            attempts_before,
        )
        self.assertTrue(self.target.exists())
        self.assertEqual(self.target.stat().st_ino, self.source.stat().st_ino)
        self.assert_clean_temp()

    def test_private_database_backups_retain_visibility(self):
        private_path = self.root / "private.sqlite"
        private = Store(private_path, visibility="PRIVATE")
        try:
            dest = self.root / "private-backup.sqlite"
            private.backup(dest)
            copy = Store(dest, visibility="PRIVATE")
            try:
                self.assertEqual(copy.visibility, "PRIVATE")
            finally:
                copy.close()
        finally:
            private.close()


if __name__ == "__main__":
    unittest.main()
