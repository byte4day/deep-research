#!/usr/bin/env python3
"""Tests for research.py against a local HTTP server (no internet)."""
from __future__ import annotations

import http.server
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "deep-research" / "scripts" / "research.py"
spec = importlib.util.spec_from_file_location("research", SCRIPT)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

PAGES = {
    "/docs": "<html><head><style>.x{}</style><script>var hidden='secret words';</script></head><body>"
             "<h1>Streams</h1><p>Consumer groups keep&nbsp;their state <b>on the server</b>, &ldquo;always&rdquo;.</p></body></html>",
    "/blog": "<html><body><p>We measured 40% lower latency in our test.</p></body></html>",
    "/pdf": "%PDF-1.7 binary",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/gone":
            self.send_error(404)
        elif self.path == "/wall":
            self.send_error(403)
        elif self.path in PAGES:
            body = PAGES[self.path].encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf" if self.path == "/pdf" else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(500)

    def log_message(self, *args):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "run"

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = R.main([str(a) for a in args])
            except SystemExit as exc:  # argparse
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def start(self):
        self.assertEqual(self.cli("init", self.run_dir, "-q", "Which queue?")[0], 0)

    def ledger(self):
        return json.loads((self.run_dir / "ledger.json").read_text())


class LedgerTests(Base):
    def test_init_creates_ledger_and_report_and_refuses_to_overwrite(self):
        self.start()
        self.assertIn("# Which queue?", (self.run_dir / "report.md").read_text())
        code, _, err = self.cli("init", self.run_dir, "-q", "Other")
        self.assertEqual(code, 2)
        self.assertIn("already exists", err)
        self.assertEqual(self.ledger()["question"], "Which queue?")

    def test_commands_without_a_ledger_fail_cleanly(self):
        for cmd in (["status"], ["check"], ["sources"], ["lint"], ["claim", "DIR", "x"]):
            args = [cmd[0], self.run_dir, *cmd[2:]] if len(cmd) > 1 else [cmd[0], self.run_dir]
            code, _, err = self.cli(*args)
            self.assertEqual(code, 2, cmd)
            self.assertIn("no ledger", err)

    def test_claim_ids_and_duplicates(self):
        self.start()
        self.assertEqual(self.cli("claim", self.run_dir, "State lives on the server")[1].strip(), "C1")
        self.assertEqual(self.cli("claim", self.run_dir, "Latency drops 40%")[1].strip(), "C2")
        self.assertEqual(self.cli("claim", self.run_dir, "  state lives on the SERVER ")[1].strip(), "C1")
        self.assertEqual(len(self.ledger()["claims"]), 2)

    def test_add_validates_input(self):
        self.start()
        self.cli("claim", self.run_dir, "x")
        bad = [
            (["--url", "example.com/page"], "full http"),
            (["--url", "https://a.com", "--supports", "C9"], "unknown claim"),
            (["--url", "https://a.com", "--date", "May 2026"], "--date"),
            (["--url", "https://a.com", "--supports", "C1", "--contradicts", "c1"], "both support and contradict"),
        ]
        for args, needle in bad:
            code, _, err = self.cli("add", self.run_dir, *args)
            self.assertEqual(code, 2, args)
            self.assertIn(needle, err)
        self.assertEqual(self.ledger()["sources"], [])

    def test_same_url_merges_instead_of_duplicating(self):
        self.start()
        self.cli("claim", self.run_dir, "a")
        self.cli("claim", self.run_dir, "b")
        self.assertEqual(self.cli("add", self.run_dir, "--url", "https://A.com/x/?utm_source=t", "--supports", "c1")[1].strip(), "S1")
        code, out, _ = self.cli("add", self.run_dir, "--url", "https://a.com/x", "--supports", "C2", "--title", "T")
        self.assertIn("S1", out)
        src = self.ledger()["sources"]
        self.assertEqual(len(src), 1)
        self.assertEqual(src[0]["supports"], ["C1", "C2"])
        self.assertEqual(src[0]["title"], "T")


class VerdictTests(Base):
    def test_verdict_rules(self):
        self.start()
        for text in ("primary one", "two sites", "one blog", "nothing", "disputed", "same site twice"):
            self.cli("claim", self.run_dir, text)
        add = lambda *a: self.cli("add", self.run_dir, *a)  # noqa: E731
        add("--url", "https://docs.vendor.com/a", "--kind", "primary", "--supports", "C1")
        add("--url", "https://news.one.com/a", "--supports", "C2,C3,C5")
        add("--url", "https://www.two.org/a", "--supports", "C2")
        add("--url", "https://three.net/a", "--contradicts", "C5")
        add("--url", "https://blog.same.co.uk/a", "--supports", "C6")
        add("--url", "https://docs.same.co.uk/b", "--supports", "C6")
        got = {v["id"]: v["verdict"] for v in R.verdicts(self.ledger())}
        self.assertEqual(got, {"C1": "confirmed", "C2": "confirmed", "C3": "single-source",
                               "C4": "unsupported", "C5": "contested", "C6": "single-source"})

    def test_site_of(self):
        self.assertEqual(R.site_of("https://www.docs.example.com/x"), "example.com")
        self.assertEqual(R.site_of("https://a.b.bbc.co.uk/x"), "bbc.co.uk")


class CheckTests(Base):
    def test_check_finds_quotes_dead_links_and_fabricated_quotes(self):
        self.start()
        self.cli("claim", self.run_dir, "State lives on the server")
        self.cli("claim", self.run_dir, "Latency drops 40%")
        add = lambda *a: self.cli("add", self.run_dir, *a)  # noqa: E731
        add("--url", f"{self.base}/docs", "--kind", "primary", "--date", "2026-10-01", "--supports", "C1",
            "--quote", 'keep their state on the server, "always"')
        add("--url", f"{self.base}/blog", "--date", "2026-09-01", "--supports", "C2", "--quote", "we measured 90% lower latency")
        add("--url", f"{self.base}/gone", "--date", "2026-09-01", "--supports", "C2", "--quote", "anything")
        add("--url", f"{self.base}/wall", "--date", "2026-09-01", "--supports", "C2", "--quote", "anything")
        add("--url", f"{self.base}/pdf", "--date", "2020-01-01", "--supports", "C1", "--quote", "in the pdf")
        code, out, _ = self.cli("check", self.run_dir)
        self.assertEqual(code, 1)
        checks = {s["id"]: s["check"] for s in self.ledger()["sources"]}
        self.assertEqual((checks["S1"]["status"], checks["S1"]["quote"]), ("ok", "found"))
        self.assertEqual(checks["S2"]["quote"], "missing")
        self.assertEqual(checks["S3"]["status"], "dead")
        self.assertEqual((checks["S4"]["status"], checks["S4"]["quote"]), ("blocked", "unchecked"))
        self.assertEqual((checks["S5"]["status"], checks["S5"]["quote"]), ("ok", "unchecked"))
        self.assertIn("PROBLEM  dead link: S3", out)
        self.assertIn("PROBLEM  quote not on the page: S2", out)
        self.assertIn("blocked (403)", out)
        self.assertIn("older than 18 months (2020-01-01)", out)
        self.assertNotIn("PROBLEM  quote not on the page: S1", out)
        # offline re-check uses the saved results and reports the same problems
        code, out2, _ = self.cli("check", self.run_dir, "--offline")
        self.assertEqual(code, 1)
        self.assertIn("dead link: S3", out2)

    def test_text_inside_script_tags_is_not_a_quote_match(self):
        self.start()
        self.cli("claim", self.run_dir, "x")
        self.cli("add", self.run_dir, "--url", f"{self.base}/docs", "--kind", "primary", "--date", "2026-10-01",
                 "--supports", "C1", "--quote", "secret words")
        self.cli("check", self.run_dir)
        self.assertEqual(self.ledger()["sources"][0]["check"]["quote"], "missing")

    def test_dead_source_no_longer_supports_its_claim(self):
        self.start()
        self.cli("claim", self.run_dir, "x")
        self.cli("add", self.run_dir, "--url", f"{self.base}/gone", "--kind", "primary", "--supports", "C1")
        self.assertEqual(R.verdicts(self.ledger())[0]["verdict"], "confirmed")
        code, out, _ = self.cli("check", self.run_dir)
        self.assertEqual(code, 1)
        self.assertIn("unsupported: C1", out)

    def test_clean_run_exits_zero(self):
        self.start()
        self.cli("claim", self.run_dir, "State lives on the server")
        self.cli("add", self.run_dir, "--url", f"{self.base}/docs", "--kind", "primary", "--date", R.today(),
                 "--supports", "C1", "--quote", "Consumer groups keep their state on the server")
        code, out, _ = self.cli("check", self.run_dir)
        self.assertEqual(code, 0, out)
        self.assertIn("clean", out)

    def test_check_with_no_sources(self):
        self.start()
        self.assertEqual(self.cli("check", self.run_dir)[0], 1)

    def test_non_web_url_is_skipped_not_fetched(self):
        self.assertEqual(R.fetch("file:///etc/passwd", 1)["status"], "skipped")


class ReportTests(Base):
    def seed(self):
        self.start()
        self.cli("claim", self.run_dir, "a")
        self.cli("add", self.run_dir, "--url", "https://a.com/1", "--title", "Alpha", "--publisher", "A Corp",
                 "--date", "2026-05", "--kind", "primary", "--supports", "C1")
        self.cli("add", self.run_dir, "--url", "https://b.com/2", "--supports", "C1")

    def test_sources_block(self):
        self.seed()
        out = self.cli("sources", self.run_dir)[1].splitlines()
        self.assertTrue(out[0].startswith("1. Alpha — A Corp, 2026-05. https://a.com/1 (primary; accessed "))
        self.assertTrue(out[1].startswith("2. https://b.com/2. https://b.com/2 (secondary"))

    def test_lint_flags_placeholders_unknown_citations_and_bare_figures(self):
        self.seed()
        code, out, _ = self.cli("lint", self.run_dir)
        self.assertEqual(code, 1)
        self.assertIn("template placeholders", out)
        report = self.run_dir / "report.md"
        report.write_text("# Q\n\n## Answer\n\nUse Alpha [1]. It is 40% faster. Beta agrees [1, 7].\n\n"
                          "```\nport 8080\n```\n\n## Sources\n\n1. Alpha 2026\n9. ghost\n")
        code, out, _ = self.cli("lint", self.run_dir)
        self.assertEqual(code, 1)
        self.assertIn("citation [7] has no source", out)
        self.assertNotIn("citation [9]", out)
        self.assertIn("source 2 is never cited", out)
        self.assertIn('a figure without a citation: "It is 40% faster."', out)
        self.assertNotIn("8080", out)

    def test_lint_passes_a_cited_report(self):
        self.seed()
        (self.run_dir / "report.md").write_text("# Q\n\nAlpha is 40% faster [1], and Beta confirms it [2].\n\n## Sources\n\n1. a\n2. b\n")
        code, out, _ = self.cli("lint", self.run_dir)
        self.assertEqual(code, 0, out)
        self.assertIn("0 problems, 0 warnings", out)

    def test_citation_ranges(self):
        self.assertEqual(R._cited("see [1-3] and [5, 7]"), {1, 2, 3, 5, 7})


if __name__ == "__main__":
    unittest.main()
