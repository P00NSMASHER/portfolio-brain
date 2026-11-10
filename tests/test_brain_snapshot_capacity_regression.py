"""Regression for the original brain-cycle project snapshot size failure.

The source SQLite remains read-only. Only the measured file size is mocked,
so the SQLite integrity check and backup still execute on a real database.
"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.core import BrainError
from brain.state_maintenance import VERIFIED_PRODUCTION_RAW_BYTES
from brain.transfer import readonly_authority_snapshot


class SnapshotCapacityRegression(unittest.TestCase):
    def test_readonly_snapshot_uses_verified_production_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.sqlite"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE marker (value INTEGER)")
                connection.execute("INSERT INTO marker VALUES (42)")
            original_bytes = source.read_bytes()
            original_stat = Path.stat
            measured_bytes = [0]

            def stat_with_measured_size(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if path == source:
                    fields = list(result)
                    fields[6] = measured_bytes[0]  # os.stat_result.st_size
                    return os.stat_result(fields)
                return result

            with patch.object(Path, "stat", stat_with_measured_size):
                for size in (128_000_001, VERIFIED_PRODUCTION_RAW_BYTES):
                    with self.subTest(size=size):
                        measured_bytes[0] = size
                        with readonly_authority_snapshot(source) as snapshot:
                            with sqlite3.connect(snapshot) as copy:
                                self.assertEqual(
                                    copy.execute("SELECT value FROM marker").fetchone(),
                                    (42,),
                                )
                measured_bytes[0] = VERIFIED_PRODUCTION_RAW_BYTES + 1
                with self.assertRaisesRegex(
                    BrainError, "TRANSFER_STATE_SIZE_UNSUPPORTED"
                ):
                    with readonly_authority_snapshot(source):
                        self.fail("Oversized source passed the capacity guard")

            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertFalse(Path(str(source) + "-wal").exists())
            self.assertFalse(Path(str(source) + "-journal").exists())


if __name__ == "__main__":
    unittest.main()
