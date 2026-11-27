---
name: Co-design React workspace
description: A familiar chat workspace with a visible learning path.
colors:
  accent: "#4d5fb8"
  star: "#a86900"
  ink: "#171b24"
  surface: "#ffffff"
  rail: "#eceef2"
  panel: "#eff1f5"
  muted: "#636c7e"
  line: "#e0e3e9"
  selected: "#dfe3f3"
  night-accent: "#a3b8ff"
  night-star: "#f4c65b"
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

Chat waiting feedback uses a compact, theme-tinted block below the composer.
Its 5px indeterminate track has 3px ends and uses the existing accent token.
Actual operation text appears alongside the composer; there are no estimated
percentages or inferred infrastructure explanations. A 12px saved label appears
only after confirmation. Screen readers receive indeterminate progress with the
real operation, and a numerical completion value only after saving. Motion is
disabled under the OS reduced-motion preference. Saved feedback disappears
after 650ms.

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
  segmented mode switch (native radios, arrow keys). A compact 32px outlined circle inside a 44px tap target
  is centered above coach check-ins and the suggestions area (expanded or collapsed),
  directly above the textbox when those are absent. Float it over the transcript
  with an 8px visible gap to the content below; reserve no blank row. The area
  outside the button stays transparent and passes pointer interactions through.
  Only the 32px circle is opaque: three subtle animated dots while
  watching/checking, wherever the student is reading. When idle the down arrow
  appears only away from the bottom and hides upon reaching it. Transcript and
  content resizing update visibility; following stays pinned until the student
  scrolls away (with a 4px tolerance for fractional layout). It is hidden for an untouched empty
  chat. Both states scroll smoothly to the latest content and re-enable following,
  pursuing new output after the first animation ends. Transcript wheel/pointer/key
  interaction stops that pursuit. App/OS reduced motion uses an instant move. Neither
  sends, aborts or retries work. The old moving transcript dots are replaced, while
  textual status/Stop watching/recovery remain. Preserve focus while working; the
  idle button leaves the focus order when hidden. Respect reduced motion and
  retain a meaningful accessible name in both states.
  In Design coaching it names the
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
  button replaces the stepper and the old Review button. In Design coaching, when the chat has project work (saved
  student work, a completed stage or a pending recommendation) it shows compact progress such
  as "2/5 · Concept generation" (stage name hidden below 768px). One dot marks a pending stage
  decision, and the button then opens Progression. Improve my design and chats without project work show plain Review.
  The stage stepper component remains on Home's Continue card only, under the same condition.
- **Chat mode on open:** a saved chat reopens in the mode of the student's latest turn when
  saved project data shows it; otherwise Design coaching if the chat has project work, else
  Lecture help. A saved draft intent wins.
- **Inline recommendation and milestone:** in Design coaching, a pending recommendation appears after the last
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
- **Review:** Summary has three levels of detail. **Your project so far** is the
  primary full-width brief with five short labeled passages: Who and why, Problem,
  Current idea, What matters, Still to explore. Its title has no extra top margin;
  14px top padding, restrained accent labels and thin separators establish hierarchy
  without nested cards or decoration. The compact Summarise chat action uses
  a tinted button beside the title and retains a 44px target and focus tooltip.
  Unknowns use subdued explicit wording.
  The brief synthesises the entire active saved chat, not just loaded/recent turns.
  Lecture materials guide the structure; no lecture-connections block is added.
  **Stage feedback** is one flat accordion group in canonical order. Rows start
  collapsed and show actual Going well / To work on counts, or No saved feedback
  yet. Outer count phrases use the same green/yellow semantic tones as their
  expanded groups; the separator and unassessed caption remain neutral. Expanding retains independent group toggles and exact saved feedback.
  No stage progress is duplicated here. **How your idea scores** retains compact
  strongest/grow-next feedback and Practice; All six skill scores reveals the
  detailed rows and tips on demand. Scores remain feedback, not a grade.
  Missing brief generation has a live loading note; failures have an explicit
  retry. No partial, stale or unsupported summary substitutes for a complete one.
  Server-cached summaries are bound to every active message; failed attempts do
  not automatically replay on remount. Preview mode never fabricates summaries.
  Design coaching Review first opens on Progression, then remembers view and open/closed choice
  per verified owner/chat in this browser tab. Visibility changes still clear
  private content and verify the owner before restoring it. Display preferences
  contain no transcript or feedback; sign-out clears them. Close/header toggle,
  Escape and drawer backdrop dismiss Review. Jump returns to the original chat
  message. Mobile Practice/scaffold insertion keeps Review open with a draft status.
  Coach Markdown remains safe, without raw HTML or inline images.
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
- **In-place edit:** replace the original student text and action row with a text-sized
  editor in that same bubble; never duplicate the saved text below it. Measure
  the longest edited line with the field font: short bubbles start at 260px,
  longer lines widen up to the available chat width, aligned to the right. Keep the
  exact original value, a compact 52–360px automatically growing field constrained to the viewport,
  with automatic shrinking and no manual resize/expand control,
  and bottom-right bordered 44px cross/up-arrow controls inside its shared textbox
  border. Reserve a footer beneath the editable text to prevent overlap; the short
  consequence note stays below the box. Keep an accessible
  label and the short replacement/draft consequence note. Enter is a newline,
  Escape/cross cancels with focus returned to Edit, and the up arrow submits
  through the existing revision operation. Theme hover colours distinguish chat
  icons and edit actions; saved stars stay gold. Preserve the separate composer
  draft, stable edit request keys and read-first failed-save recovery.
