"""Adversarial Cloudflare attestation verification; temporary test keys only."""
import base64
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from brain.cloudflare_clock import verify,CloudflareClockError

SHA="a"*40
WHEN=datetime(2026,10,8,6,50,0,tzinfo=timezone.utc)
def iso(dt):return dt.isoformat().replace("+00:00","Z")
def b64url(data):return base64.urlsafe_b64encode(data).decode().rstrip("=")

class SignedClock(unittest.TestCase):
    def setUp(self):
        if shutil.which("openssl") is None:self.skipTest("OpenSSL missing")
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d=Path(self.tmp.name)
        self.private=d/"private.pem"
        self.public=d/"public.pem"
        self.payload=d/"payload.json"
        self.sig=d/"sig.der"
        subprocess.run(["openssl","ecparam","-name","prime256v1","-genkey","-noout","-out",str(self.private)],check=True,capture_output=True)
        subprocess.run(["openssl","pkey","-in",str(self.private),"-pubout","-out",str(self.public)],check=True,capture_output=True)
        self.doc={"kind":"cloudflare_cron_v1","worker":"portfolio-brain-recovery","cron":"*/10 * * * *",
                  "source_sha":SHA,"scheduled_at":iso(WHEN),
                  "issued_at":iso(WHEN+timedelta(seconds=20)),"slot":int(WHEN.timestamp()//600)}
    def inputs(self):
        self.payload.write_bytes(json.dumps(self.doc,separators=(",",":")).encode())
        subprocess.run(["openssl","dgst","-sha256","-sign",str(self.private),"-out",str(self.sig),str(self.payload)],check=True,capture_output=True)
        raw=self.sig.read_bytes()
        self.assertEqual(raw[0],0x30)
        i=2;self.assertEqual(raw[i],2);n=raw[i+1];i+=2
        r=raw[i:i+n];i+=n;self.assertEqual(raw[i],2);n=raw[i+1];i+=2
        s=raw[i:i+n]
        rawsig=r[-32:].rjust(32,b"\x00")+s[-32:].rjust(32,b"\x00")
        return b64url(self.payload.read_bytes()),b64url(rawsig)
    def test_valid_independent_signature_never_claims_soak_pass(self):
        a,b=self.inputs()
        result=verify(a,b,SHA,now=WHEN+timedelta(seconds=45),pubkey=self.public)
        self.assertTrue(result["signed_origin"])
        self.assertFalse(result["soak_pass"])
    def test_real_valid_signed_base64url_can_begin_with_hyphen(self):
        # Fully synthetic P-256 public key and fixed test attestation.
        # Signed offline with an ephemeral TEST key; no production signing key.
        # Exercises actual OpenSSL verification rather than a mocked signature.
        # Construct the exact signed bytes from the structured document.
        # Base64 string copying is unsafe for provenance fixtures: deleting
        # even one encoded 'a' changes the signed 40-hex source identity.
        fixture_doc = {
            "kind": "cloudflare_cron_v1",
            "worker": "portfolio-brain-recovery",
            "cron": "*/10 * * * *",
            "source_sha": SHA,
            "scheduled_at": "2026-10-09T09:30:19Z",
            "issued_at": "2026-10-09T09:30:20Z",
            "slot": 2985897,
        }
        fixture_envelope = b64url(json.dumps(
            fixture_doc, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8"))
        fixture_signature = (
            "-m3gqQFOzjL9K4CVUlKuVgW-c1qZ9trMrUJzIw2J-bOSrNwPn7yp"
            "e8o-ph7WL5gcRFm50zcOrnVLcGyMdzqE2A"
        )
        self.assertTrue(fixture_signature.startswith("-"))
        sample_pubkey = Path(self.tmp.name) / "test-only-public.pem"
        sample_pubkey.write_text(
            "-----BEGIN PUBLIC KEY-----\n"
            "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEc4EyboLDuEjJk1lbi3LJ9lLg30p+\n"
            "ZfGOLgKSBlrKeaY19PtJexOrFbkX5m9OGeGe88WYFs5QU77NsH3IpEcTDw==\n"
            "-----END PUBLIC KEY-----\n",
            encoding="ascii",
        )
        test_now = datetime(2026, 10, 9, 9, 30, 40, tzinfo=timezone.utc)
        trusted = verify(fixture_envelope, fixture_signature, SHA,
                         now=test_now, pubkey=sample_pubkey)
        self.assertEqual(trusted["status"], "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED")
        self.assertTrue(trusted["signed_origin"])
        self.assertFalse(trusted["soak_pass"])
        self.assertEqual(trusted["source_sha"], SHA)
        # A similarly shaped but tampered signature must still be rejected.
        tampered = fixture_signature[:2] + ("A" if fixture_signature[2] != "A" else "B") + fixture_signature[3:]
        with self.assertRaisesRegex(CloudflareClockError, "CLOCK_SIGNATURE_NOT_VERIFIED"):
            verify(fixture_envelope, tampered, SHA, now=test_now, pubkey=sample_pubkey)

        # Replay the ACTUAL workflow shell command locally, overriding only
        # its output destination to an isolated disposable test path. The
        # production PEM is different from our test key, so this must BLOCK
        # by signature or age, NOT by argparse misreading a leading '-'.
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/brain-cycle.yml"
        command = [line.strip() for line in workflow.read_text().splitlines()
                   if line.strip().startswith("python -m brain.cloudflare_clock --envelope ")]
        self.assertEqual(len(command), 1)
        self.assertIn('--signature="$CF_SIGNATURE"', command[0])
        self.assertNotIn('--signature "$CF_SIGNATURE"', command[0])
        output = Path(self.tmp.name) / "parsed-not-authorized.json"
        shell_line = command[0].replace("/tmp/brain/cloudflare-origin.json", str(output))
        env = dict(os.environ, CF_ENVELOPE=fixture_envelope,
                   CF_SIGNATURE=fixture_signature, BRAIN_SOURCE_SHA=SHA)
        executed = subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + shell_line],
            cwd=workflow.parents[2], env=env,
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(executed.returncode, 1)
        self.assertNotIn("expected one argument", executed.stderr)
        self.assertNotIn("unrecognized arguments", executed.stderr)
        result = json.loads(output.read_text())
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn(result["reason"], {"CLOCK_SIGNATURE_NOT_VERIFIED",
                                         "CLOCK_STALE_OR_FUTURE"})
        self.assertFalse(result["soak_pass"])

    def test_wrong_source_rejected(self):
        a,b=self.inputs()
        with self.assertRaisesRegex(CloudflareClockError,"CLOCK_SOURCE_MISMATCH"):
            verify(a,b,"b"*40,now=WHEN+timedelta(seconds=30),pubkey=self.public)
    def test_tampered_payload_invalid_signature(self):
        a,b=self.inputs()
        self.doc["slot"]+=1
        altered=b64url(json.dumps(self.doc,separators=(",",":")).encode())
        with self.assertRaises(CloudflareClockError):
            verify(altered,b,SHA,now=WHEN+timedelta(seconds=40),pubkey=self.public)
    def test_stale_or_future_rejected(self):
        a,b=self.inputs()
        for moment in (WHEN+timedelta(minutes=30), WHEN-timedelta(seconds=30)):
            with self.subTest(moment=moment),self.assertRaises(CloudflareClockError):
                verify(a,b,SHA,now=moment,pubkey=self.public)
    def test_real_cloudflare_cron_with_provider_seconds_accepted(self):
        # Production Cloudflare Cron logged scheduledTime at 13:10:19, not :10:00.
        # Signature, source, correct ten-minute minute/slot, and freshness still bind it.
        self.doc["scheduled_at"]=iso(WHEN+timedelta(seconds=19))
        self.doc["issued_at"]=iso(WHEN+timedelta(seconds=22))
        a,b=self.inputs()
        result=verify(a,b,SHA,now=WHEN+timedelta(seconds=40),pubkey=self.public)
        self.assertEqual(result["status"],"CLOUDFLARE_SIGNED_ORIGIN_VERIFIED")
        self.assertEqual(result["slot"],int(WHEN.timestamp()//600))
        self.assertFalse(result["soak_pass"])

    def test_nonzero_seconds_outside_cron_minute_rejected(self):
        self.doc["scheduled_at"]=iso(WHEN+timedelta(minutes=1,seconds=19))
        self.doc["issued_at"]=iso(WHEN+timedelta(minutes=1,seconds=22))
        a,b=self.inputs()
        with self.assertRaisesRegex(CloudflareClockError,"CLOCK_WRONG_MINUTE"):
            verify(a,b,SHA,now=WHEN+timedelta(minutes=1,seconds=40),pubkey=self.public)

    def test_wrong_schedule_rejected(self):
        self.doc["scheduled_at"]=iso(WHEN+timedelta(minutes=1))
        self.doc["issued_at"]=iso(WHEN+timedelta(minutes=1,seconds=10))
        a,b=self.inputs()
        with self.assertRaisesRegex(CloudflareClockError,"CLOCK_WRONG_MINUTE"):
            verify(a,b,SHA,now=WHEN+timedelta(minutes=2),pubkey=self.public)
    def test_fake_manual_clock_rejected(self):
        self.doc["kind"]="manual_probe"
        a,b=self.inputs()
        with self.assertRaisesRegex(CloudflareClockError,"CLOCK_IDENTITY_INVALID"):
            verify(a,b,SHA,now=WHEN+timedelta(seconds=40),pubkey=self.public)
    def test_wrong_public_key_rejected(self):
        a,b=self.inputs()
        self.public.write_text("wrong")
        with self.assertRaisesRegex(CloudflareClockError,"CLOCK_SIGNATURE_NOT_VERIFIED"):
            verify(a,b,SHA,now=WHEN+timedelta(seconds=30),pubkey=self.public)
    def test_noncanonical_or_oversize_base64_rejected(self):
        with self.assertRaisesRegex(CloudflareClockError,"CLOCK_BASE64_INVALID"):
            verify("!","!!!",SHA,now=WHEN,pubkey=self.public)

if __name__=="__main__":unittest.main()
