"""List answer keys that may have gone out of date.

Tournament and penalty rules are rewritten every season. Three keys in this
set were found describing rules TPCi had since changed: who chooses first in
top cut, the end-of-round procedure, the overtime limit. Nothing in the file
had said when a key was written or which handbook it was checked against, so
nothing could have flagged them. Now each question carries `asked` (the month
the judges discussed it) and, once someone has verified it against a dated
document, `key_checked_against` ({document: ISO revision date}).

This script compares those with the revision dates in
bench/handbook_revisions.json and prints the keys that need a re-read:

  never checked   a rule-of-the-event question with no `key_checked_against`
  stale           checked against a revision older than the current one
  asked before    no check on record and the judges discussed it before the
                  current revision — the answer may describe the old rule

It changes nothing. Re-reading a key is a person's job.

    python3 bench/stale.py bench/questions.jsonl
    python3 bench/stale.py bench/questions.jsonl --strict   # exit 1 if any stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVISIONS = ROOT / "bench/handbook_revisions.json"

# Which documents govern which question categories. Game-rule questions
# (interaction) follow the rulebook and card text, which change far less
# often, and are not tracked here.
GOVERNS = {
    "tournament": ("tcg-tournament-handbook", "tournament-rules-handbook"),
    "penalty": ("penalty-guidelines", "tcg-tournament-handbook"),
    "legality": ("tcg-tournament-handbook",),
    "deckbuilding": ("tcg-tournament-handbook",),
}


def month(iso_date: str) -> str:
    return iso_date[:7]


def check(rows: list[dict], revisions: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return (id, reason, detail) for every key that needs a re-read."""
    out = []
    for row in rows:
        docs = GOVERNS.get(row.get("category"))
        if not docs or row.get("contested"):
            continue
        against = row.get("key_checked_against") or {}
        current = {d: revisions[d] for d in docs if d in revisions}
        if not against:
            asked = row.get("asked")
            newest = max(current.values(), default=None)
            if asked and newest and asked < month(newest):
                out.append((row["id"], "asked before",
                            f"discussed {asked}, {' / '.join(current)} revised {newest}"))
            else:
                out.append((row["id"], "never checked", ", ".join(current)))
            continue
        for doc, rev in current.items():
            seen = against.get(doc)
            if seen is None or seen < rev:
                out.append((row["id"], "stale", f"{doc}: checked against {seen or 'nothing'}, now {rev}"))
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("questions", type=Path)
    ap.add_argument("--revisions", type=Path, default=REVISIONS)
    ap.add_argument("--strict", action="store_true", help="exit 1 if anything is listed")
    ap.add_argument("--all", action="store_true",
                    help="also list every 'asked before' key; by default only the count is shown, "
                         "because until keys are verified against a dated document that is all of them")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.questions.read_text(encoding="utf-8").splitlines() if l.strip()]
    revisions = json.loads(args.revisions.read_text(encoding="utf-8"))
    revisions = {k: v for k, v in revisions.items() if not k.startswith("_")}
    flagged = check(rows, revisions)

    tracked = sum(1 for r in rows if r.get("category") in GOVERNS and not r.get("contested"))
    print(f"{tracked} rule-of-the-event keys tracked against: "
          + ", ".join(f"{d} {v}" for d, v in sorted(revisions.items())))
    by_reason: dict[str, int] = {}
    for _, reason, _ in flagged:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    print("needing a re-read: " + (", ".join(f"{k} {v}" for k, v in sorted(by_reason.items())) or "none"))
    for qid, reason, detail in flagged:
        if reason == "asked before" and not args.all:
            continue
        print(f"  {qid}  {reason:14} {detail}")
    if by_reason.get("asked before") and not args.all:
        print(f"  ({by_reason['asked before']} 'asked before' keys not listed; pass --all)")
    if args.strict and flagged:
        sys.exit(1)


if __name__ == "__main__":
    main()
