# Sources: ranking, where to look, query craft

## Ranking

| Kind | What counts | Trust |
|---|---|---|
| `primary` | The origin of the fact: official documentation, a standard or RFC, the paper itself, source code, a changelog or release note, a regulator filing, a court record, a dataset, a company's own pricing page | Highest. One is enough to confirm a claim about that thing. |
| `secondary` | Reporting and analysis: news, engineering blogs, reviews, textbooks, encyclopedias | Good for context and comparison. Needs a second site, or the primary it cites. |
| `community` | Forums, issue threads, social posts, comment sections, video transcripts | Real-world experience and early warnings. Never the only support for a factual claim. |

A vendor is a primary source for what its product does and costs, and a biased source for how it compares with competitors.

When a secondary source cites a primary one, follow the link and cite the primary.

## Where to look

| Question | Start with |
|---|---|
| How an API, SDK or tool behaves | Official docs for the exact version, the changelog, then the source code and its tests |
| Is a bug or limitation real | The project's issue tracker, release notes, then forum threads |
| Which option to choose | Each option's own docs for facts; independent benchmarks and postmortems for trade-offs |
| A statistic or market figure | The original report or dataset, not the article quoting it; note the year and the method |
| Science or medicine | The paper (abstract is not enough for a strong claim), systematic reviews, then guidelines |
| Law, policy, compliance | The text of the law or rule, the regulator's guidance, then commentary |
| A company or person | Their own site and filings, then reporting; say when a fact could not be verified |
| What practitioners think | Forum and social threads, read as opinion and counted as `community` |

## Query craft

- Write three phrasings per sub-question: the plain question, the terms an expert would use, and the failure case ("X problems", "X vs Y", "X deprecated").
- Add the year or version for anything that changes.
- Search for the exact error text or the exact phrase in quotes.
- Restrict to a site when you know where the truth lives (`site:` the docs or the repository).
- For a contested claim, search for its negation and for "criticism" or "limitations".
- When results are thin, broaden the term; when they are noisy, add the domain word.

## Reading

- Check the date and the version before the content.
- Find the sentence that states the fact and copy it exactly for `--quote`. If no sentence states it, the page does not support the claim.
- A number needs its unit, its date and how it was measured.
- Note what the author gains from the claim.

## When to stop

Stop when each claim the answer rests on is `confirmed`, a fresh search for the opposite finds nothing new, and new sources repeat what you already have. If the budget runs out first, stop anyway and list what is still open.
