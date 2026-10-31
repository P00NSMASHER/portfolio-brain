"""Network-free interactive browser-flow emulation, executed with Node built-ins.

This tests the actual in-page JS, not a mock implementation of its math.
It cannot replace real mobile accessibility or browser automation QA.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InlineScript(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = True

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False


HARNESS = r"""
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "") {
    this.tag = tag; this.children = []; this.events = {};
    this.attrs = {}; this.textContent = ""; this.value = "";
    this.className = "";
  }
  appendChild(child) {
    this.children.push(child);
    if (this.tag === "select" && this.children.length === 1) {
      this.value = child.value;
    }
    return child;
  }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  set innerHTML(value) { throw Error("Unsafe HTML injection attempt"); }
}
const store = new Map();
const node = id => {
  if (!store.has(id)) store.set(id, new Element(id));
  return store.get(id);
};
let navigations = 0;
const mockDocument = {
  getElementById: node,
  createElement: tag => new Element(tag),
  createElementNS: (ns,tag) => new Element(tag)
};
class FileReader {
  readAsText(file) { this.result = file.text; this.onload(); }
}
const sandbox = {
  document: mockDocument, Date, Intl, Math, Number, Object,
  Array, String, Set, JSON, isNaN, Error,
  FileReader,
  location: {reload() {navigations++;}}
};
function click(id) {
  assert.equal(typeof node(id).events.click, "function", "missing click "+id);
  node(id).events.click({});
}
function importFile(value) {
  const text = JSON.stringify(value);
  node("inputFile").events.change({
    target: {files:[{text, size:text.length}], value:"imported-private-file"}
  });
}

const js = fs.readFileSync(process.argv[2], "utf8");
const synthetic = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
vm.runInNewContext(js, sandbox, {timeout:1000});
assert.equal(typeof node("demo").events.click, "function");
assert.equal(typeof node("inputFile").events.change, "function");
assert.equal(typeof node("paperRun").events.click, "function");
assert.equal(typeof node("runBacktest").events.click, "function");
assert.equal(typeof node("clear").events.click, "function");

click("demo");
assert.match(node("nav").textContent, /\$/);
assert.match(node("sourceKind").textContent, /SIMULATED/);
assert.equal(node("watchlistBody").children.length, 2);
assert.ok(node("historyChart").children.length >= 2);

node("paperSymbol").value="AAPL";
node("paperQty").value="2";
node("paperPrice").value="100";
click("paperRun");
assert.match(node("paperResult").textContent, /PAPER BUY 2 AAPL/);
assert.match(node("paperResult").textContent, /No order submitted/);
node("paperQty").value="-100";
click("paperRun");
assert.match(node("paperResult").textContent, /Blocked: Cannot paper-sell/);

node("backtestSymbol").value="SPY";
click("runBacktest");
assert.match(node("backtestResult").textContent, /Simulated end/);
assert.match(node("backtestResult").textContent, /No real fills or forecast/);

let count = 0;
for (let i=0; i<100; i++) {
  const current = JSON.parse(JSON.stringify(synthetic));
  current.cash_usd = String(500 + i * 250);
  current.positions[0].shares = String(1+(i%11));
  current.positions[1].shares = String(1+(i%7));
  current.watchlist[0].note = i===42
    ? "<img src=x onerror=alert(1)>" : "User research note "+i;
  importFile(current);
  assert.match(node("message").textContent, /Loaded SIMULATED snapshot/);
  assert.equal(node("holdingsBody").children.length, 2);
  assert.equal(node("watchlistBody").children.length, 2);
  assert.equal(node("watchlistBody").children[0].children[3].textContent,
               current.watchlist[0].note);
  node("paperSymbol").value="SPY";
  node("paperQty").value="0.1";
  node("paperPrice").value="100";
  click("paperRun");
  assert.match(node("paperResult").textContent, /No order submitted/);
  count++;
}

const invalid = JSON.parse(JSON.stringify(synthetic));
invalid.cash_usd = "-10";
importFile(invalid);
assert.match(node("message").textContent, /Snapshot rejected/);
click("clear");
assert.equal(navigations, 1);
click("paperRun");
assert.match(node("paperResult").textContent, /Blocked: Import a snapshot first/);
console.log("PASS: "+count+" synthetic import/overview/watchlist/paper UI flows, buy/sell, backtest, malicious note, invalid import, clear.");
"""


class LocalOnlyBrowserFlowTests(unittest.TestCase):
    def test_one_hundred_actual_javascript_dashboard_interactions(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node not available on this platform")
        page = InlineScript()
        page.feed((ROOT / "personal_investing" / "dashboard.html").read_text())
        self.assertEqual(len(page.scripts), 1)
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            javascript = temp / "app.js"
            harness = temp / "test.js"
            javascript.write_text(page.scripts[0], encoding="utf-8")
            harness.write_text(HARNESS, encoding="utf-8")
            fixture = ROOT / "personal_investing" / "examples" / "snapshot.synthetic.json"
            p = subprocess.run([node, str(harness), str(javascript), str(fixture)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, (p.stderr or p.stdout)[-5000:])
        self.assertIn("100 synthetic import/overview/watchlist/paper UI flows", p.stdout)


if __name__ == "__main__":
    unittest.main()
