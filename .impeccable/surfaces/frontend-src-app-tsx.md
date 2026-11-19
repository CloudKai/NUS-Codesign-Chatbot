---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/styles.css","frontend/src/Conversation.tsx","frontend/src/ThinkingPath.tsx"]
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
Use icon controls where familiar, remove Streamlit links and saved-message counts,
replace prominent intent tabs with a compact composer selector, and expose a
persistent day/night toggle. No extra informational copy in the chat.

Keep chat as the default. Review brings together saved summary, feedback,
Facione and stage work. A notebook's Sources tab manages shared materials.
Chats retain file attachments and citation inspection.
