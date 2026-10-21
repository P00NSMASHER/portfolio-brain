"""Real Windows ACL and SQLite no-retry smoke test; synthetic temp only.

Skipped on non-Windows hosts. This changes only a freshly created disposable
directory's ACL, never an existing user or repository path. No GitHub requests,
credentials, production actions, or external approval checks are involved.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from verification import native_final_approval as approval
from verification.native_intent_store import IntentStore, StoreDenied

WINDOWS_PRIVATE_ACL = r'''
$ErrorActionPreference = 'Stop'
$path = Join-Path $env:PB_WINDOWS_TEST_DIR 'private'
New-Item -ItemType Directory -Path $path | Out-Null
if (-not [System.IO.Directory]::Exists($path)) { throw 'TEST_DIR_MISSING' }
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $sid,
    [System.Security.AccessControl.FileSystemRights]::FullControl,
    ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
    [System.Security.AccessControl.PropagationFlags]::None,
    [System.Security.AccessControl.AccessControlType]::Allow
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $path -AclObject $acl
'''

SOURCE, POLICY, HEAD = 'a' * 40, 'b' * 40, 'c' * 40
STORE_ID = 'e' * 64
NOW = datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc)
CONTEXT = {'expected_source_sha': SOURCE, 'expected_policy_sha': POLICY, 'now': NOW}


def synthetic_ticket():
    return dict(
        repository=approval.REPOSITORY, repository_id=approval.REPOSITORY_ID,
        pr_number=735, pr_node_id='PR_kwDOUrdY3c8test735',
        head_ref='canary/intent-735', head_sha=HEAD,
        base_ref='main', base_sha=SOURCE, controller_source_sha=SOURCE,
        policy_sha=POLICY, approval_check_id=101,
        issued_at='2026-10-21T02:25:00Z', expires_at='2026-10-21T02:35:00Z')


@unittest.skipUnless(os.name == 'nt', 'Windows native ACL smoke test')
class WindowsNativeIntentSmokeTests(unittest.TestCase):
    def test_private_acl_persistence_and_uncertain_no_retry(self):
        with tempfile.TemporaryDirectory(prefix='pb-private-intent-test-') as directory:
            # Only a disposable child directory's ACL is modified.
            env = dict(os.environ, PB_WINDOWS_TEST_DIR=directory)
            script = Path(directory) / 'acl_setup.ps1'
            script.write_text(WINDOWS_PRIVATE_ACL, encoding='utf-8')
            setup = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive',
                 '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=20, check=False)
            script.unlink(missing_ok=True)
            self.assertEqual(setup.returncode, 0, 'PRIVATE_SYNTHETIC_ACL_SETUP_FAILED')
            db = Path(directory) / 'private' / 'intents.sqlite3'
            self.assertFalse(db.exists())

            with IntentStore.create(db, store_id=STORE_ID) as store:
                initial = store.prepare(synthetic_ticket(), **CONTEXT)
                self.assertEqual(initial.state, 'PREPARED')
                attempted = store.claim(735, initial.digest, **CONTEXT)
                self.assertEqual(attempted.state, 'ATTEMPTED')
                uncertain = store.record_result(735, initial.digest, 'UNKNOWN', 'f' * 64)
                self.assertEqual(uncertain.state, 'UNKNOWN')

            with IntentStore(db, expected_store_id=STORE_ID) as store:
                self.assertEqual(store.load(735).state, 'UNKNOWN')
                with self.assertRaisesRegex(StoreDenied, 'INTENT_ALREADY_ATTEMPTED_NO_RETRY'):
                    store.claim(735, initial.digest, **CONTEXT)
                enrolled = store.record_result(735, initial.digest, 'ENROLLED', '1' * 64)
                self.assertEqual(enrolled.state, 'ENROLLED')
                self.assertEqual(store.revoke(735, initial.digest, 'OWNER_REVOKED').state,
                                 'REVOKED')

            with IntentStore(db, expected_store_id=STORE_ID) as store:
                self.assertEqual(store.load(735).state, 'REVOKED')
                self.assertEqual(store.event_count(), 5)
                provider_reads = []
                result = __import__(
                    'verification.native_intent_store', fromlist=['verify_recorded_approval']
                ).verify_recorded_approval(
                    lambda path: provider_reads.append(path),
                    store, pr_number=735, **CONTEXT)
                self.assertEqual(result.status, 'HOLD')
                self.assertEqual(provider_reads, [])
                self.assertEqual(result.provider_writes, 0)


if __name__ == '__main__':
    unittest.main()
