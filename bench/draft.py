"""Sample candidate records for review, and assign the public/private split.

Two jobs.

1. Pull a stratified sample of records from work/*.jsonl so you read across
   topics rather than top to bottom. Output is work/drafts.jsonl — gitignored,
   because it holds other people's messages verbatim.

2. Decide which questions are held back. The split is assigned by hashing the
   question id, so it is stable: re-running does not reshuffle, and adding
   questions later does not move existing ones between halves.

WHY HOLD ANY BACK: publishing a benchmark feeds it into the next training cycle.
Within a year a model may score well on the public half by memory rather than by
reasoning. The private half is what still means something then, and it can only
be created now — you cannot retroactively un-publish a question.

    python3 bench/draft.py --sample 60
    python3 bench/draft.py --split bench/questions.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORK = ROOT / "work"
PRIVATE_SHARE = 0.25


def is_private(question_id: str) -> bool:
    """Stable, uniform, and reproducible from the id alone."""
    digest = hashlib.sha256(question_id.encode()).digest()
    return digest[0] / 255 < PRIVATE_SHARE


def sample(n: int, seed: int = 7) -> list[dict]:
    """Stratified by topic, so 60 questions are not 45 card interactions."""
    records = []
    for path in sorted(WORK.glob("*.jsonl")):
        if path.name == "drafts.jsonl":
            continue
        records += [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise SystemExit("No records in work/. Run the extraction step first.")

    # Answered records only — an unanswered one gives a question with no clue
    # what the source concluded, which is most of the value in reviewing it.
    records = [t for t in records if t.get("answered")]

    buckets: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        buckets[record["topics"][0]].append(record)

    rng = random.Random(seed)
    for pool in buckets.values():
        rng.shuffle(pool)

    # Round-robin across topics rather than a fixed quota each: small buckets
    # empty out and the larger ones keep filling, so asking for 60 gets 60.
    picked: list[dict] = []
    taken = {topic: 0 for topic in buckets}
    while len(picked) < n:
        progressed = False
        for topic in sorted(buckets):
            if len(picked) >= n:
                break
            index = taken[topic]
            if index < len(buckets[topic]):
                picked.append(buckets[topic][index])
                taken[topic] += 1
                progressed = True
        if not progressed:
            break        # every bucket exhausted
    rng.shuffle(picked)
    return picked


def write_drafts(records: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for index, record in enumerate(records):
            qid = f"q-{index:04d}"
            fh.write(json.dumps({
                "id": qid,
                "split": "private" if is_private(qid) else "public",
                "topic_guess": record["topics"],
                "date": record["date"],
                "source_ref": record["id"],
                # You fill these in. The question must be YOUR words — never a
                # message pasted across.
                "question_en": "",
                "verdict": "",
                "answer_source": "",
                "key_checked_by": "",
                # Read-only context. Stays in work/, never in bench/.
                "_raw": record["raw"],
            }, ensure_ascii=False) + "\n")


def split_report(path: Path) -> None:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    counts = Counter("private" if is_private(r["id"]) else "public" for r in rows)
    total = sum(counts.values())
    for half, n in sorted(counts.items()):
        print(f"  {half:8} {n:4}  ({100*n//max(total,1)}%)")
    print(f"\n  public  -> {path}")
    print(f"  private -> {path.with_suffix('')}.private.jsonl  (gitignored, never published)")


def write_split(drafted: Path, public: Path) -> None:
    """Route each question to its half. The private file is never published.

    Split comes from the id hash, not from the file it was written in — so a
    question cannot be moved between halves by editing it, deliberately or by
    accident.
    """
    private = public.with_suffix("")
    private = private.with_name(private.name + ".private.jsonl")
    rows = [json.loads(l) for l in drafted.read_text(encoding="utf-8").splitlines() if l.strip()]

    halves: dict[Path, list[dict]] = {public: [], private: []}
    for row in rows:
        row["split"] = "private" if is_private(row["id"]) else "public"
        halves[private if row["split"] == "private" else public].append(row)

    for path, kept in halves.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in kept:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {len(kept):4} -> {path.name}")

    unverified = sum(1 for r in rows if not r.get("key_checked_by"))
    if unverified:
        print(f"\n  {unverified} of {len(rows)} have no verified answer key. "
              f"A question without a checked key measures nothing.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, help="how many records to pull for review")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--split", type=Path, help="report the split of an existing question file")
    ap.add_argument("--write", type=Path, help="route a drafted file into its public and private halves")
    ap.add_argument("--public", type=Path, default=ROOT / "bench/questions.jsonl")
    args = ap.parse_args()

    if args.write:
        write_split(args.write, args.public)
        return

    if args.split:
        split_report(args.split)
        return
    if not args.sample:
        ap.error("pass --sample N, --write FILE, or --split FILE")

    records = sample(args.sample, args.seed)
    out = WORK / "drafts.jsonl"
    write_drafts(records, out)

    topics = Counter(t["topics"][0] for t in records)
    private = sum(is_private(f"q-{i:04d}") for i in range(len(records)))
    print(f"{len(records)} records -> {out}")
    print(f"  held back: {private} private / {len(records)-private} public")
    for topic, n in topics.most_common():
        print(f"    {n:3}  {topic}")


if __name__ == "__main__":
    main()
