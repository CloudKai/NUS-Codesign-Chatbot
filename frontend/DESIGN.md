---
name: Co-design React workspace
description: A familiar chat workspace with a visible learning path.
colors:
  accent: "#4d5fb8"
  ink: "#171b24"
  surface: "#ffffff"
  rail: "#eceef2"
  panel: "#eff1f5"
  muted: "#636c7e"
  line: "#e0e3e9"
  selected: "#dfe3f3"
  night-accent: "#a3b8ff"
  night-surface: "#292f3c"
  night-rail: "#17191e"
  night-panel: "#222b3b"
  night-ink: "#f2f4f8"
  night-muted: "#a0aabe"
  night-line: "#394253"
  night-selected: "#34405f"
typography:
  body:
    fontFamily: "Inter, IBM Plex Sans, sans-serif"
    fontSize: "15px"
    lineHeight: 1.5
  message:
    fontFamily: "Inter, IBM Plex Sans, sans-serif"
    fontSize: "16px"
    lineHeight: 1.65
  title:
    fontFamily: "Inter, IBM Plex Sans, sans-serif"
    fontSize: "34px"
    letterSpacing: "-0.02em"
rounded:
  control: "8px"
  panel: "12px"
  composer: "16px"
spacing:
  tight: "8px"
  normal: "16px"
  section: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
  composer:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.composer}"
    padding: "8px"
---
# React design system

## Overview
A chat-first student workspace based on the CDE2300 Co-Design Learning Platform Figma export. Compact navigation, a generous conversation column and a visible
Thinking Path support everyday study. This file governs the React workspace at `/` and its `/pilot/` alias;
the root design guide continues to govern the existing Streamlit surface.

## Colors
Slate navigation and progress panels frame the pale conversation. Indigo identifies actions and selection. Night mode uses blue-grey surfaces and
pale blue actions. Light, Dark and System are saved account preferences. The
header sun/moon control switches Light/Dark through the existing preferences API.

## Typography
Locally bundled Inter is the UI and conversation face, with IBM Plex Sans as fallback.
Message bodies and the composer use 16px type. Messages use 1.65 line height within a 740px column. Primary mobile controls have 44px touch targets.

## Layout
Desktop uses a 236px collapsible navigation panel and a flexible conversation
column. Review opens on the right when requested. Below 1024px, Review opens
as a modal sheet and navigation opens as a temporary drawer. Below 768px the
navigation rail gives way to a header button. Opening Review or visiting Search
preserves the mounted draft.

## Elevation & Depth
Flat surfaces and one-pixel borders separate primary regions. Drawer shadows
indicate temporary overlap. The composer uses a border and a soft shadow.

## Shapes
8–12px control corners, a 16px composer, and a compact square Send action. Numbered
stage markers express actual ordered stages, never invented scores or rewards.

## Components
- **Icon actions:** consistent 1.6px SVG strokes; title and accessible name are
  required. Copy, edit, feedback, sources, panel toggles, theme and send use icons.
- **Navigation:** New Chat opens a standalone conversation. The plus button beside
  Notebooks opens the centered Create a notebook dialog. Chats can be dragged
  by the left grip onto a notebook or back to Chats (grips and the Ctrl K hint are
  hidden on touch screens). The right ellipsis opens Rename, Pin, Share, a per-chat
  Response detail (Concise / Detailed), Delete and Move to notebook. Nested chats keep
  their history and appear in Search. Search sits between New Chat and Library.
  Its page has one title input for notebooks and chats, and a result opens the
  matching item. The keyboard shortcut focuses the same input.
- **Notebook folders:** Selecting a folder opens its full Chats list and
  shared Sources. The sidebar shows its three most recent chats and a
  link to the full list when there are more.
- **Composer:** one fixed-height, internally scrollable chat field with a two-option
  segmented mode switch (native radios, arrow keys). In Design coaching it names the
  current stage. Preserve explicit intent because only project coaching can recommend
  stage progression. The explicit Start in chat action selects Design coaching.
