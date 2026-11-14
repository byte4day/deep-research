#!/usr/bin/env python3
"""deep-research ledger: track claims and sources, then check them before you write.

A research run is a folder holding ``ledger.json`` (claims + sources) and ``report.md``.

    research.py init  DIR -q "Which queue should we use for X?"
    research.py claim DIR "Redis Streams keeps consumer-group state on the server"     -> C1
    research.py add   DIR --url URL --title T --kind primary --date 2026-05-01 \
                          --quote "exact words from the page" --supports C1
    research.py check DIR            # fetch every source: dead links, missing quotes, weak claims
    research.py status DIR           # claims with a verdict each
    research.py sources DIR          # numbered "Sources" block for the report
    research.py lint  DIR            # report.md: every [n] resolves, numbers carry a citation

Verdicts: confirmed (one primary source, or two sources on different sites),
single-source, unsupported, contested (a source contradicts it).

Standard library only. Exit codes: 0 clean, 1 problems found, 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = "1.0.0"
KINDS = ("primary", "secondary", "community")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) deep-research-check/" + VERSION
MAX_BYTES = 3_000_000
STALE_DAYS = 548  # 18 months

REPORT_TEMPLATE = """# {question}

_Researched {today}. Sources checked with `research.py check`._

## Answer

<The answer in 2 to 5 sentences. Lead with the recommendation or the finding.>

## Findings

<One short paragraph or bullet per finding. Each factual sentence ends with its source, e.g. [1].
Say how sure you are: high, medium or low, and why.>

## What is not known

<Claims you could not confirm, sources that disagree, and what would settle it.>

## Sources

