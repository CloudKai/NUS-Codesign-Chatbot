# Stage feedback in Summary

## Problem Statement

Students value the stage-by-stage Going well and To work on feedback currently
shown in My work. Moving My work to selected bookmarks requires a clear home
for that feedback alongside the project summary and Facione scores.

## Solution

Arrange Summary as a wide project summary at the top, each Thinking Path stage's
Going well and To work on feedback below, followed by the existing Facione scoring.

## User Stories

1. As a student, I want a wide summary at the top, so that I can understand my project before reading detailed feedback.
2. As a student, I want feedback grouped by stage, so that I can understand where each strength or improvement belongs.
3. As a student, I want the Going well feedback from My work, so that useful positive feedback stays available.
4. As a student, I want the To work on feedback from My work, so that I can identify improvements for each stage.
5. As a student, I want stages in Thinking Path order, so that I can review my journey consistently.
6. As a student, I want Facione scoring after stage feedback, so that I can inspect my critical-thinking assessment.
7. As a student, I want existing Facione tips and practice actions, so that I can act on my scores.
8. As a student, I want honest empty states, so that missing feedback is clear.
9. As a student, I want long feedback to remain readable on mobile, so that I can review it on my phone.
10. As a student, I want saved feedback restored on reload, so that I can resume reviewing it.
11. As a student, I want stage feedback available even when I have no stars, so that bookmarking does not control assessment.

## Implementation Decisions

- Update the React Thinking Path Summary presentation using its existing server-provided review data.
- Replace the current aggregate Strengths and Areas to improve cards with the per-stage Going well and To work on content currently rendered in My work.
- Use a top summary spanning the available Summary panel width. Reuse the saved project review summary and existing fallback behavior when a project summary is unavailable.
- Preserve canonical stage labels and ordering, existing feedback wording, and Facione values, tips and practice controls.
- Render only saved assessments. Opening Summary or starring messages must not trigger model generation or infer a score.
- Complete this spec first so stage feedback is available before My work becomes bookmark-only.

## Testing Decisions

- The user-approved seam is the rendered React workspace in a real browser using a disposable mock backend with known saved review data.
- Verify summary, ordered stage feedback and Facione sequence, exact saved feedback, empty states, existing score interactions and reload behavior.
- Reuse the existing mock student-journey setup for known review data. Assert visible behavior and accessibility rather than component internals or source strings.
- Browser checks cover desktop and 390 px mobile, keyboard access and console errors. This seam covers observable integration and layout, with exhaustive backend failure testing belonging to the existing HTTP suite.
- Work in vertical red/green cycles with one behavioral test followed by minimal implementation.

## Out of Scope

Changing assessment prompts, scores, stage progression, feedback generation or adding a new review system.

## Further Notes

Publish with ready-for-agent after confirming the test seam. Record validation,
compatibility, rollback and the next exact action in implementation status before
starting the bookmark spec in a fresh session.

Implemented and verified on 2026-11-22. See the
[implementation handoff](STAGE_REVIEW_SUMMARY_HANDOFF.md) for validation,
compatibility, rollback and the bookmark entry point.