- **Home:** shown when no chat is open and from the Home navigation item. Greets the
  student, offers one Continue card for the most recent chat and up to three recent rows.
  Chats without a saved preview (empty, untitled) are never listed. When the chat has project
  work the card shows the stage stepper and strongest and next-to-grow skills. A pending
  stage decision replaces the next-action text with "Ready for {stage}?" and Move on / Stay
  here, which use the in-chat resolve endpoint and lock rules.
  With no chats it explains the five stages and offers Start my design project and
  Ask a lecture question.
- **Chat header:** the title is a breadcrumb inside a notebook ("Notebook › Chat"; the notebook
  part opens the notebook and truncates first), so there is no separate folder row. One Review
  button replaces the stepper and the old Review button. When the chat has project work (saved
  student work, a completed stage or a pending recommendation) it shows compact progress such
  as "2/5 · Concept generation" (stage name hidden below 768px). One dot marks a pending stage
  decision, and the button then opens Progression. Chats with no project work show plain Review.
  The stage stepper component remains on Home's Continue card only, under the same condition.
- **Chat mode on open:** a saved chat reopens in the mode of the student's latest turn when
  saved project data shows it; otherwise Design coaching if the chat has project work, else
  Lecture help. A saved draft intent wins.
- **Inline recommendation and milestone:** a pending recommendation appears after the last
  message with Move to / Stay here. A milestone banner appears only after a confirmed move
  that the refreshed project confirms, or when all stages are observed complete.
- **Coach check-ins:** one deterministic card above the composer chosen from saved data
  (returning after 24 hours, no work in stage, last review item, skill to grow). No model
  call, never saved as a message, dismissal kept per chat for the tab session.
- **Stage starters:** up to three chips for the current stage in Design coaching while the
  composer is empty. All scaffold buttons (chips, Work on this, Build on this, Practice,
  Use in my project, check-in actions) insert editable text through one helper and never send.
- **Reasoning starters:** short labeled buttons append editable scaffolds while
  preserving existing text. Mobile shows two starters and expands the rest on request.
- **Review:** Summary shows the saved discussion summary, strengths and areas to improve
  (each item has Build on this / Work on this), and "How your idea scores": Facione
  scores as feedback, not a grade, with strongest skill, skill to grow and Practice.
  Progression contains the Thinking Path, next step, stage decisions, and per-stage
  saved work with real contribution counts. Feedback items name their stage only when it is
  not the current one. Strongest skill is one compact line; Grow next is a full-width row.
  Review opens on Summary unless a stage decision is pending. Coach Markdown
  renders without raw HTML or inline images.
- **Settings:** a centered page uses the Figma groups Profile, Appearance,
  Learning, and Your data. Rows align on desktop and stack at narrow widths.
  Theme, appearance switches, and default mode use owner-scoped preferences. Per-chat
  response detail lives in the chat's ⋯ menu, not here.
- **Sources and Library:** students manage shared sources in the notebook’s
  Sources tab. Chats can attach files and inspect citations. Upload and Add
  from Library lead the notebook Sources toolbar. Added sources show their
  current use state, with official course materials in a separate section.
  File rows open previews and disclose secondary actions on demand. The
  drawer title is 24px, section headings are 17px, and compact controls use
  13–14px text with 44px touch targets.
- **Recovery:** preserve actionable errors, pending-write checks, disabled states
  and unsaved streaming labels even when simplifying ordinary status copy.
  A pending question or edit offers Check saved answer, Retry same question and Discard and edit.
  Retry and Discard unlock only after a check finds no saved reply, so nothing is sent twice. Discard
  puts the text back in the composer under a new key, which frees a question the server rejects for good.
  Start my design project and Ask a lecture question on Home also set the mode of an empty chat that is
  already open. Transcript recovery, edit and citation buttons, the mode switch, suggestion chips, the wordmark and
  the drawer's section, Settings, Refresh and Sign out controls keep 44px targets below 768px. Request keys use
  `crypto.randomUUID` when it exists and a `getRandomValues` UUID on plain-HTTP origins, so sending never throws.
  A newer Review status replaces the short "Project summary downloaded." note.