<Paste the output of `research.py sources DIR` here.>
"""


class Problem(Exception):
    """A usage error: printed without a traceback, exit code 2."""


# ---------------------------------------------------------------- storage

def ledger_path(run: Path) -> Path:
    return run / "ledger.json"


def load(run: Path) -> dict:
    path = ledger_path(run)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Problem(f"no ledger in {run}. Start with: research.py init {run} -q \"<question>\"") from None
    except ValueError as exc:
        raise Problem(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or "sources" not in data or "claims" not in data:
        raise Problem(f"{path} is not a deep-research ledger")
    return data


def save(run: Path, data: dict) -> None:
    run.mkdir(parents=True, exist_ok=True)
    tmp = run / f"ledger.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, ledger_path(run))


def today() -> str:
    return dt.date.today().isoformat()


def next_id(rows: list[dict], prefix: str) -> str:
    nums = [int(r["id"][1:]) for r in rows if re.fullmatch(rf"{prefix}\d+", str(r.get("id", "")))]
    return f"{prefix}{max(nums, default=0) + 1}"


def split_ids(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in re.split(r"[,\s]+", value):
            part = part.strip().upper()
            if part and part not in out:
                out.append(part)
    return out


# ---------------------------------------------------------------- text + fetch

def normalize(text: str) -> str:
    """Lowercase letters and digits separated by single spaces, so quotes survive markup and typography."""
    text = html.unescape(text).casefold()
    return re.sub(r"[^a-z0-9À-ɏЀ-ӿ؀-ۿ一-鿿]+", " ", text).strip()


def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1\s*>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    return re.sub(r"(?s)<[^>]+>", " ", raw)


def site_of(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    parts = host.split(".")
    # Good enough to tell two sites apart without a public-suffix list.
    if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "ac", "gov", "edu", "net"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def canonical_url(url: str) -> str:
    u = urllib.parse.urlsplit(url.strip())
    query = "&".join(p for p in u.query.split("&") if p and not re.match(r"(utm_[a-z]+|fbclid|gclid|ref)=", p))
    return urllib.parse.urlunsplit((u.scheme.lower(), (u.netloc or "").lower(), u.path.rstrip("/"), query, ""))


def fetch(url: str, timeout: float) -> dict:
    """Return {status, http, text}. status: ok | blocked | dead | error | skipped."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        return {"status": "skipped", "http": None, "text": "", "detail": f"not a web URL ({scheme or 'no scheme'})"}
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked above
            ctype = (resp.headers.get("Content-Type") or "").lower()
            body = resp.read(MAX_BYTES)
            code = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 405, 406, 429, 451) or 520 <= exc.code <= 530:
            return {"status": "blocked", "http": exc.code, "text": "", "detail": "site refused an automated request"}
        if exc.code in (404, 410):
            return {"status": "dead", "http": exc.code, "text": "", "detail": "page not found"}
        return {"status": "error", "http": exc.code, "text": "", "detail": f"HTTP {exc.code}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        dead = "Name or service not known" in str(reason) or "nodename nor servname" in str(reason) \
            or "No address associated" in str(reason)
        return {"status": "dead" if dead else "error", "http": None, "text": "",
                "detail": "domain does not resolve" if dead else str(reason)[:120]}
    if "pdf" in ctype or body[:5] == b"%PDF-":
        return {"status": "ok", "http": code, "text": "", "detail": "pdf: quote not checked"}
    charset = re.search(r"charset=([\w-]+)", ctype)
    try:
        raw = body.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        raw = body.decode("utf-8", errors="replace")
    return {"status": "ok", "http": code, "text": page_text(raw), "detail": ""}


def check_source(src: dict, timeout: float) -> dict:
    got = fetch(src["url"], timeout)
    quote = (src.get("quote") or "").strip()
    if not quote:
        quote_state = "none"
    elif got["status"] != "ok" or not got["text"]:
        quote_state = "unchecked"
    else:
        quote_state = "found" if normalize(quote) in normalize(got["text"]) else "missing"
    return {"status": got["status"], "http": got["http"], "detail": got.get("detail", ""),
            "quote": quote_state, "checked": today()}


# ---------------------------------------------------------------- verdicts

def verdicts(data: dict) -> list[dict]:
    rows = []
    for claim in data["claims"]:
        cid = claim["id"]
        live = [s for s in data["sources"] if (s.get("check") or {}).get("status") != "dead"]
        support = [s for s in live if cid in s.get("supports", [])]
        against = [s for s in live if cid in s.get("contradicts", [])]
        sites = {site_of(s["url"]) for s in support}
        if against and support:
            verdict = "contested"
        elif against:
            verdict = "contradicted"
        elif not support:
            verdict = "unsupported"
        elif any(s.get("kind") == "primary" for s in support) or len(sites) >= 2:
            verdict = "confirmed"
        else:
            verdict = "single-source"
        rows.append({"id": cid, "text": claim["text"], "verdict": verdict,
                     "supports": [s["id"] for s in support], "contradicts": [s["id"] for s in against]})
    return rows


# ---------------------------------------------------------------- commands

def cmd_init(args: argparse.Namespace) -> int:
    run = args.dir
    if ledger_path(run).exists() and not args.force:
        raise Problem(f"{ledger_path(run)} already exists (pass --force to start over)")
    question = " ".join(args.question.split())
    if not question:
        raise Problem("the question is empty")
    save(run, {"version": VERSION, "question": question, "created": today(), "claims": [], "sources": []})
    report = run / "report.md"
    if not report.exists():
        report.write_text(REPORT_TEMPLATE.format(question=question, today=today()), encoding="utf-8")
    print(f"research run ready: {run}\n  ledger: {ledger_path(run)}\n  report: {report}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    data = load(args.dir)
    text = " ".join(args.text.split())
    if not text:
        raise Problem("the claim is empty")
    for claim in data["claims"]:
        if normalize(claim["text"]) == normalize(text):
            print(claim["id"])
            return 0
    cid = next_id(data["claims"], "C")
    data["claims"].append({"id": cid, "text": text, "added": today()})
    save(args.dir, data)
    print(cid)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    data = load(args.dir)
    url = args.url.strip()
    if not re.match(r"^https?://[^\s/]+", url, re.I):
        raise Problem(f"--url must be a full http(s) URL, got: {url}")
    if args.date and not re.fullmatch(r"\d{4}(-\d\d(-\d\d)?)?", args.date):
        raise Problem("--date must look like 2026, 2026-05 or 2026-05-01")
    supports, contradicts = split_ids(args.supports), split_ids(args.contradicts)
    known = {c["id"] for c in data["claims"]}
    unknown = [c for c in supports + contradicts if c not in known]
    if unknown:
        raise Problem(f"unknown claim id(s): {', '.join(unknown)}. Add them first with: research.py claim DIR \"...\"")
    both = set(supports) & set(contradicts)
    if both:
        raise Problem(f"a source cannot both support and contradict {', '.join(sorted(both))}")
    existing = next((s for s in data["sources"] if canonical_url(s["url"]) == canonical_url(url)), None)
    if existing:
        # Same page cited again: merge instead of creating a second number for it.
        for key, new in (("supports", supports), ("contradicts", contradicts)):
            existing[key] = sorted(set(existing.get(key, [])) | set(new), key=lambda c: int(c[1:]))
        for key in ("title", "publisher", "date", "quote", "note"):
            if getattr(args, key) and not existing.get(key):
                existing[key] = getattr(args, key).strip()
        save(args.dir, data)
        print(f"{existing['id']} (already in the ledger; merged)")
        return 0
    sid = next_id(data["sources"], "S")
    data["sources"].append({
        "id": sid, "url": url, "title": (args.title or "").strip(), "publisher": (args.publisher or "").strip(),
        "date": args.date or "", "kind": args.kind, "quote": (args.quote or "").strip(),
        "note": (args.note or "").strip(), "supports": supports, "contradicts": contradicts, "accessed": today(),
    })
    save(args.dir, data)
    print(sid)
    return 0


def _age_days(date: str) -> int | None:
    m = re.fullmatch(r"(\d{4})(?:-(\d\d))?(?:-(\d\d))?", date or "")
    if not m:
        return None
    try:
        d = dt.date(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1))
    except ValueError:
        return None
    return (dt.date.today() - d).days


def cmd_check(args: argparse.Namespace) -> int:
    data = load(args.dir)
    sources = data["sources"]
    if not sources:
        print("no sources yet. Add one with: research.py add DIR --url URL --supports C1")
        return 1
    if not args.offline:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for src, result in zip(sources, pool.map(lambda s: check_source(s, args.timeout), sources)):
                src["check"] = result
        save(args.dir, data)
    problems: list[str] = []
    warnings: list[str] = []
    for s in sources:
        chk = s.get("check") or {}
        label = f"{s['id']} {s['url']}"
        if chk.get("status") == "dead":
            problems.append(f"dead link: {label} ({chk.get('detail')})")
        elif chk.get("status") == "error":
            warnings.append(f"could not fetch: {label} ({chk.get('detail')})")
        elif chk.get("status") == "blocked":
            warnings.append(f"blocked ({chk.get('http')}), open it by hand: {label}")
        if chk.get("quote") == "missing":
            problems.append(f"quote not on the page: {label}\n      quote: \"{s['quote'][:110]}\"")
        elif chk.get("quote") == "unchecked" and chk.get("status") == "ok":
            warnings.append(f"quote not checked ({chk.get('detail') or 'no text'}): {label}")
        if not s.get("quote"):
            warnings.append(f"no quote recorded: {label}")
        if not s.get("date"):
            warnings.append(f"no publication date: {label}")
        elif (_age_days(s["date"]) or 0) > STALE_DAYS:
            warnings.append(f"older than 18 months ({s['date']}): {label}")
        if not s.get("supports") and not s.get("contradicts"):
            warnings.append(f"linked to no claim: {label}")
    rows = verdicts(data)
    for v in rows:
        if v["verdict"] in ("unsupported", "contradicted"):
            problems.append(f"{v['verdict']}: {v['id']} {v['text']}")
        elif v["verdict"] in ("single-source", "contested"):
            warnings.append(f"{v['verdict']}: {v['id']} {v['text']}")
    if args.json:
        print(json.dumps({"sources": sources, "claims": rows, "problems": problems, "warnings": warnings}, indent=2))
        return 1 if problems else 0
    ok = sum(1 for s in sources if (s.get("check") or {}).get("status") == "ok")
    found = sum(1 for s in sources if (s.get("check") or {}).get("quote") == "found")
    confirmed = sum(1 for v in rows if v["verdict"] == "confirmed")
    mode = " (offline: using the last saved fetch results)" if args.offline else ""
    print(f"{len(sources)} sources: {ok} reachable, {found} quotes found on the page{mode}")
    print(f"{len(rows)} claims: {confirmed} confirmed")
    for p in problems:
        print(f"  PROBLEM  {p}")
    for w in warnings:
        print(f"  warning  {w}")
    if not problems and not warnings:
        print("clean")
    return 1 if problems else 0


def cmd_status(args: argparse.Namespace) -> int:
    data = load(args.dir)
    rows = verdicts(data)
    if args.json:
        print(json.dumps({"question": data["question"], "claims": rows, "sources": len(data["sources"])}, indent=2))
        return 0
    print(f"Q: {data['question']}")
    print(f"{len(data['sources'])} sources, {len(rows)} claims")
    for v in rows:
        refs = ", ".join(v["supports"]) or "-"
        against = f"  against: {', '.join(v['contradicts'])}" if v["contradicts"] else ""
        print(f"  {v['id']:<4} {v['verdict']:<13} [{refs}]{against}  {v['text']}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    data = load(args.dir)
    for s in data["sources"]:
        n = s["id"][1:]
        title = s.get("title") or s["url"]
        meta = ", ".join(x for x in (s.get("publisher"), s.get("date")) if x)
        tail = f"{s.get('kind', 'secondary')}; accessed {s.get('accessed', '?')}"
        print(f"{n}. {title}{' — ' + meta if meta else ''}. {s['url']} ({tail})")
    return 0


CITE_RE = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
NUMBER_RE = re.compile(r"(\d[\d,.]*\s?%|[$€£]\s?\d|\b\d{2,}[\d,.]*\b)")


def _cited(text: str) -> set[int]:
    out: set[int] = set()
    for m in CITE_RE.finditer(text):
        for part in re.split(r"\s*,\s*", m.group(1)):
            span = re.split(r"\s*[–-]\s*", part)
            if len(span) == 2 and span[0].isdigit() and span[1].isdigit() and int(span[0]) <= int(span[1]) <= int(span[0]) + 50:
                out.update(range(int(span[0]), int(span[1]) + 1))
            else:
                out.update(int(x) for x in span if x.isdigit())
    return out


def cmd_lint(args: argparse.Namespace) -> int:
    data = load(args.dir)
    report = args.report or args.dir / "report.md"
    try:
        text = report.read_text(encoding="utf-8")
    except OSError as exc:
        raise Problem(f"cannot read {report}: {exc.strerror or exc}") from None
    known = {int(s["id"][1:]) for s in data["sources"]}
    body = re.split(r"(?im)^#{1,6}\s+(sources|references)\s*$", text)[0]
    body = re.sub(r"(?s)```.*?```", "", body)
    used = _cited(body)
    problems = [f"citation [{n}] has no source in the ledger" for n in sorted(used - known)]
    dead = {int(s["id"][1:]) for s in data["sources"] if (s.get("check") or {}).get("status") == "dead"}
    problems += [f"citation [{n}] points at a dead link" for n in sorted(used & dead)]
    warnings = [f"source {n} is never cited" for n in sorted(known - used)]
    if "<" in body and re.search(r"<(The answer|One short paragraph|Claims you could not|Paste the output)", body):
        problems.append("the report still contains template placeholders")
    for lineno, line in enumerate(body.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "_Researched", ">")):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z\[\"(])", stripped):
            plain = CITE_RE.sub("", re.sub(r"https?://\S+|`[^`]*`", "", sentence))
            if NUMBER_RE.search(plain) and not CITE_RE.search(sentence):
                warnings.append(f"line {lineno}: a figure without a citation: \"{sentence[:90]}\"")
    for p in problems:
        print(f"  PROBLEM  {p}")
    for w in warnings:
        print(f"  warning  {w}")
    print(f"{report}: {len(used)} sources cited, {len(problems)} problems, {len(warnings)} warnings")
    return 1 if problems else 0


# ---------------------------------------------------------------- cli

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="research.py", description="Claim and source ledger for deep research.")
    p.add_argument("--version", action="version", version=f"deep-research {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="start a research run folder")
    i.add_argument("dir", type=Path)
    i.add_argument("-q", "--question", required=True)
    i.add_argument("--force", action="store_true", help="replace an existing ledger")
    i.set_defaults(fn=cmd_init)

    c = sub.add_parser("claim", help="record a claim; prints its id (C1, C2, …)")
    c.add_argument("dir", type=Path)
    c.add_argument("text")
    c.set_defaults(fn=cmd_claim)

    a = sub.add_parser("add", help="record a source; prints its id (S1, S2, …)")
    a.add_argument("dir", type=Path)
    a.add_argument("--url", required=True)
    a.add_argument("--title")
    a.add_argument("--publisher")
    a.add_argument("--date", help="publication date: YYYY, YYYY-MM or YYYY-MM-DD")
    a.add_argument("--kind", choices=KINDS, default="secondary",
                   help="primary: the origin of the fact (official docs, paper, source code, filing, dataset). "
                        "secondary: reporting or analysis. community: forums, social posts.")
    a.add_argument("--quote", help="exact words from the page that back the claim")
    a.add_argument("--note")
    a.add_argument("--supports", action="append", metavar="C1[,C2]")
    a.add_argument("--contradicts", action="append", metavar="C3")
    a.set_defaults(fn=cmd_add)

    k = sub.add_parser("check", help="fetch every source: dead links, missing quotes, weak claims")
    k.add_argument("dir", type=Path)
    k.add_argument("--offline", action="store_true", help="do not fetch; judge from the saved results")
    k.add_argument("--timeout", type=float, default=15.0)
    k.add_argument("--json", action="store_true")
    k.set_defaults(fn=cmd_check)

    s = sub.add_parser("status", help="claims with their verdicts")
    s.add_argument("dir", type=Path)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    o = sub.add_parser("sources", help="numbered Sources block for the report")
    o.add_argument("dir", type=Path)
    o.set_defaults(fn=cmd_sources)

    lint = sub.add_parser("lint", help="check report.md citations against the ledger")
    lint.add_argument("dir", type=Path)
    lint.add_argument("report", type=Path, nargs="?")
    lint.set_defaults(fn=cmd_lint)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except Problem as exc:
        print(f"research: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
