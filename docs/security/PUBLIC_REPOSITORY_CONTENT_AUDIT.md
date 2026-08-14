# Public repository content audit

**Status:** documentation only. No files were deleted and Git history was not
rewritten. Audit date: 2026-08-10 on branch `Production-RemoveData`.

## Purpose

This repository is public and currently contains teaching materials under
`lecture_notes/`. The project owner must confirm whether those materials are
permitted to remain publicly accessible on GitHub.

## Tracked lecture / reading materials (current tip)

Commands used:

```bash
find lecture_notes -type f \( -name '*.pdf' -o -name '*.PDF' \) | sort
git lfs ls-files
git ls-files 'lecture_notes/**/*.pdf' 'lecture_notes/**/*.PDF'
```

| Path | Storage form |
|---|---|
| `lecture_notes/lectureNotes/Week 1 Introduction to innovation v3.pdf` | Normal Git blob (`%PDF-1.7`) |
| `lecture_notes/lectureNotes/Week 2 JTBD Framework Term 1 2026.pdf` | Normal Git blob |
| `lecture_notes/lectureNotes/Week 4 Affinity Clusters Product Values and Features Oxymoron.pdf` | Normal Git blob |
| `lecture_notes/lectureNotes/Week 7 Concept Generation, Prioritization, Prototyping 2 Mar 2026.pdf` | Normal Git blob |
| `lecture_notes/lectureNotes/Week 8 Prototyping Plan Metaphors Analogy in Design v0.pdf` | Normal Git blob |
| `lecture_notes/lectureNotes/Week 9 Testing Feedback Poster Design Affordance GenAI.pdf` | Normal Git blob |
| `lecture_notes/lectureNotes/Week 10 Storytelling.pdf` | Normal Git blob |
| `lecture_notes/readings/Reading 1 How Pixar fosters collective creativity.pdf` | Normal Git blob |
| `lecture_notes/readings/Reading 2 engaging-personas.pdf` | Normal Git blob |
| `lecture_notes/readings/Reading 3 A-technique-for-getting-ideas-james-webb-young.pdf` | Normal Git blob |

`git lfs ls-files` returned no lecture PDF pointers on this tip. All 10 tracked
PDFs are normal Git blobs, not LFS pointers.

## Production image exclusion

`.dockerignore` excludes `lecture_notes/`. Production Compose enables
`COURSE_MATERIAL_SYNC_ENABLED=true` against shared `course/` keys so runtime
must not copy lecture PDFs into the student uploads `users/` prefix.

## Owner decision required

Before student cutover, the repository owner must choose one of:

1. **Keep public** — materials are intentionally open for this course.
2. **Remove from future commits only** — stop tracking new copies; leave history.
3. **History rewrite / takedown** — requires a separate, explicitly approved
   procedure. Do **not** run `git filter-repo`, BFG, or force-push without that
   approval.

## Safe removal procedure (do not execute without approval)

If removal/history rewrite becomes necessary:

1. Snapshot every clone and any forks that must keep a private archive.
2. Agree the exact paths and whether LFS objects must also be purged.
3. Use a reviewed filter/LFS purge plan on a dedicated branch.
4. Rotate any credentials that may have been present in history.
5. Force-push only after branch protection and collaborator coordination.

This document deliberately does not embed destructive commands.
