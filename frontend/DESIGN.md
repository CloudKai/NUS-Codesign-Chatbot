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
  by the left grip onto a notebook or back to Chats. The right ellipsis
  opens Rename, Pin, Share, Delete and Move to notebook. Nested chats keep
  their history and appear in Search. Search sits between New Chat and Library.
  Its page has one title input for notebooks and chats, and a result opens the
  matching item. The keyboard shortcut focuses the same input.
- **Notebook folders:** Selecting a folder opens its full Chats list and
  shared Sources. The sidebar shows its three most recent chats and a
  link to the full list when there are more.
- **Composer:** one fixed-height, internally scrollable chat field with a compact Lecture help / Design coaching
  selector. Preserve explicit intent because only project coaching can recommend
  stage progression. Let students choose between modes. The explicit Start in chat action selects Design coaching.
- **Reasoning starters:** short labeled buttons append editable scaffolds while
  preserving existing text. Mobile shows two starters and expands the rest on request.
- **Review:** Summary shows the saved discussion summary, strengths, areas
  to improve, and recorded Facione assessments. Progression contains the
  Thinking Path, next step, stage decisions, and expandable saved work.
  Review opens on Summary unless a stage decision is pending. Coach Markdown
  renders without raw HTML or inline images.
- **Settings:** a centered page uses the Figma groups Profile, Appearance,
  Learning, and Your data. Rows align on desktop and stack at narrow widths.
  Theme, appearance switches, and default mode use owner-scoped preferences.
- **Sources and Library:** students manage shared sources in the notebook’s
  Sources tab. Chats can attach files and inspect citations. Upload and Add
  from Library lead the notebook Sources toolbar. Added sources show their
  current use state, with official course materials in a separate section.
  File rows open previews and disclose secondary actions on demand. The
  drawer title is 24px, section headings are 17px, and compact controls use
  13–14px text with 44px touch targets.
- **Recovery:** preserve actionable errors, pending-write checks, disabled states
  and unsaved streaming labels even when simplifying ordinary status copy.

## Do's and Don'ts
- Do use icons for familiar actions and text for ambiguous learning choices.
- Do preserve focus, keyboard names and reduced-motion preferences.
- Do keep stage labels and next actions authoritative to the backend.
- Don't add Streamlit links, saved-message counters or decorative status copy.
- Don't present image generation, folder CRUD or fabricated achievements as working.
