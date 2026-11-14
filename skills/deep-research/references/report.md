# Report shape

`research.py init` writes this skeleton to `report.md`. Keep the order.

1. **Answer.** Two to five sentences. The recommendation or the finding comes first, then the main reason.
2. **Findings.** One short paragraph or bullet per finding. Each factual sentence ends with `[n]`, where n is the source number from `research.py sources`. Several sources: `[1, 4]`.
3. **What is not known.** Claims you could not confirm, sources that disagree and why, and what evidence would settle it.
4. **Sources.** The numbered block printed by `research.py sources <dir>`.

For a comparison, put a table in Findings: one row per option, one column per criterion, a citation in each cell that states a fact.

## Confidence wording

| Say | When |
|---|---|
| high confidence | A primary source states it, or several independent sources agree, and nothing contradicts it |
| medium confidence | One good secondary source, or sources agree but none is primary |
| low confidence | A single community source, an old source, or sources disagree |
| not known | Nothing checkable was found |

Mark your own reasoning as inference: "This suggests…" with no citation, never dressed as a sourced fact.

## Before sending

- `research.py check <dir>` shows no PROBLEM lines.
- `research.py lint <dir>` shows no PROBLEM lines.
- Every warning that touches the conclusion is either fixed or mentioned under "What is not known".
- Dates are absolute ("March 2026"), never "recently".
