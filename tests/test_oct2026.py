#!/usr/bin/env python3
"""October 2026 page layout, fail-closed parsing, both real capture layouts,
hand-checked notice intervals, and the build's receipt/capture gates.
Run: python3 -m pytest -q tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "data" / "raw"
sys.path.insert(0, str(HERE.parent / "pipeline"))
import generate as G  # noqa: E402
import parser as P  # noqa: E402

POLICY = "<p>Anthropic notifies customers with active deployments for models with upcoming retirements, providing at least 60 days' notice before model retirement for publicly released models.</p>"
ANTHROPIC_OCT = POLICY + """
<table><thead><tr><th>API model name</th><th>Current state</th><th>Deprecated</th><th>Tentative retirement date</th></tr></thead><tbody>
<tr><td>claude-mythos-preview</td><td>Deprecated</td><td>June 9, 2026</td><td>To be announced</td></tr>
<tr><td>claude-sonnet-4-5-20250929</td><td>Deprecated</td><td>September 30, 2026</td><td>November 30, 2026</td></tr>
</tbody></table>
<h3 id="2026-09-30-claude-sonnet-4-5-model" class="group">2026-09-30: Claude Sonnet 4.5 model<span><button aria-label="Copy link"></button></span></h3>
<table><thead><tr><th>Retirement date</th><th>Deprecated model</th><th>Recommended replacement</th></tr></thead><tbody>
<tr><td>November 30, 2026</td><td><code>claude-sonnet-4-5-20250929</code></td><td><code>claude-sonnet-5-5</code></td></tr>
</tbody></table>
<h3 id="2024-09-04-claude-1-and-instant-models">2024-09-04: Claude 1 and Instant models</h3>
<table><thead><tr><th>Retirement date</th><th>Deprecated model</th><th>Recommended replacement</th></tr></thead><tbody>
<tr><td>November 6, 2024</td><td><code>claude-instant-1.2</code></td><td><code>claude-haiku-4-5-20251001</code></td></tr>
</tbody></table>
"""


def _by_id(records):
    return {r["model_id"]: r for r in records}


class TestOctoberLayout(unittest.TestCase):
    def test_deprecated_rows_and_h3_id_history(self):
        recs, policy = P.parse_anthropic(ANTHROPIC_OCT)
        by_id = _by_id(recs)
        s45 = by_id["claude-sonnet-4-5-20250929"]
        self.assertEqual((s45["status"], s45["announced"], s45["retirement"], s45["replacement"]),
                         ("deprecated", "2026-09-30", "2026-11-30", "claude-sonnet-5-5"))
        self.assertEqual(by_id["claude-mythos-preview"]["retirement"], None)
        self.assertEqual(by_id["claude-instant-1.2"]["announced"], "2024-09-04")
        self.assertEqual(policy["floors"][0]["min"], 60)

    def test_fails_closed(self):
        for html in (ANTHROPIC_OCT.replace("<td>Deprecated</td><td>June 9", "<td>Legacy</td><td>June 9"),
                     ANTHROPIC_OCT.replace("<th>Tentative retirement date</th>", "<th>Retires</th>"),
                     POLICY):
            with self.assertRaises(ValueError):
                P.parse_anthropic(html)


class TestRealCaptures(unittest.TestCase):
    def _latest(self, slug, stamp):
        return (RAW / f"{slug}-{stamp}.html").read_text(encoding="utf-8")

    def test_both_layouts_parse(self):
        for stamp in ("20260812T052706Z", "20261006T232323Z"):
            recs, policy = P.parse_anthropic(self._latest("anthropic", stamp))
            by_id = _by_id(recs)
            self.assertEqual(by_id["claude-3-opus-20240229"]["announced"], "2025-06-30", stamp)
            self.assertEqual(by_id["claude-instant-1.2"]["announced"], "2024-09-04", stamp)
            self.assertEqual(policy["floors"][0]["min"], 60)
            orecs, opolicy = P.parse_openai(self._latest("openai", stamp))
            self.assertEqual([f["class"] for f in opolicy["floors"]], ["ga", "specialized", "preview"])
            self.assertIn("gpt-4o-2024-05-13", _by_id(orecs))

    def test_hand_checked_intervals(self):
        """Expected values computed by hand from the dates on the 2026-10-06 pages."""
        a, ap = P.parse_anthropic(self._latest("anthropic", "20261006T232323Z"))
        o, op = P.parse_openai(self._latest("openai", "20261006T232323Z"))
        models = _by_id(G._compute_models(a + o, {"Anthropic": ap, "OpenAI": op}))
        s45 = models["claude-sonnet-4-5-20250929"]  # Sep 30 -> Nov 30, 2026
        self.assertEqual((s45["notice_days"], s45["primary_verdict"]), (61, "PASS"))
        cyber = models["gpt-5.4-cyber"]  # Sep 11 -> Oct 1, 2026
        self.assertEqual((cyber["notice_days"], cyber["primary_verdict"]), (20, "SHORT"))
        self.assertEqual(cyber["verdicts"]["preview"]["verdict"], "PASS")
        tts = models["tts-1"]  # Oct 1, 2026 -> Jan 6, 2027
        self.assertEqual((tts["notice_days"], tts["verdicts"]["ga"]["verdict"], tts["verdicts"]["specialized"]["verdict"]),
                         (97, "SHORT", "PASS"))
        self.assertEqual(models["claude-1.0"]["notice_days"], 63)  # Sep 4 -> Nov 6, 2024
        self.assertEqual(models["claude-mythos-preview"]["note"], "No retirement date published — notice interval not computable")


class TestBuildGates(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (G.RAW_DIR, G.PIN, G.OUT_PATH, sys.argv)
        G.RAW_DIR, G.PIN, G.OUT_PATH = self.tmp, self.tmp / "pin.json", self.tmp / "out.json"
        sys.argv = ["generate.py"]
        for slug in ("anthropic", "openai"):
            src = sorted(RAW.glob(f"{slug}-2026*.html"))[-1]
            (self.tmp / src.name).write_bytes(src.read_bytes())
            (self.tmp / src.with_suffix(".sha256").name).write_text(src.with_suffix(".sha256").read_text())

    def tearDown(self):
        G.RAW_DIR, G.PIN, G.OUT_PATH, sys.argv = self.saved

    def test_no_pin_stops_then_accepted_pin_builds(self):
        with self.assertRaises(RuntimeError):
            G.main()
        sys.argv = ["generate.py", "--accept-source-change"]
        G.main()
        sys.argv = ["generate.py"]
        G.main()
        self.assertEqual(json.loads(G.OUT_PATH.read_text())["as_of"], "2026-10-06")

    def test_receipt_mismatch_stops(self):
        receipt = sorted(self.tmp.glob("openai-*.sha256"))[-1]
        receipt.write_text("0" * 64 + "  x.html\n")
        sys.argv = ["generate.py", "--accept-source-change"]
        with self.assertRaises(RuntimeError):
            G.main()

    def test_newer_failed_capture_stops(self):
        (self.tmp / "anthropic-20991231T000000Z.failed").write_text("x")
        sys.argv = ["generate.py", "--accept-source-change"]
        with self.assertRaises(RuntimeError):
            G.main()

    def test_changed_statement_stops(self):
        sys.argv = ["generate.py", "--accept-source-change"]
        G.main()
        pin = json.loads(G.PIN.read_text())
        pin["openai"]["policy"]["floors"][0]["min"] = 12
        G.PIN.write_text(json.dumps(pin))
        sys.argv = ["generate.py"]
        with self.assertRaises(RuntimeError):
            G.main()


if __name__ == "__main__":
    unittest.main()
