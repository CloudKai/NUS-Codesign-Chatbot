# Stage-grouped message bookmarks

## Problem Statement

Students need to revisit useful moments in their conversations. My work currently
lists student contributions automatically, which makes important messages hard to
find and excludes coach replies students may want to save.

## Solution

Let the notebook owner star or unstar individual student messages and coach
replies. My work displays only starred messages, grouped by their saved Thinking
Path stage. A Jump to message action brings the original message into view and
highlights it.

## User Stories

1. As a student, I want to star my own message, so that I can save an important idea.
2. As a student, I want to star a coach reply, so that I can revisit useful guidance.
3. As a student, I want to unstar a message in Chat, so that I can remove a bookmark.
4. As a student, I want to remove a star from My work, so that I can curate saved work efficiently.
5. As a student, I want only starred messages in My work, so that the area stays manageable.
6. As a student, I want bookmarks grouped by the message's saved stage, so that I can review each part of my journey.
7. As a student, I want bookmarks to retain their stage after I advance or revisit, so that their context stays reliable.
8. As a student, I want to save Lecture Help messages, so that useful course explanations remain accessible.
9. As a student, I want a Lecture Help tag only on messages sent in that mode, so that I can recognize their context.
10. As a student, I want older messages without a stage grouped under No stage, so that I can still bookmark them.
11. As a student, I want No stage to appear collapsed only when populated, so that it takes little space.
12. As a student, I want to jump to the exact original message, so that I can read its surrounding conversation.
13. As a student, I want the target highlighted, so that I can identify it immediately.
14. As a student, I want stars to survive reload and server restart, so that saved work remains available.
15. As a student, I want stars private to my notebook ownership, so that other users cannot read or change them.
16. As a student, I want replaced or deleted messages removed from My work, so that each bookmark has an available original.
17. As a student, I want a revised message to need its own star, so that a bookmark always represents the text I selected.
18. As a student, I want keyboard and mobile access to stars and jumps, so that I can use them across devices.
19. As a student, I want clear feedback if saving fails, so that I know whether my bookmark persisted.

## Implementation Decisions

- Extend the React message actions, typed browser API, workspace service and repository through existing ownership boundaries.
- Use stable message identity and authoritative saved stage and interaction intent. Do not infer a stage from message text or the current notebook stage.
- Persist bookmark state on the server. Existing messages default to unstarred.
- Accept explicit desired starred state so repeated requests are idempotent. Preserve unrelated metadata and concurrent transcript changes.
- Validate active message membership and notebook ownership on every write and read. Replaced conversation revisions cannot expose stale bookmarks.
- Keep stars independent of learning assessment, model calls, stage confirmation and review generation.
- Read all bookmarks needed for My work independently of the currently loaded transcript page. Jump must locate messages beyond that page.
- Show author and a bounded preview with access to the original. Only Lecture Help receives a mode tag.
- Keep the five stages in canonical order, with empty-state guidance. The optional No stage group follows them.
- Replace My work's automatic transcript and feedback sections with bookmarks. Coordinate with the companion Summary spec so stage feedback remains accessible.
- Prefer existing persistence facilities. Any required schema change needs an explicit tested additive migration, backup and rollback guidance before use.

## Testing Decisions

- The user approved the public HTTP and browser seams before test authoring.
- Test authenticated reader HTTP routes for star/unstar, repeat requests, owner isolation, saved stage and intent, legacy metadata, edits, removal, pagination and restart recovery. Observe results through HTTP reads.
- Test the rendered React workspace in a real browser against a disposable mock backend for message actions, bookmark-only My work, jump and highlight, mobile layout and keyboard access.
- Follow existing notebook-reader, workspace and student-journey integration tests. Tests assert external behavior and use deterministic providers and disposable data.
- Execute one failing behavioral test and its minimal implementation per cycle. Record red and green evidence before proceeding.

## Out of Scope

Instructor access, shared bookmarks, cross-notebook collections, manual stage reassignment,
automatic intent switching, new model-generated feedback and Streamlit bookmark UI.

## Further Notes

Depends on the companion Summary layout spec being complete before replacing My work.
Publish with ready-for-agent after confirming test seams. Implement each spec in
sequence and record a handoff with validation evidence before the next fresh session.

## Implementation evidence

Implemented locally on 2026-11-22. See the [validation and compatibility handoff](STARRED_MESSAGES_HANDOFF.md)
and [repeatable test instructions](../TESTING.md#starred-message-regression-31).
