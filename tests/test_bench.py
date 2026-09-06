"""The scenarios from the plan's test matrix.

Run:  .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "."))


# --- Benchmark split --------------------------------------------------------

class TestSplit:
    def test_split_is_stable_across_runs(self):
        """Re-running must not reshuffle, or the held-back half leaks over time."""
        from draft import is_private

        ids = [f"q-{i:04d}" for i in range(200)]
        assert [is_private(i) for i in ids] == [is_private(i) for i in ids]

    def test_private_share_is_roughly_a_quarter(self):
        from draft import is_private

        held = sum(is_private(f"q-{i:04d}") for i in range(1000))
        assert 200 <= held <= 300, f"{held}/1000 held back"

    def test_split_comes_from_the_id_not_the_file(self):
        """A question cannot be moved between halves by editing its row."""
        import json
        import tempfile
        from pathlib import Path

        from draft import is_private, write_split

        private_id = next(f"q-{i:04d}" for i in range(50) if is_private(f"q-{i:04d}"))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "drafted.jsonl"
            # Deliberately mislabelled as public.
            src.write_text(json.dumps({"id": private_id, "split": "public"}) + "\n")
            public = Path(tmp) / "questions.jsonl"
            write_split(src, public)
            assert public.read_text().strip() == "", "a private question reached the public file"

    def test_public_questions_carry_no_verbatim_message(self):
        """Questions are rewritten. A pasted message would fail review anyway,
        and the original wording is never reproduced either way."""
        import json
        from pathlib import Path

        path = ROOT / "bench/questions.jsonl"
        if not path.exists():
            pytest.skip("no questions yet")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            assert "_raw" not in row, f"{row['id']} carries raw messages"
            assert row.get("split") == "public"


# --- Question file integrity ------------------------------------------------

def _questions() -> list[dict]:
    import json

    rows = []
    for name in ("questions.jsonl", "questions.private.jsonl"):
        path = ROOT / "bench" / name
        if path.exists():
            rows += [json.loads(l) for l in
                     path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


def test_every_question_matches_the_schema():
    import json

    import jsonschema

    rows = _questions()
    if not rows:
        pytest.skip("no questions yet")
    schema = json.loads((ROOT / "bench/schema.json").read_text(encoding="utf-8"))
    for row in rows:
        jsonschema.validate(row, schema)


def test_open_questions_say_what_a_right_answer_contains():
    """There is no verdict to match, so without expected_points they are unscorable."""
    for row in _questions():
        if row["verdict"] == "open":
            assert row.get("expected_points"), f"{row['id']} is open with nothing to grade"


def test_question_ids_are_unique_across_both_halves():
    ids = [r["id"] for r in _questions()]
    assert len(ids) == len(set(ids))


def test_unkeyed_questions_are_marked_contested_not_left_silently_blank():
    """A question with no key measures nothing. If the source never settled on one, that
    is a finding — flag it rather than leaving an empty field to be missed."""
    for row in _questions():
        if not row.get("key_checked_by"):
            assert row.get("contested"), f"{row['id']} has no key and is not marked contested"


def test_publishing_strips_the_pointers_back_into_private_messages():
    """source_ref and date are for re-checking a key locally. Published they
    would point at where and when the question was recorded."""
    import json
    import subprocess
    import tempfile
    from pathlib import Path

    row = {"id": "q-deadbeef", "split": "public", "question_en": "x" * 40,
           "category": "interaction", "answer_source": "mechanics", "verdict": "yes",
           "key_checked_by": "original key", "key_checked_on": "2026-09-05",
           "source_ref": "src-0002", "date": "26/01/2025"}
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.jsonl"
        out = Path(tmp) / "out.jsonl"
        src.write_text(json.dumps(row) + "\n")
        subprocess.run([sys.executable, str(ROOT / "bench/publish.py"),
                        str(src), "--out", str(out)], check=True, capture_output=True)
        published = json.loads(out.read_text().strip())
    assert "source_ref" not in published
    assert "date" not in published
    assert published["question_en"] == row["question_en"]


def test_stale_flags_keys_checked_against_an_older_revision():
    """A tournament key verified against last season's handbook must be listed
    once a newer revision exists; one verified against the current revision
    must not; a game-rule question is not tracked at all."""
    sys.path.insert(0, str(ROOT / "bench"))
    import stale
    revisions = {"tcg-tournament-handbook": "2026-09-01", "tournament-rules-handbook": "2026-09-01"}
    rows = [
        {"id": "q-1", "category": "tournament", "key_checked_against": {"tcg-tournament-handbook": "2025-09-01", "tournament-rules-handbook": "2026-09-01"}},
        {"id": "q-2", "category": "tournament", "key_checked_against": {"tcg-tournament-handbook": "2026-09-01", "tournament-rules-handbook": "2026-09-01"}},
        {"id": "q-3", "category": "tournament", "asked": "2025-08"},
        {"id": "q-4", "category": "interaction"},
    ]
    flagged = {qid: reason for qid, reason, _ in stale.check(rows, revisions)}
    assert flagged == {"q-1": "stale", "q-3": "asked before"}


def test_publishing_keeps_the_month_but_not_the_day():
    """`asked` (YYYY-MM) is published so keys can be checked for staleness;
    `date` (the exact day) is not, because the exact day identifies a
    conversation."""
    import json, subprocess, tempfile
    row = {"id": "q-0000abcd", "question_en": "q?", "category": "tournament", "answer_source": "mechanics",
           "verdict": "yes", "expected_points": ["x"], "split": "public", "key_checked_by": "t",
           "source_ref": "src-0002", "date": "26/01/2025", "asked": "2025-01"}
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "q.jsonl"; out = Path(d) / "out.jsonl"
        src.write_text(json.dumps(row) + "\n")
        subprocess.run([sys.executable, str(ROOT / "bench/publish.py"), str(src), "--out", str(out)], check=True, capture_output=True)
        published = json.loads(out.read_text().strip())
    assert published["asked"] == "2025-01" and "date" not in published
