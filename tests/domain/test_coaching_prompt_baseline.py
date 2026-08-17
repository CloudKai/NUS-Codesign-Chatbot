"""Canonical Coaching prompt hash lock. Updating hashes requires pedagogical review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_FIXTURE = Path("tests/fixtures/coaching_prompt_baseline.json")


def test_canonical_coaching_prompts_match_pedagogical_baseline() -> None:
    """Fail if shared coaching or stage files change without explicit review.

    Hashes were generated from commit a6d163668902beae4938fe552cced7ba92b15e88.
    This test reads local files only. It does not shell out to Git or the network.
    """
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert "explicit pedagogical review" in str(payload.get("note") or "").lower()
    files = payload["files"]
    assert len(files) == 6
    for item in files:
        path = Path(item["path"])
        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert digest == item["sha256"], path.as_posix()
