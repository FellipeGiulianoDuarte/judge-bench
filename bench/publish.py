"""Strip local-only fields and write the file that gets published.

Two fields never leave this machine:

  source_ref  an opaque id into local working files
  date           the exact day the question was recorded; the month (`asked`)
                 is published instead

Both stay in the working copy so a disputed key stays traceable locally.

    python3 bench/publish.py work/merged.jsonl --out dist/questions.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

LOCAL_ONLY = ("source_ref", "date", "_raw")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("questions", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows = [json.loads(l) for l in
            args.questions.read_text(encoding="utf-8").splitlines() if l.strip()]

    public, held, unkeyed = [], 0, 0
    for row in rows:
        if row.get("split") == "private":
            held += 1
            continue
        if not row.get("key_checked_by") and not row.get("contested"):
            unkeyed += 1
            continue
        public.append({k: v for k, v in row.items() if k not in LOCAL_ONLY})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in public),
                        encoding="utf-8")

    leaked = [f for r in public for f in LOCAL_ONLY if f in r]
    print(f"{len(public)} questions -> {args.out}")
    print(f"  held back (private split)      : {held}")
    print(f"  dropped (no key, not contested): {unkeyed}")
    print(f"  local-only fields in output    : {leaked or 'none'}")
    assert not leaked


if __name__ == "__main__":
    main()
