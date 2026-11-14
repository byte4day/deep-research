# deep-research

A research skill and agent for Claude Code, Cursor and Codex. It plans sub-questions, reads primary sources, and keeps a ledger of claims and sources. Before the answer is written, a script fetches every source again and checks that each link is alive and each quote is really on the page.

## Install

```bash
git clone https://github.com/byte4day/deep-research
cd deep-research
./install.sh            # or: ./install.sh claude | cursor | codex
```

Needs Python 3.11 or newer. No other dependencies.

## Use

Ask for research in plain words:

```
research which message queue fits a 3-person team, with sources
```

In Claude Code you can also start the agent directly: `claude --agent researcher`.

The agent writes its run to `research/<slug>/` (or `~/research/<slug>/` outside a project):

| File | What it holds |
|---|---|
| `ledger.json` | Claims, sources, quotes and the result of the last check |
| `report.md` | The cited answer |

## The ledger script

```bash
R="python3 $HOME/.agents/skills/deep-research/scripts/research.py"
$R init  research/queues -q "Which queue fits a 3-person team?"
$R claim research/queues "Redis Streams keeps consumer-group state on the server"     # prints C1
$R add   research/queues --url https://redis.io/docs/... --kind primary --date 2026-03 \
         --quote "exact words from the page" --supports C1                            # prints S1
$R check research/queues     # dead links, quotes not on the page, weak claims
$R status research/queues    # a verdict per claim
$R sources research/queues   # numbered Sources block
$R lint  research/queues     # report.md: citations resolve, figures are cited
```

| Verdict | Meaning |
|---|---|
| `confirmed` | One primary source, or two sources on different sites |
| `single-source` | One non-primary source |
| `contested` | A source contradicts it |
| `unsupported` | No live source backs it |

`check` exits 1 when it finds a dead link, a quote that is not on the page, or an unsupported claim. Sites that refuse automated requests are reported as `blocked`, so you can open them by hand.

## What is in the repo

| Path | Purpose |
|---|---|
| `skills/deep-research/SKILL.md` | The skill: rules, depth levels, workflow |
| `skills/deep-research/scripts/research.py` | The ledger script (standard library only) |
| `skills/deep-research/references/` | Source ranking, query craft, report shape |
| `agents/` | `researcher` agent for Claude Code, Cursor and Codex |
| `tests/` | `python3 tests/test_research.py` and `bash tests/test_install.sh` |

## Uninstall

```bash
./uninstall.sh
```

Research run folders are never deleted.

## License

MIT
