# Phase 1 choices

## Item 1: reserved result slots (2 course + 2 student)

- **Choice:** 4 total slots split 2 course (Knowledge Base) + 2 student upload.
  New setting `FAST_CHAT_RETRIEVAL_COURSE_SLOTS` (default 2, bounds 1 to 8). The
  student share is `FAST_CHAT_RETRIEVAL_MAX_CHUNKS - course slots`.
- **Why:** The existing config already caps the prompt at
  `FAST_CHAT_RETRIEVAL_MAX_CHUNKS=4`, so 2 + 2 is the even split inside that cap and
  matches the plan's "about 2 + 2". No new total, so prompt size and cost do not change.
- **Where the crowding came from:** `CompositeContextRetriever` appended up to 4
  Knowledge Base chunks before the local chunks, then `execution.py` re-bounded to
  the first 4. A full set of course hits left no room for uploads.
- **Rules:** both sides keep at least one slot when the total is 2 or more. A side
  that returns fewer hits releases its unused slots (course side is offered spare
  slots first). Course chunks stay ahead of upload chunks in the prompt.
- **Known limit:** the 8,000-character prompt budget in `execution.py` still applies
  after the slot cut. Two very large course chunks could still squeeze the tail.
  Not changed, because it is a separate budget.
- **Known limit:** selected image marker chunks from the local retriever count as
  student slots.

## Item 2: Knowledge Base candidates (12)

- **Choice:** request 12 candidates (`KNOWLEDGE_BASE_RETRIEVE_CANDIDATES`, default 12,
  bounded 12 to 16), validate each, rank by score, keep the best 4
  (`FAST_CHAT_RETRIEVAL_MAX_CHUNKS`).
- **Why:** 12 is 3 times the kept count, at the low end of the 12 to 16 range. The
  Retrieve call latency is dominated by the managed search round trip, not the
  result count, and fewer candidates keep response size and validation work small.
  Operators can raise it to 16 without a code change.
- The adapter never sends fewer candidates than it keeps. Hits failing the bucket,
  object-key or empty-text checks never take a kept slot. Two existing tests that
  asserted `numberOfResults == 4` now assert 12.

## Item 3: parallel retrieval

- The Knowledge Base call runs on a one-worker thread with the turn's context copied
  (`contextvars.copy_context`), so turn-perf fields still land on the right turn.
  Local ranking runs on the calling thread. Exceptions from either side propagate as
  before. Retrieve admission and timeout logic in `bedrock_retrieve.py` is unchanged.
- Local ranking is pure Python, so the gain is overlap with the network wait of the
  Knowledge Base call, not CPU parallelism.

## Ruff baseline findings

The baseline had three F401 findings. Two unused imports were removed
(`backend/http/app.py`, `tests/domain/test_hmw_scaffold_gate.py`). The third,
`UploadAdmissionError` in `ui/services/runtime.py`, is re-exported through
`ui.runtime` and used by `ui/panels/sources.py`, so it stays with a `noqa: F401`.
