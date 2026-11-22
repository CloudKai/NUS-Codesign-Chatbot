# Summary #30 implementation handoff

Subsequent Review refinements (2026-11-22), including disclosures, the Chat overview
and owner/chat-scoped restoration, are recorded in the
[Review refinements handoff](REVIEW_REFINEMENTS_HANDOFF.md). This document records
the earlier ticket's implementation and evidence.

## Behavior and scope

Summary now shows the existing saved project summary across the available panel
width, followed by Going well and To work on for each canonical Thinking Path
stage, then the existing Facione scores, tips and Practice control. Feedback uses
the same stage-specific saved data and wording as My work. Missing feedback is
explicitly unassessed. Wrapped phone feedback has 14 px separation between groups.

My work, Progression, stage decisions, summary fallback/Read more, transcript,
download and backend contracts remain unchanged. The obsolete aggregate feedback
cards and their private helpers were removed. No provider or assessment changes.

## Files

- `frontend/src/ThinkingPath.tsx`: ordered stage feedback replaces aggregate cards.
- `frontend/src/styles.css`: stage feedback group spacing.
- `tests/browser/stage_review_summary.js`: public HTTP fixture setup and rendered
  saved-feedback, scores, actions, keyboard, reload and responsive regression.
- `tests/browser/stage_review_summary_empty.js`: missing-summary, per-stage empty
  feedback and unassessed score regression.
- `frontend/README.md`, `frontend/DESIGN.md`, `docs/TESTING.md`: behavior and test
  instructions; `docs/IMPLEMENTATION_STATUS.md`: phase evidence and next action.

## Validation evidence

Two vertical slices ran red before green: ordered stage feedback was absent from
Summary; then rendered feedback groups lacked readable separation. The first
browser regression now passes with ten saved turns across all five stages and
explicit confirmed progression. It checks exact server-provided wording and
ordering, full-width summary, score values/tips/practice, editable draft insertion,
keyboard tabs, reload, no Review POSTs, horizontal overflow and console errors.
The second regression passes for all ten feedback empty states and absent scores.

Real browser QA covered 1440 px desktop and 390 px phone widths in Light and Dark.
Screenshots are under ignored `output/playwright/summary-30/`. Restart QA compared
the entire public project response before/after restarting the disposable API,
then reloaded and checked the rendered summary and saved feedback again.
FastAPI `/api/v1/health` and Streamlit `/_stcore/health` returned healthy.
Focused HTTP tests passed all 11 cases in `test_student_journey_readiness.py` and
`test_notebook_reader.py`, including citation/source, streaming, stage confirmation
and persistence/restart behavior.

The frontend TypeScript/Vite build and Python compilation passed through
`sh scripts/build.sh`. Its normal pytest invocation hit an existing environment
collision: `.venv/lib/python3.12/site-packages/tests/__init__.py` shadows the
repository's namespace, breaking two script-test imports during collection.
`--import-mode=importlib` is unsuitable because sibling helper imports also fail.
The full suite was therefore run with an explicit process-local namespace binding:

```sh
.venv/bin/python - <<'PY'
import pathlib
import sys
import types
import pytest
local_tests = types.ModuleType('tests')
local_tests.__path__ = [str(pathlib.Path('tests').resolve())]
sys.modules['tests'] = local_tests
raise SystemExit(pytest.main(['-q']))
PY
```

This changes only test-process import resolution, excludes no tests, and changes
no repository or installed dependency. All **3,158 tests passed**, with no failures
or skips. Validation logs are in `/private/tmp/codesign-summary-30/`.
The visual detector flagged pre-existing font, gradient and border styles; these
were preserved to keep this approved layout change within scope.

## Compatibility and rollback

No schema, persistence format, API, `.env`, real data or migration changes. The
existing saved review projection is reused. Roll back by reverting only this
phase's frontend source changes and rebuilding. No stage, commit, deployment or
paid API call was performed. The user's existing `scripts/start_local_8081.sh`
changes and specification/status work were preserved.

## Next exact action: #31 in a fresh session

Read [Starred messages](STARRED_MESSAGES.md), root/package guides and current
implementation status, then start with one failing authenticated reader HTTP test
for explicit desired star state and its visible HTTP read. The user has already
approved authenticated HTTP tests for persistence/ownership/edit behavior and real
browser tests with a disposable mock backend for actions, jumps and bookmark-only
My work. Do not ask again about those seams. Continue one red/green slice at a time.

Summary's stage feedback must remain available when My work becomes bookmarks.
Use saved message identity, stage and intent; load bookmarks independently of the
transcript page; preserve ownership, active revisions, unrelated metadata and
idempotency. New messages and legacy records must default to unstarred. No schema
change is needed unless the existing persistence facilities demonstrably require
one. Keep one writer, deterministic mocks, no paid calls, and no staging/commit/deploy.

Fixture notes: quick chats start unnamed and can be renamed through settings;
idempotency keys are owner-scoped, so include the new chat id. The ten-turn journey
requires the test-only supported `COACH_REQUESTS_PER_MINUTE=120`; values above its
allowed bound fall back to eight. Require NDJSON `done`, not merely HTTP 200.
The repository has a cached Playwright CLI at
`/Users/kaiming/.npm/_npx/31e32ef8478fbf80/node_modules/@playwright/cli/playwright-cli.js`.
It works through `node` when the wrapper cannot reach npm. Local server/browser
commands need the environment's normal local-network approval. The #30 test
backend used disposable `/private/tmp/codesign-summary-30/` data on port 8093;
Streamlit used 8593. Both are stopped before handoff.