- **Recovery:** preserve actionable errors, pending-write checks, disabled states
  and unsaved streaming labels even when simplifying ordinary status copy.
  A pending question or edit is wordless progress: bouncing dots only — no note,
  no buttons. A check that finds nothing saved returns the text to the composer
  automatically under the safety of that check, so nothing is sent twice and no
  controls are needed. A check that cannot complete keeps the receipt, keeps the
  dots, and rechecks when the chat reopens. In-progress words are suppressed
  while dots show; terminal outcomes (saved, busy, budget) still announce.
  A pending receipt is recovery state and an in-flight coach turn is recoverable
  through its persisted receipt: neither locks the workspace navigation, so the
  sidebar, other chats and New chat stay clickable while the coach is queuing,
  streaming or awaiting recovery.
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
  Design coaching Review has three tabs in this order: Progression (stages, next action, tools), Summary
  (wide project summary, stage-by-stage feedback, Facione) and My work (only messages
  the owner explicitly starred). Bookmarks keep the original saved stage and author;
  only Lecture Help has a mode tag. The five stage groups stay in canonical order,
  with counts and guidance for empty groups. The current group opens first. A
  populated No stage group follows them and starts collapsed. Stage links in
  Progression open that stage's starred messages. Each preview offers Jump to message
  and Remove star; jumps load older history if needed, close Review, focus the exact
  original and highlight it for six seconds. These controls keep 44px phone targets.
  Save failures appear inside My work as well as the Chat status. Feedback remains
  in Summary; My work does not automatically collect transcript or feedback.
  Improve my design opens directly to My work with one list of starred messages.
  Jump to message returns to the saved reply and its citations. Switching back to
  Design coaching restores the saved stage, any pending decision, and project summary export.
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

## Saved-message presentation

Saved stars use the semantic gold token (`--star`) with a solid fill in Chat and
My work, plus a subtle gold tint behind selected Chat actions. Outline vs solid,
pressed state, accessible names and colour work together. The saved-star selector
must outrank the shared pressed-action style; changing the icon fill alone leaves
it indigo. Useful-answer feedback retains its existing accent styling.

My work has one containing surface. Each stage is an accent-coloured disclosure
with a saved-count badge; expanded content is inset below it along a subtle 1px
guide. Flat message entries use author → content → actions hierarchy and fine
separators, with a larger gap before the next stage. Jump is a quiet text action;
the gold star removes that saved item. Previews are server-limited to 320 characters
and visually limited to six lines, with a height bound for nested Markdown. A
newline-heavy entry must not turn into a wall of text. Full originals remain
available through Jump. Preview links render as text so clipping cannot leave
invisible keyboard links; original chat links stay active. There are no nested
message cards or new
stage-colour legends. Named stage regions/lists and count descriptions convey
parentage without relying on colour. All stage/action controls are at least 44px.

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
