# judge-bench

A benchmark of real Pokémon TCG rules questions — the kind judges ask each other
mid-tournament, with the answers those judges arrived at.

**Not a benchmark for evaluating LLM judges.** The judges here are people.

## Why this one is different

Most rules benchmarks go stale quietly. This one has a property that makes it
useful for longer: **the correct answers change on a published schedule.** Cards
with the "G" regulation mark left Standard on 10 April 2026. The Play! Pokémon
documents were revised on 1 September 2026. Every rotation and every quarterly
revision creates questions where last year's right answer is now wrong.

That makes it a test of currency, not just knowledge — which is exactly what a
model trained on a fixed corpus is worst at, and exactly what a judge at an event
needs.

## Where the questions come from

Real questions that judges asked each other, rewritten in English as standalone
questions in our own words. **No original wording is reproduced**, and the source
is not disclosed.

The answers are the conclusions those judges reached. `key_checked_by` records how
each key was checked — against the original conclusion, or against a dated
document — rather than implying a citation. Where no single conclusion was reached,
the question is marked `contested` and scored separately — a rules question judges
genuinely disagree about is a finding, not a defect.

## A quarter is held back

Publishing a benchmark feeds it into the next training cycle. Within a year a model
may score well on the public half from memory rather than reasoning. The private
half is what still measures anything then, and it can only be created now — you
cannot retroactively un-publish a question.

The split is a hash of the question id: stable across runs, unchanged when
questions are added, and impossible to move a question between halves by editing
its row. A test proves the last one.

## Five conditions

| | What it measures |
|---|---|
| `no-tools` | what the model already knows |
| `web-search` | what a judge gets from a chatbot today — the real competitor |
| `corpus-in-context` | the whole rules corpus pasted in, no retrieval |
| `api-direct` | retrieval alone, no model writing the answer |
| `mcp` | the model calling a rules tool and writing the answer from it |

`corpus-in-context` against `api-direct` says whether retrieval beats stuffing the
prompt. `api-direct` against `mcp` says what it costs to let a model write the prose.

## Running it

```bash
uv venv && uv pip install anthropic jsonschema
python3 bench/draft.py --sample 60                  # a stratified sample to read
python3 bench/draft.py --write work/drafted.jsonl   # route into public and private
python3 bench/run.py --limit 60 --dry-run
python3 bench/grade.py bench/results/<date>.jsonl
python3 bench/publish.py work/merged.jsonl --out dist/questions.jsonl
python3 bench/stale.py bench/questions.jsonl          # keys that may describe an old rule
```

`publish.py` strips `source_ref` and `date` — an opaque pointer into local
working files, and the exact day. Both stay in the working copy so a disputed answer
stays traceable locally. The month (`asked`) is published.

`stale.py` exists because TPCi rewrites the tournament handbooks every season and
three keys here were found describing rules that had since changed (who chooses
first in top cut, the end-of-round procedure, the overtime limit). Every tournament,
penalty, legality and deck-building key is compared with the revision dates in
`bench/handbook_revisions.json`: a key verified against an older revision is
`stale`; one never verified against a dated document and discussed before the
current revision is `asked before`. Verifying a key records
`key_checked_against`; a rule known to have changed records `rule_changed`.
Questions whose right answer depends on the date asked are marked `contested`
with `contested_reason: time-bound` and are not scored on a verdict.

## Do not aim for 100%

A perfect score means the benchmark is broken: either the questions were shaped
around what the system handles, or the hard cases were dropped. Judges disagree on
some rulings and the Penalty Guidelines give the head judge latitude.

The target is to beat the web-search condition by more than the confidence
interval, and to win clearly on questions whose answers changed after training
cut-offs. Scores are reported per category with Wilson intervals plus run-to-run
spread — a gap smaller than the spread is not a result.

Two things the grader does that most do not:

- **Refusals are counted separately from wrong answers.** A system that says "I do
  not know" failed safely; one that invents a section number did not. Averaging
  them hides the distinction this benchmark exists to measure.
- **Open questions are not scored on a verdict.** "What is the fix?" has no yes/no,
  and matching on a verdict of "open" is nearly free. They are scored on whether
  the answer contains the required facts, judged by a model that is checked against
  a word-overlap grader — the disagreement rate is reported, because a grader you
  have not checked is a number you cannot quote.

## Status

Every question is currently **unreviewed**. The questions were rewritten by a model;
the answers are what the judges concluded. Neither has had a human check, and
`drafted_by` says so on every row.

The keys the connector and web search both missed were audited against card text,
the rulebook, the handbooks and the Compendium; `key_checked_by` records what each
was checked against and what changed. Of 37 disputed keys, 8 were wrong or
malformed and 4 were time-bound. No rule-of-the-event key has yet been verified
against the current handbook revision as a whole — `stale.py` lists them all as
`asked before` until someone does.

## Licence

Code [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html). Questions
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — credit the source,
share extensions under the same licence. See `LICENSE-DATA`.

The system this was built to measure is
[judge-mcp](https://github.com/FellipeGiulianoDuarte/judge-mcp).

Unofficial. Not affiliated with, endorsed by, or sponsored by The Pokémon Company
International or Nintendo.
