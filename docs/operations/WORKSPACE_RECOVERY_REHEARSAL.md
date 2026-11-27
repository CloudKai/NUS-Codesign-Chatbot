# Complete-workspace recovery rehearsal

Ticket local47. Local, disposable, mock-only rehearsal of the documented
backup-and-restore procedure for a student's complete saved workspace. It never
touches developer or user data, never runs against production, and makes no
live recoverability claim for DSQL or AWS.

## What must be in a backup

A complete saved workspace backup covers, with every writer stopped:

| Item | Location | Why |
|---|---|---|
| Student/application SQLite store | `APP_DATABASE_PATH` (one `*.sqlite3` file per configured store) | Notebooks and settings metadata (milestone recaps, Deep Review job envelopes and completed snapshots, learning journey), messages, sources, `student_artifacts` + `student_artifact_versions`, `student_canvases` + `student_canvas_versions` — both version histories included |
| Generation admission ledger | the `ledger_path` from `GENERATION_ADMISSION_POLICY`, when configured | Conservative allowance reservations and settled charges; restoring it prevents replaying spent funding |
| Uploaded/derived files | `APP_FILES_DIR` (the `files/` tree) | Original uploaded source bytes and derived artifacts |
| Workspace exports | `APP_WORKSPACES_DIR` | Per-notebook export outputs |
| Course material sync dir | `LECTURE_NOTES_DIR` | Local lecture-note copies, when synchronization is enabled |

The SQLite backup API (`sqlite3.Connection.backup`) captures any WAL pages, so
a stopped-server file copy of the backup target is self-consistent;
`PRAGMA integrity_check` on the restored copy is part of the rehearsal.

## Rehearse it locally

```sh
.venv/bin/python -m scripts.workspace_recovery_rehearsal
```

The driver prints aggregate JSON evidence only. It allocates its own temporary
root, boots the real same-origin FastAPI/SQLite stack with the deterministic
mock provider in a separate guarded child process, and never opens a supplied
database. The rehearsal:

1. Seeds one synthetic Guest owner through public HTTP only: chat turns, an
   uploaded source, an artifact with a three-revision version history, a canvas
   with a three-revision version history, a confirmed stage transition
   (producing its milestone recap), and a completed durable Deep Review.
   Because stage completion has no public HTTP route — stage authority belongs
   to confirmed coaching turns — the child relaxes only the Deep Review
   eligibility gate; enqueue, the durable worker, snapshot persistence and
   owner fencing stay real.
2. Snapshots every public read (project with recaps/review, messages page,
   settings, learning state, sources and source bytes, both resource version
   histories with a version-body read, the Deep Review job, transcript bytes)
   and proves the snapshot stable across a real restart.
3. Performs the stopped-server backup (SQLite backup API, integrity check,
   file-tree copy) and records a table-level inventory of what the backup
   contains.
4. Makes the original stores unavailable and restores the backup into a fresh
   disposable location, then re-verifies the identical snapshot through public
   interfaces, the completed Deep Review, the owner-fenced notebook list, and
   that a second registered owner is refused (404 on every read) both before
   and after the restore.
5. Restarts the restored stack a second time and re-verifies the snapshot.

## Compatibility limits found and fixed

- **Local source relocation (fixed red-first in ticket 47):** local-provider
  uploads are stored under `files_dir/threads/<thread>/uploads`, and older
  source rows carry the absolute path written at upload time. Restoring the
  backup into a fresh location left those reads returning 400 "Source file is
  not available". `safe_source_file_path` now re-anchors a stale absolute path
  under the configured `files_dir` using the stable `threads/<thread>/uploads`
  suffix, with the same traversal containment check as any stored path. Pinned
  by `tests/http/test_source_recovery_relocation.py`. Same-location restores
  were never affected.
- Settings-blob resources (recaps, Deep Review envelopes) live in the notebook
  metadata inside the SQLite store and recover with it — no separate handling.
- Object-storage (S3) sources store relative object keys and are inherently
  relocation-safe; this rehearsal does not exercise S3.

## DSQL recovery is verified separately

Everything above is the **SQLite/local** procedure. Aurora DSQL has its own
supported recovery mechanisms (documented in the deployment runbooks), and no
DSQL restore, PITR or snapshot operation is exercised here. The rehearsal makes
no live recoverability inference from SQLite behavior; live/production recovery
exercises require separate explicit authorization and are never run against
production data. Rollback for the ticket's code change is source-only (revert
`backend/sources/projection.py`); the rehearsal itself is additive and leaves
no state behind.
