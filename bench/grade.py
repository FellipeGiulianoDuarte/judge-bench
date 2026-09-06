"""Score a benchmark run.

Five numbers, reported separately because they fail in different ways:

  verdict      right answer on a yes/no question
  points       for an "open" question, how many required facts the answer contains
  refused      said it did not know — a different failure from being wrong
  asking       asked for event tier / division instead of assuming
  variance     how much the same condition moved across repeated runs

Why verdict and points are separate: "open" as a verdict only means "not yes/no".
Matching on it is nearly free and counting it as correct inflates every score.
An open question is graded on its expected_points and on nothing else.

Why refusals are their own column: a system that says "I do not know" failed
safely, and one that invents a section number did not. Averaging them together
hides the distinction this project exists to measure.

n IS QUESTIONS, NOT ROWS. Three runs of the same question are not three
independent samples — they are usually identical, and counting them separately
triples n and shrinks every confidence interval to a third of its honest width.
Runs are collapsed to one result per question (majority across runs) before
anything is counted. The run-to-run spread at the bottom is where repeated runs
earn their keep: it says how much of any gap is noise.

Never publish one aggregate. 87% overall hides 100% on legality and 40% on
interactions, and interactions are the hard part. Never publish a bare
percentage either — the interval is what says whether a gap is real.

    python3 bench/grade.py bench/results/2026-09-05.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent


def wilson(hits: int, n: int) -> tuple[float, float, float]:
    """Wilson score interval. Normal approximation breaks near 0 and 1, and a
    benchmark with a 100% cell is exactly where that happens."""
    if n == 0:
        return 0.0, 0.0, 0.0
    z, p = 1.96, hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - spread), min(1.0, centre + spread)


def load_judgements(path: Path) -> dict[tuple[str, str], list[bool]]:
    """Model-judged coverage per (question, condition), if bench/local/judge.py ran.

    Term overlap systematically under-credits paraphrase: it scored "its outcome
    stands and the board cannot be rewound" as missing "the result of the
    finished game is not overturned". Same ruling, no shared words. When
    judgements exist they are used instead; otherwise the approximate matcher
    still runs, and the report says which was used.
    """
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[(d["id"], d["condition"])] = d["model_covered"]
    return out


def load(results: Path, questions: Path) -> tuple[list[dict], dict[str, dict]]:
    rows = [json.loads(l) for l in results.read_text(encoding="utf-8").splitlines() if l.strip()]
    keyed = {q["id"]: q for q in
             (json.loads(l) for l in questions.read_text(encoding="utf-8").splitlines() if l.strip())}
    return rows, keyed


STOP = {"the", "a", "an", "is", "it", "of", "to", "in", "on", "and", "or", "if",
        "that", "this", "for", "be", "are", "was", "not", "no", "at", "as", "by",
        "with", "from", "then", "than", "would", "any", "player", "players"}


def terms(text: str) -> set[str]:
    import unicodedata
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return {t for t in re.split(r"[^a-z0-9]+", folded) if len(t) > 2 and t not in STOP}


def covers(answer: str, point: str, threshold: float = 0.5) -> bool:
    """Rough: does the answer contain most of the content words of this point?

    Approximate on purpose and it will both miss and over-credit. It is here so
    an "open" question is graded on something rather than on a free verdict
    match; replace it with a model grader validated against human labels before
    publishing any number that came out of it.
    """
    wanted = terms(point)
    return bool(wanted) and len(wanted & terms(answer)) / len(wanted) >= threshold


def collapse(rows: list[dict]) -> list[dict]:
    """One row per (question, condition): the majority result across runs.

    Repeated runs measure variance, not sample size. Counting each run as a
    separate observation is the difference between "100% [86%-100%] n=24" and
    "100% [68%-100%] n=8" — the second is the truth.
    """
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["id"], row["condition"])].append(row)

    collapsed = []
    for (_, _), runs in grouped.items():
        verdicts = Counter(r["got"].get("verdict") for r in runs)
        winner = verdicts.most_common(1)[0][0]
        # Keep a full row whose verdict is the majority one, so the answer text
        # that gets point-graded belongs to the verdict being counted.
        pick = next(r for r in runs if r["got"].get("verdict") == winner)
        collapsed.append({**pick, "runs": len(runs)})
    return collapsed


def grade(rows: list[dict], keyed: dict[str, dict],
          judged: dict[tuple[str, str], list[bool]] | None = None) -> dict:
    judged = judged or {}
    cells: dict[tuple, list[bool]] = defaultdict(list)
    points: dict[tuple, list[bool]] = defaultdict(list)
    refused: dict[str, list[bool]] = defaultdict(list)
    asked: dict[str, list[bool]] = defaultdict(list)
    per_run: dict[tuple, list[bool]] = defaultdict(list)

    # Variance is measured on the raw rows, before collapsing.
    for row in rows:
        q = keyed.get(row["id"])
        if q and q["verdict"] != "open":
            per_run[(row["condition"], row["run"])].append(
                row["got"].get("verdict") == q["verdict"])

    for row in collapse(rows):
        q = keyed.get(row["id"])
        if not q:
            continue
        got, condition = row["got"], row["condition"]
        said = got.get("verdict")
        answer = got.get("answer", "") or ""

        refused[condition].append(said == "unanswerable")

        if q["verdict"] == "open":
            # No verdict to match. Score on the share of required facts present,
            # as ONE observation per question rather than one per fact — the
            # facts within a question are not independent either.
            expected = q.get("expected_points") or []
            if not expected:
                continue
            by_model = judged.get((row["id"], condition))
            if by_model:
                share = sum(bool(x) for x in by_model[:len(expected)]) / len(expected)
            else:
                share = sum(covers(answer, point) for point in expected) / len(expected)
            got_most = share >= 0.5
            points[(condition, q["category"])].append(got_most)
            points[(condition, "ALL")].append(got_most)
            continue

        correct = said == q["verdict"]
        for slice_name in (q["category"], "ALL", f"source:{q['answer_source']}"):
            cells[(condition, slice_name)].append(correct)
        if q.get("answer_changed_after"):
            cells[(condition, "changed-since-cutoff")].append(correct)

        if q.get("needs_context"):
            wanted = set(q["needs_context"])
            asks = " ".join(got.get("asks_for", [])).lower()
            asked[condition].append(any(w in asks for w in wanted))

    return {"cells": cells, "points": points, "refused": refused,
            "asked": asked, "per_run": per_run,
            "grader": "model-judged" if judged else "word overlap, approximate"}


CONDITIONS = {
    "no-tools": "asked cold, no search, no documents",
    "web-search": "same model with web search turned on",
    "corpus-in-context": "same model, our whole rules corpus pasted into the prompt",
    "api-direct": ("our lookup called directly, no model writing the answer "
                   "— it returns a rules section, so it CANNOT score on yes/no "
                   "questions; read its rows in the detail view instead"),
    "mcp": ("the model calls our four tools, reads what comes back, and writes "
            "the answer — this is the product"),
    "connector": "our lookup through the MCP connector, model writes the answer",
}


def _header(rows: list[dict], keyed: dict[str, dict]) -> list[str]:
    models = sorted({r.get("model", "?") for r in rows})
    conditions = sorted({r["condition"] for r in rows})
    asked = sorted({r["id"] for r in rows})
    runs = max(r.get("run", 0) for r in rows) + 1

    print("=" * 100)
    print(f"WHAT WAS RUN: {len(asked)} Pokemon TCG rules questions, each asked "
          f"{runs} time{'s' if runs > 1 else ''}, of "
          f"{' and '.join(m for m in models if m != 'none')}.")
    print(f"WHERE THE QUESTIONS CAME FROM: real judge discussions, rewritten. The "
          f"right answer is what")
    print(f"                               the judges concluded in the original thread.")
    print()
    print("THE CONDITIONS COMPARED:")
    for c in conditions:
        print(f"  {c:20} {CONDITIONS.get(c, '?')}")
    print("=" * 100)
    return conditions


def detail(rows: list[dict], keyed: dict[str, dict], conditions: list[str]) -> None:
    """One block per question: what was asked, the right answer, what each said."""
    by_question: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_question[row["id"]][row["condition"]].append(row)

    for qid in sorted(by_question):
        q = keyed.get(qid)
        if not q:
            continue
        print(f"\n{'-' * 100}")
        print(f"{qid}   [{q['category']}]   answer comes from: "
              f"{'the rulebook' if q['answer_source'] == 'mechanics' else 'a TPCi decision you cannot derive'}")
        print(f"QUESTION ASKED:  {q['question_en']}")
        if q["verdict"] == "open":
            print(f"RIGHT ANSWER:    not yes/no. It must contain:")
            for point in q.get("expected_points", []):
                print(f"                   - {point}")
        else:
            print(f"RIGHT ANSWER:    {q['verdict'].upper()}")
        print(f"KEY VERIFIED BY: {q.get('key_checked_by') or 'NOBODY — unverified'}")
        print()
        for condition in conditions:
            runs = by_question[qid].get(condition, [])
            if not runs:
                continue
            said = Counter(r["got"].get("verdict") for r in runs)
            agreed = "same every run" if len(said) == 1 else f"DIFFERED ACROSS RUNS: {dict(said)}"
            best = runs[0]
            answer = (best["got"].get("answer") or "").replace("\n", " ")

            if q["verdict"] == "open":
                expected = q.get("expected_points", [])
                hit = [p for p in expected if covers(answer, p)]
                mark = f"{len(hit)}/{len(expected)} facts"
            else:
                mark = "CORRECT" if said.most_common(1)[0][0] == q["verdict"] else "WRONG"

            print(f"  {condition:20} {mark:14} said: {said.most_common(1)[0][0]}   ({agreed})")
            print(f"  {'':20} {'':14} {answer[:150]}")
    print(f"\n{'-' * 100}\n")


def _table(title: str, subtitle: str, cells: dict, conditions: list[str]) -> None:
    slices = sorted({s for _, s in cells}, key=lambda s: (s != "ALL", s))
    if not slices:
        return
    labels = {
        "ALL": "every question of this kind",
        "interaction": "how cards interact",
        "penalty": "what to do when a rule is broken",
        "tournament": "how the event runs",
        "legality": "is this card allowed",
        "source:mechanics": "answer is in the rulebook",
        "source:exception": "answer is a TPCi decision",
        "changed-since-cutoff": "the right answer changed recently",
    }
    print(f"\n{title}")
    print(f"  {subtitle}")
    print()
    width = max(len(labels.get(s, s)) for s in slices) + 2
    print(f"{'':{width}}" + "".join(f"{c:>26}" for c in conditions))
    for slice_name in slices:
        line = f"{labels.get(slice_name, slice_name):{width}}"
        for condition in conditions:
            data = cells.get((condition, slice_name))
            if not data:
                line += f"{'not asked':>26}"
                continue
            p, lo, hi = wilson(sum(data), len(data))
            line += f"{f'{sum(data)}/{len(data)}  ({lo:.0%}-{hi:.0%})':>26}"
        print(line)


def report(scored: dict, rows: list[dict], keyed: dict[str, dict], show_detail: bool) -> None:
    conditions = _header(rows, keyed)
    if show_detail:
        detail(rows, keyed, conditions)

    _table("SCORE ON YES/NO QUESTIONS",
           "questions right out of questions asked. Range in brackets is where the "
           "true rate probably sits, 95% confidence.",
           scored["cells"], conditions)
    _table("SCORE ON OPEN QUESTIONS (what is the fix? how does the match end?)",
           "counted right when the answer contains most of the required facts. "
           "Matching is approximate - read the detail above before trusting it.",
           scored["points"], conditions)

    print("\nHOW OFTEN IT SAID 'I DO NOT KNOW'")
    print("  A wrong answer and a refusal are different failures. This counts refusals.")
    print()
    for condition in conditions:
        data = scored["refused"].get(condition)
        if data:
            print(f"  {condition:22} {sum(data)} of {len(data)} questions")

    if any(scored["asked"].values()):
        print("\nASKED FOR THE MISSING FACT INSTEAD OF ASSUMING IT")
        print("  Penalties change with event tier and age division. This counts whether it asked.")
        print()
        for condition, data in sorted(scored["asked"].items()):
            if data:
                print(f"  {condition:22} {sum(data)} of {len(data)} questions")

    spreads = defaultdict(list)
    for (condition, _), data in scored["per_run"].items():
        if data:
            spreads[condition].append(sum(data) / len(data))
    if spreads:
        print("\nDID IT GIVE THE SAME ANSWER EACH TIME IT WAS ASKED?")
        print("  A difference between two conditions smaller than this is noise, not a result.")
        print()
        for condition, runs in sorted(spreads.items()):
            print(f"  {condition:22} best and worst run differ by "
                  f"{max(runs) - min(runs):.0%}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", type=Path)
    ap.add_argument("--questions", type=Path, default=ROOT / "bench/questions.jsonl")
    ap.add_argument("--judged", type=Path, default=ROOT / "bench/results/judged.jsonl",
                    help="model judgements from bench/local/judge.py, if present")
    ap.add_argument("--summary", action="store_true",
                    help="scores only; default also prints every question and answer")
    args = ap.parse_args()
    rows, keyed = load(args.results, args.questions)
    judged = load_judgements(args.judged)
    report(grade(rows, keyed, judged), rows, keyed, show_detail=not args.summary)


if __name__ == "__main__":
    main()
