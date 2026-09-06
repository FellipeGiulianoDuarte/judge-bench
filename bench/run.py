"""Run the benchmark across conditions.

Five conditions, same questions, same key:

  1 no-tools           what the weights remember
  2 web-search         the real competitor — what a judge does today
  3 corpus-in-context  our two files pasted in, no retrieval
  4 api-direct         our lookup, called directly
  5 connector          our lookup, through MCP, with Claude writing the prose

3 vs 4 says whether retrieval adds anything over just having the corpus.
4 vs 5 says what it costs to let Claude write the answer.

NOTE ON temperature: current models reject it. Sampling parameters were removed
on Opus 5 and Sonnet 5 — passing temperature returns a 400. Determinism comes
from repeated runs and reporting variance, not from a temperature setting.

    python3 bench/run.py --limit 60 --conditions no-tools,web-search --runs 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "server"))

MODEL = "claude-opus-5"

SYSTEM = """You are answering Pokémon TCG rules questions as a tournament judge would.

Reply as JSON only, no prose around it:
{"verdict": "yes"|"no"|"depends"|"unanswerable",
 "answer": "<two sentences at most>",
 "asks_for": ["<anything you would need to know before ruling>"]}

Use "unanswerable" when you do not know. A confident wrong answer is worse than
admitting you cannot say."""


def load_questions(path: Path, limit: int | None) -> list[dict]:
    if not path.exists():
        sys.exit(f"{path} does not exist yet. Write questions first — see bench/schema.json.")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def ask_claude(question: str, condition: str, corpus: str = "") -> tuple[dict, dict]:
    """One question, one condition. Returns (parsed answer, usage)."""
    from anthropic import Anthropic

    client = Anthropic()
    system = SYSTEM
    tools: list[dict] = []

    if condition == "web-search":
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]
    elif condition == "corpus-in-context":
        system = f"{SYSTEM}\n\nUse ONLY the rules below. Exceptions override mechanics.\n\n{corpus}"
    elif condition not in ("no-tools",):
        raise ValueError(f"{condition} is not answered by this function — see the runner notes.")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        tools=tools or None,  # type: ignore[arg-type]
        messages=[{"role": "user", "content": question}],
    )
    if response.stop_reason == "refusal":
        return {"verdict": "unanswerable", "answer": "refused", "asks_for": []}, {}

    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        parsed = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        parsed = {"verdict": None, "answer": text[:400], "asks_for": [], "unparsed": True}
    usage = {"in": response.usage.input_tokens, "out": response.usage.output_tokens}
    return parsed, usage


def ask_api_direct(question: str, terms: str = "") -> tuple[dict, dict]:
    """Condition 4: our lookup with no model at all. Measures retrieval alone."""
    from lookup import lookup

    hit = lookup(question, terms)
    if hit["no_match"]:
        return {"verdict": "unanswerable", "answer": "", "asks_for": []}, {}
    top = (hit["exceptions"] or hit["mechanics"])[0]
    return {"verdict": None, "answer": top["text"], "retrieved": top["heading"],
            "asks_for": []}, {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=ROOT / "bench/questions.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--runs", type=int, default=3, help="repeats, to measure variance")
    ap.add_argument("--conditions", default="no-tools,web-search,corpus-in-context")
    ap.add_argument("--out", type=Path, default=ROOT / f"bench/results/{date.today()}.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and cost, call nothing")
    args = ap.parse_args()

    questions = load_questions(args.questions, args.limit)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    calls = len(questions) * len(conditions) * args.runs

    # ~5k in / 500 out at Opus 5 rates ($5/$25 per MTok). Sonnet 5 is ~2.5x cheaper.
    estimate = calls * ((5000 / 1e6) * 5 + (500 / 1e6) * 25)
    print(f"{len(questions)} questions x {len(conditions)} conditions x {args.runs} runs "
          f"= {calls} calls, roughly ${estimate:,.0f} on {MODEL}")

    if args.dry_run:
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run `ant auth status`, or use --dry-run.")

    corpus = ""
    if "corpus-in-context" in conditions:
        # Everything, including the ingested handbook sections. Passing only the
        # two hand-written files is 3k characters and makes the model refuse
        # every tournament and penalty question — correctly, and misleadingly.
        from corpus import load as load_corpus
        corpus = "\n\n".join(
            f"## {s.citation or s.heading}"
            f"{'  [EXCEPTION — overrides the general rule]' if s.kind == 'exceptions' else ''}"
            f"\n{s.body}"
            for s in load_corpus())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for q in questions:
            for condition in conditions:
                for run in range(args.runs):
                    if condition == "api-direct":
                        answer, usage = ask_api_direct(q["question_en"])
                    else:
                        answer, usage = ask_claude(q["question_en"], condition, corpus)
                    fh.write(json.dumps({
                        "id": q["id"], "condition": condition, "run": run,
                        "model": MODEL if condition != "api-direct" else "none",
                        "expected": q["verdict"], "got": answer, "usage": usage,
                    }, ensure_ascii=False) + "\n")
                    print(f"  {q['id']} {condition} run{run}: {answer.get('verdict')}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
