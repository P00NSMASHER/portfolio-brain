"""Run standalone protocol's pure Node.js tests as part of Foundation CI.

No npm install, Express server, outside network, payment or runtime secret needed.
The standalone product remains a non-deployed review-only code artifact.
"""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "agent-data-tools-standalone"
PROTOCOL = SERVICE / "test" / "protocol-security.test.mjs"
SOURCES = tuple(sorted((SERVICE / "src").glob("*.mjs")))


class StandaloneX402ProtocolTests(unittest.TestCase):
    def node(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js >=20 required to test the standalone seller")
        return node

    def test_reviewed_protocol_sources_syntax_without_network(self):
        self.assertEqual(len(SOURCES), 3, "standalone source inventory changed")
        for source in (*SOURCES, PROTOCOL):
            with self.subTest(path=str(source.relative_to(ROOT))):
                result = subprocess.run(
                    [self.node(), "--check", str(source)],
                    cwd=ROOT, capture_output=True, text=True, timeout=20,
                    check=False,
                )
                self.assertEqual(result.returncode, 0,
                                 "Node syntax invalid: " + source.name + "\n"
                                 + result.stderr[:1200])

    def test_mocked_payment_origin_and_settlement_regressions(self):
        self.assertTrue(PROTOCOL.is_file(), "reviewed protocol test missing")
        result = subprocess.run(
            [self.node(), "--test", "--test-concurrency=1",
             str(PROTOCOL.relative_to(SERVICE))],
            cwd=SERVICE, capture_output=True, text=True,
            timeout=40, check=False,
        )
        self.assertEqual(result.returncode, 0,
                         "Offline x402 protocol regressions failed:\n"
                         + result.stdout[-3500:] + "\n" + result.stderr[-1500:])
        self.assertIn("# fail 0", result.stdout)
        self.assertIn("# pass 9", result.stdout)

    def test_review_only_code_does_not_activate_existing_hosting(self):
        self.assertTrue((SERVICE / "package.json").is_file())
        self.assertFalse(
            (ROOT / ".github/workflows/agent-data-tools-standalone.yml").exists(),
            "unreviewed standalone Actions workflow would activate",
        )
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("x402-render-gateway", render)
        self.assertNotIn("agent-data-tools-standalone", render)
        self.assertTrue((ROOT / ".github/workflows/reliability-day.yml").is_file())
        observer = (ROOT / ".github/workflows/reliability-day.yml").read_text()
        receipt = (ROOT / ".github/workflows/portfolio-source-acceptance-producer.yml").read_text()
        self.assertIn("      false &&", observer)
        self.assertIn("        false &&", receipt)

    def test_live_upstream_checks_are_opt_in_and_not_in_ci(self):
        manifest = (SERVICE / "package.json").read_text(encoding="utf-8")
        self.assertIn('"test:upstreams"', manifest)
        self.assertIn("test/contracts.test.mjs", manifest)
        self.assertNotIn("test/upstream-smoke.test.mjs\"\n  }", manifest)
        ci = (ROOT / ".github/workflows/foundation-ci.yml").read_text()
        self.assertNotIn("npm run test:upstreams", ci)


if __name__ == "__main__":
    unittest.main()
