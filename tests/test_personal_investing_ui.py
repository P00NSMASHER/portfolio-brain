"""Static browser/UX security checks for the local-only companion."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "personal_investing" / "dashboard.html"
EXAMPLE = ROOT / "personal_investing" / "examples" / "snapshot.synthetic.json"


class HTMLAudit(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.external = []
        self.scripts = []
        self._script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            if "src" in a:
                self.external.append(("script", a["src"]))
            self._script = True
        if tag in {"link", "iframe", "object", "embed"}:
            self.external.append((tag, a))
        if tag == "form" and a.get("action"):
            self.external.append((tag, a))

    def handle_data(self, data):
        if self._script:
            self.scripts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False


class PersonalDashboardPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = UI.read_text(encoding="utf-8")
        cls.parsed = HTMLAudit()
        cls.parsed.feed(cls.html)

    def test_ui_never_requires_or_loads_external_code(self):
        self.assertEqual(self.parsed.external, [])
        self.assertIn("connect-src 'none'", self.html)
        self.assertIn("object-src 'none'", self.html)
        self.assertIn("frame-src 'none'", self.html)
        self.assertIn('name="referrer" content="no-referrer"', self.html)

    def test_no_network_cookies_or_browser_persistence(self):
        js = "\n".join(self.parsed.scripts)
        for disallowed in ("fetch(", "XMLHttpRequest", "WebSocket",
                           "localStorage", "sessionStorage", "indexedDB",
                           "document.cookie", "serviceWorker",
                           "sendBeacon(", "navigator.geolocation",
                           "window.open("):
            with self.subTest(disallowed=disallowed):
                self.assertNotIn(disallowed, js)

    def test_synthetic_demo_and_manual_local_import(self):
        self.assertIn('id="inputFile"', self.html)
        self.assertIn('type="file"', self.html)
        self.assertIn('id="demo"', self.html)
        self.assertIn('id="clear"', self.html)
        self.assertIn('id="paperRun"', self.html)
        self.assertIn('id="runBacktest"', self.html)
        self.assertIn('data_kind:"SIMULATED"', self.html)
        self.assertIn("No order submitted", self.html)
        self.assertIn("No real fills or forecast", self.html)

    def test_user_strings_are_escaped_by_dom_text_content(self):
        js = "\n".join(self.parsed.scripts)
        self.assertIn("td.textContent", js)
        self.assertIn("span.textContent", js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("document.write(", js)

    def test_inline_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node executable unavailable; static checks still run")
        js = "\n".join(self.parsed.scripts)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dashboard.js"
            path.write_text(js, encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(path)], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, timeout=20
            )
            self.assertEqual(result.returncode, 0, result.stderr[:2000])

    def test_example_is_synthetic_and_cannot_contain_secrets(self):
        import json
        snap = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(snap["data_kind"], "SIMULATED")
        for key in ("token", "api_key", "account_id", "access_token",
                    "password", "username", "brokerage_account"):
            self.assertNotIn(key, snap)
        from personal_investing.engine import analyze
        self.assertFalse(analyze(snap)["execution_authority"])


if __name__ == "__main__":
    unittest.main()
