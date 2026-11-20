---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/HomeView.tsx","frontend/src/StageStepper.tsx","frontend/src/CoachCheckIn.tsx","frontend/src/StageRecommendation.tsx","frontend/src/ModeSwitch.tsx","frontend/src/coachingContent.ts","frontend/src/styles.css","frontend/src/Conversation.tsx","frontend/src/ThinkingPath.tsx"]
---

# React student workspace
Mode: Operate. Scope: frontend/src, /pilot/.

## Direction contract
THESIS: A familiar chat workspace with visible learning continuity. The user
explicitly pins ChatGPT, Gemini and Codex as references; that choice overrides
the random direction assignment. Avoid the incumbent wall of form controls.

OWN-WORLD: Cool pale blue navigation, white chat, quiet blue-grey progress rail,
ink text and cobalt selected states. Workhorse sans typography, compact rail
rows, generous conversation measure, outlined reasoning prompts.

STORY: Choose a notebook, write or explore a reasoning prompt, consult sources,
and see where the student's own saved work fits in the five-stage journey.

FIRST VIEWPORT: Collapsible left navigation, flexible central chat, a compact
title row with Review, and the composer below. Review opens on the right on
desktop and in a sheet on smaller screens. Search opens from navigation.
Signature interaction: a reasoning prompt appends an editable scaffold without
discarding the draft or sending a model request.

FORM: User-pinned category-standard chat application, code-led. The seeded
assignment is acknowledged and overridden by the explicit competitor brief.
seed:ff7fd354936e258b.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## User refinement
Use icon controls where familiar, remove Streamlit links, replace prominent intent tabs
with a compact segmented mode switch, and expose a persistent day/night toggle.

Engagement update: a Home view (continue card), header stage stepper, inline stage
recommendation with milestone banner, deterministic coach check-ins, stage starter chips
and actionable feedback (Work on this, Build on this, Practice, Use in my project) are
allowed. Counts, check-ins and milestone copy must come from saved API data. Never
fabricate achievements, streaks or scores. Keep it calm: one check-in and one milestone
at a time, no modals, scaffolds only insert editable text.

Keep chat as the default. Review brings together saved summary, feedback,
Facione and stage work. A notebook's Sources tab manages shared materials.
Chats retain file attachments and citation inspection.