- **Course tools:** stage chips above the composer and the "Tools from the course" list in
  each opened Review stage insert fill-in templates taken from the CDE2300 lecture notes:
  job statement (WHEN I, BUT, HELP ME, SO I), persona, How Might We, creative matrix with
  POEMS, Crazy 8, Powers of Ten, selection criteria, prioritisation matrix, goals, values and
  features, prototyping plan, test questions and the story arc. Each shows the lecture week.
  In an opened Review stage the list stays folded behind a "Tools from the course" button.
  Review has three tabs in this order: Progression (stages, next action, tools), Summary
  (strengths, areas to improve, Facione) and My work (the whole journey, stage by stage in order: every
  entry the student shared with its full text, the coach summary, and what is going well or to work on).
  Each stage folds and shows a status badge (Done, Current, Started, Not started) and its entry count. The current
  stage opens first, "Expand all" opens the rest, and the "Your work" link on a stage in Progression opens that stage here.
  One-word commands such as "move" and an unedited "I want to practise …" starter are not listed
  as work (`isStudentWork` in `coachingContent.ts`), so the lists stay short as the chat grows.
  Do not add frameworks that are not in the notes. The empathy map is included at the owner's
  request. The Week 3 slides are not in `lecture_notes/`, so it uses the standard Says, Thinks,
  Does, Feels quadrants (see `COURSE_CONTENT.md`).
- **Hints and reflection:** the **Hint** button beside Send inserts one request: the student
  notes what they tried, and asks for one question back and a lecture tool if one fits,
  never the answer. Templates and hints never ask the coach to do the student's thinking.
  After a confirmed stage move, the milestone banner offers an optional **Add a
  reflection**. Everything inserts editable text and never sends. The row shows two chips
  plus the hint chip, scrolls sideways on phones, and hides while a check-in or milestone
  is showing so only one prompt competes for attention at a time.
- **Scaffold insertion:** an empty draft or an untouched earlier scaffold is replaced.
  Words the student typed are kept and the scaffold is added below them.
- **Home recap:** the Continue card quotes the student's latest saved contribution
  under "You last shared".
- **Project summary:** the Review header has a download button that saves a Markdown
  copy of the summary, strengths, areas to improve, scores and each stage's work.
  It is built in the browser from the project view; nothing is invented.

## Do's and Don'ts
- Do use icons for familiar actions and text for ambiguous learning choices.
- Do preserve focus, keyboard names and reduced-motion preferences.
- Do keep stage labels and next actions authoritative to the backend.
- Don't add Streamlit links or decorative status copy.
- Contribution counts, check-ins and milestone copy are allowed when derived from saved API data.
- Don't present image generation, folder CRUD or fabricated achievements (invented streaks,
  badges, scores or milestones) as working. Keep at most one check-in and one milestone visible.

## Workspace layout and panel sizing

`src/workspaceLayout.tsx` decides where the sidebar and Review sit. It uses the window width and the
saved panel widths, not one fixed breakpoint. The chat column stays at 600 px or wider while panels are docked.

1. **Room for everything:** full sidebar and Review sit beside the chat.
2. **Review would squeeze the chat:** the sidebar becomes a 60 px icon rail first. The saved preference stays
   "expanded", so the full sidebar returns when Review closes or the window grows.
3. **Still too narrow:** Review shrinks toward its 320 px minimum. The saved width is never overwritten.
4. **Still no room:** Review becomes a dismissible right-hand drawer (tablet, 768 px and wider) or a full-screen view
   (phones, under 768 px). Click the dimmed page or press Escape to close it. The sidebar is then as it would be with Review closed.
5. **Sidebar without Review:** docked when `width - sidebar >= 600`, otherwise a rail. The expanded list opens as an overlay drawer
   from the rail or, on phones, the header menu. Escape and the backdrop close the overlay.

**Drag handles** (`ResizeHandle`) sit on the sidebar's right edge and Review's left edge. They exist only while that panel is docked and expanded.
Pointer drag updates the width live inside the limits (sidebar 200 to 360, Review 320 to 640) and never takes the chat below 600 px. Arrow keys
move 16 px (Shift: 64), Home or double-click resets to the defaults (236 and 380). The handle has `role="separator"` with
`aria-valuenow`, a visible hover and focus state and a 14 px hit area. Widths and the user's collapse choice are stored in
`localStorage` under `codesign-layout:v1`. Collapsing the sidebar yourself is remembered. Automatic collapsing is not.
