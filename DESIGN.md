# CDE2300 Design Thinking Companion — Design Specification

## 1. Product intent

The CDE2300 Design Thinking Companion is a project-development and critical-thinking
workspace for Product Design and Innovation students. It combines a grounded research
notebook, a restrained conversational coach, and a visible thinking journey in one workspace.

The interface should help students answer three questions at any point:

1. What am I working on?
2. What should I think about next?
3. Which evidence is shaping the discussion?

The product supports student reasoning rather than replacing it. Guidance should be concise,
actionable, transparent, and connected to the student’s own discussion and selected sources.

## 2. Design principles



### Focus before features

Show the controls needed for the current task. Secondary settings belong in Preferences or
contextual dialogs instead of competing with the discussion.

### Thinking is a journey

The six critical-thinking stages are persistent and easy to scan. The active stage receives
the strongest emphasis; future stages remain visible without looking disabled.

### Feedback must lead to action

Review content should summarize the discussion, identify what is working, name concrete
improvements, and provide a useful next action. Do not repeat progress indicators already
shown in the Journey view.

### Sources stay visible

Students should always know whether responses are grounded in selected sources or general
model knowledge. Source selection is part of the main workspace, not a hidden setting.

### Calm, professional density

Use thin dividers, restrained color, compact controls, and generous working space. Avoid
decorative dashboards, excessive cards, redundant statistics, and unnecessary explanatory
copy.

### Student control

Potentially consequential actions require clear confirmation. Students can choose coaching
style, theme, sources, and when to manually move to the next journey step. Model
infrastructure is configured internally and is not student-facing.

### Authentication and course transparency

The signed-out gate uses the same Source Serif wordmark, IBM Plex interface
type, teal accent, spacing, radii, and light/dark tokens as the workspace.
Credentials, account creation, confirmation, and password recovery stay in
Amazon Cognito Managed Login; never recreate password fields in Streamlit.

Before redirecting, state plainly that chatbot work is never graded and has no
association with course grades. Also explain that the companion is used for the
course and that researchers want to understand how students use it and whether
it benefits learning. Keep this notice visible but calm, not hidden in legal
copy or presented as a warning.

## 3. Information architecture

```text
Top bar
├── Product identity
├── Current notebook title
├── Notebooks
└── Profile avatar
    ├── Display name
    ├── Coaching style (Quick / Strict)
    ├── Appearance
    └── Help and support

Workspace
├── Thinking Path
│   ├── Journey roadmap
│   └── Review insights
├── Chat
│   ├── Conversation
│   └── Composer
└── Sources
    ├── Search / type / sort
    ├── Lecture Notes / Readings / My Sources
    └── Add sources
```

Desktop keeps all three workspace areas visible. Tablet and mobile use a panel switcher for
Sources, Chat, and Journey/Review. Notebooks opens as a folder-free library dialog.

## 4. Desktop layout

The application fills the viewport and uses a compact header above one continuous workspace.


| Region        | Relative width | Purpose                                  |
| ------------- | -------------- | ---------------------------------------- |
| Thinking Path | 1.05           | Journey guidance and actionable review   |
| Discussion    | 2.35           | Primary student–coach interaction        |
| Sources       | 1.05           | Grounding material and source management |


The three areas share one outer surface. Thin vertical dividers create structure without
turning each area into a floating card.

### Spacing

- Page inset: `16px`
- Header vertical padding: approximately `10px`
- Workspace top gap: approximately `10px`
- Panel padding: `16–17px`
- Standard control height: approximately `40px`
- Compact radius: `10–14px`
- Dialog radius: approximately `16px`



## 5. Visual system



### Typography

Use IBM Plex Sans for UI chrome and Source Serif 4 for the brand wordmark:

```css
"IBM Plex Sans", ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
```


| Style               | Typical size | Usage                        |
| ------------------- | ------------ | ---------------------------- |
| Notebook/page title | `18px`       | Discussion heading           |
| Panel title         | `15–16px`    | Thinking Path, Sources       |
| Body                | `14px`       | Messages and primary content |
| Supporting text     | `12px`       | Metadata, summaries, hints   |
| Micro label         | `11px`       | Counts and compact status    |


Use weight and spacing for hierarchy. Avoid all-caps section labels and oversized marketing
headings.

### Core color tokens



#### Light


| Token         | Value     | Usage                                     |
| ------------- | --------- | ----------------------------------------- |
| Background    | `#F3F5F7` | Cool-slate application canvas             |
| Surface       | `#FFFFFF` | Discussion, header, dialogs, and controls |
| Panel         | `#EEF1F4` | Thinking Path and Sources columns         |
| Muted surface | `#F7F8F9` | Low-emphasis controls and states          |
| Text          | `#15202B` | Primary slate copy                        |
| Muted text    | `#5B6875` | Supporting copy and metadata              |
| Border        | `#D7DDE2` | Soft dividers and control outlines        |
| Accent        | `#0F766E` | Teal selected states and primary actions  |
| Accent hover  | `#0D9488` | Primary-action hover                      |
| Accent soft   | `#E8F3F1` | Active stage and user messages            |
| Success       | `#15803D` | Positive status                           |
| Warning dot   | `#E11D48` | Review change notification                |


The light theme uses subtle surface contrast to clarify the workspace: quiet cool-slate side
panels frame a white discussion canvas, while teal is reserved for active states and actions.
Avoid flat all-white layouts and avoid using accent color for passive decoration.

#### Dark


| Token         | Value     | Usage                               |
| ------------- | --------- | ----------------------------------- |
| Background    | `#111416` | Application canvas                  |
| Surface       | `#171B1E` | Header, workspace, dialogs          |
| Muted surface | `#1C2124` | Low-emphasis controls and states    |
| Text          | `#EEF2F3` | Primary copy                        |
| Muted text    | `#A4ADB3` | Supporting copy and metadata        |
| Border        | `#30373C` | Dividers and control outlines       |
| Accent        | `#2BA89A` | Teal selected states and primary actions |
| Accent hover  | `#38B6A7` | Primary-action hover                |
| Accent soft   | `#19312E` | Active stage and user messages      |
| Success       | `#4FB37A` | Source-grounding status             |


The application supports `System`, `Light`, and `Dark`. Theme changes must affect the whole
experience, including messages, inputs, menus, dialogs, upload areas, disabled states, and
empty states.

Select menus render in a portal outside the workspace. Their option text, hover surface,
selected surface, border, and shadow must therefore use explicit theme tokens so choices
remain readable in both light and dark appearances.

### Shape and elevation

- Use thin borders as the default form of separation.
- Reserve shadows for dialogs and floating overlays.
- Use rounded rectangles for controls, user messages, and the active journey stage.
- Do not wrap every content section in a card.



### Icons

Use Streamlit’s bundled Material Symbols so icon size and stroke weight remain consistent.
Icons support a label; they do not replace important text except in compact mobile/header
controls with accessible names.

## 6. Core components



### Top bar

The top bar contains:

- “CDE2300 Design Thinking Companion” identity with the quiet “Product Design and
  Innovation” descriptor.
- Current notebook as the single page-level heading with an aligned edit action.
- A compact Notebooks action.
- A compact profile/Preferences trigger.

Coaching style and appearance live in Preferences so the header stays focused on
course identity and the current project. Model infrastructure remains internal.

On desktop, center the complete notebook-title group against the page viewport rather than
against its layout column. The title and edit icon share one vertical axis. Apply a
pronounced downward optical offset to the pencil glyph inside its square action target so
its visible stroke aligns with the title, without moving the target itself.

### Thinking Path: Journey

The journey contains six ordered stages:

1. Focus
2. Evidence
3. Assumptions
4. Perspectives
5. Synthesis
6. Conclusion

Rules:

- Show all stages in a vertical track.
- Expand only the active stage with its title and guidance.
- Use a filled accent number for the active stage.
- Use quiet borders and muted text for future stages.
- Keep each completed stage's own symbol and add a small green tick badge;
  completion must not replace the stage symbol with a generic check.
- When audited stage selection is enabled, let students work on any non-current
  stage. Label completed stages "Revisit this stage" and incomplete stages
  "Work on this stage"; selection alone never marks a stage complete or changes
  Facione scores.
- In an expanded inactive stage, order the content as description, Suggested
  questions, then the aligned stage-selection action.
- Start the stage list directly beneath Journey/Review; do not repeat a progress
  meter or "Current focus" heading above it. Keep the confirmation-gated Next
  control inside Journey so it never appears as a Review action.
- Present “Suggested questions” as a clear, bordered action inside the active stage.
- Opening it reveals three stage-relevant options.
- Treat those questions as view-only guidance. They never populate, submit, or otherwise
modify the discussion composer.
- Keep the six-stage track compact enough to remain fully visible in the desktop panel
without routine vertical scrolling.
- Do not show a separate “N of 6” counter; the numbered stages already communicate
position and total length.
- Align the active stage’s title, description, and suggested-question control beneath
the stage name rather than beneath its number.
- Use one clear vertical rhythm inside the active card: stage identity, guidance title,
explanation, then a full-width nested suggested-question row.
- Give the active card deliberate internal breathing room and keep every nested action
left-aligned with the guidance content; avoid centered controls that fragment the scan path.
- Do not add a separate “previous step completed” banner beneath the track; stage styling
already communicates completion and the banner displaces the next-step action.
- Show “Move to next step” below the journey.

Manual progression opens a confirmation dialog showing the current and next stages. The
stage changes only after the student confirms the primary action.

### Thinking Path: Review

Review is a focused feedback surface, not another progress dashboard.

Required sections:

1. Summary — a model-written overview of the student’s thinking (not pasted prompts).
2. Facione critical-thinking scores — six dimensions in a compact neutral table. Display
   `Not started` for 0 and `N / 4` for scores 1–4, with the original restrained rubric
   glyph beside the value. Retain the canonical Holistic rubric meaning in accessible
   text: Analysis, Interpretation, Inference, Evaluation, Explanation, Self-Regulation.
   Review reports the strongest explicit evidence demonstrated per dimension across the
   active conversation; a later brief response must not erase earlier demonstrated work.
3. Strengths — collapsed expander with one subsection per Thinking Path stage.
   Stages stay empty until coaching feedback exists, and earlier stage feedback
   is preserved.
4. Areas for improvement — collapsed expander, also grouped by stage, with
   concrete supportive next actions when available.
5. Working conclusion — collapsed expander.

Avoid:

- Repeating “1 of 6” or progress history inside Review.
- Generic praise without evidence or a next action.
- Duplicate summaries with different labels.
- Charts, dashboards, or analytics beyond the Facione score table. Facione glyphs are
  supplementary visual cues only; the numeric value and accessible rubric text remain
  authoritative.
- Quoting student prompts verbatim as the summary.
- Showing Strengths or Areas filler before the student has earned feedback.



### Discussion

The discussion is the primary workspace.

- Use the notebook title once, in the top bar, as the page-level heading. Do not
repeat it above the discussion.
- Immediately state whether selected sources or model knowledge ground the response.
- Right-align student messages in a soft accent surface.
- Do not show a redundant student avatar; bubble alignment and surface color already
communicate authorship.
- Keep coach responses on the main surface for readability.
- Use “Coach” as the minimal assistant identity.
- Keep the student-message Copy/Edit action trigger visible and discoverable;
  regeneration is not a current action.
- Anchor the composer to the bottom of the discussion area.
- Keep the empty composer compact. Let it grow with the draft until its maximum
height, then scroll vertically inside the textarea.
- Use a single vertical-ellipsis trigger for student-message actions; do not pair it
with a second dropdown chevron.

Composer placeholder:

> Ask a question or Share your thinking



### Sources

The Sources panel shows a selected count and an Add action.

Empty state:

- One quiet add icon.
- “Add your first source.”
- One sentence explaining upload, pasted text, and webpage import.

Populated state:

- Checkbox for grounding selection.
- Source title as the primary label.
- Concise metadata below the title.
- Contextual menu for preview, download, or deletion.
- Thin dividers between sources.



### Add sources dialog

The dialog contains three tabs:

- Upload
- Website
- Paste text

Upload supports drag-and-drop or browsing, lists accepted formats and limits, keeps the
submission action disabled until material is present, and explains that files stay in the
local notebook.

Website import must communicate that only safe, public webpages are supported.

### Notebook library

The current library is folder-free. It supports search, creating a notebook,
opening existing notebooks, and contextual notebook actions.

Each notebook row includes:

- Notebook title.
- Current stage and stage number.
- A concise summary derived from the latest student thinking or working conclusion.
- A contextual menu for rename, move, transcript download, and deletion.

Use a compact notebook list/card structure sized to its actual content. When
only a few notebooks exist, do not reserve a folder rail or fill the dialog with
decorative empty space.

### Preferences

Preferences contains:

- Coaching style: Quick or Strict, backed by the existing short/long behavior.
- Appearance: System, Light, or Dark.

The default appearance for a student without a stored preference is Light. Existing stored
Light, Dark, and System choices remain authoritative.

Use a consistent vertical rhythm in the popover: keep explanatory guidance clearly
separated from the first field, place labels close to their own controls, and leave a
distinct section gap before the next setting. Dividers separate groups but do not replace
spacing.

Coaching responses are English-only. Source names, citations, proper nouns, and quoted
evidence retain their original wording.

## 7. Interaction states

Every interactive component should account for:

- Default
- Hover
- Keyboard focus
- Active or selected
- Disabled
- Loading
- Empty
- Success
- Error
- Confirmation

Primary actions use the accent color. Secondary actions use the surface with a border.
Disabled primary actions use a muted surface and must not look clickable.

Destructive notebook and source actions require explicit confirmation or an intentional
enablement step.

## 8. Responsive behavior



### Desktop: above `1050px`

- Show all three workspace columns.
- Keep the current notebook identity in the header.
- Keep Notebooks and Preferences visible.



### Tablet and mobile: `1050px` and below

- Replace the three simultaneous columns with a panel switcher.
- Panels are labeled Sources, Discussion, and Thinking Path.
- Show only the selected panel.
- Hide the full brand descriptor and current notebook identity when space is constrained.
- Keep Notebooks and Preferences available as compact controls.
- Preserve full-width tap targets and avoid horizontally scrolling controls.

Mobile controls should remain usable at `390px` width. Long labels may wrap to two lines but
must not overlap adjacent controls.

## 9. Accessibility

- Maintain at least WCAG AA contrast for body text and interactive states.
- Use semantic tabs, dialogs, radio groups, comboboxes, upload regions, and buttons.
- Every icon-only action requires an accessible label or tooltip.
- Preserve visible keyboard focus.
- Do not communicate state with color alone.
- Keep touch targets close to `40px` or larger.
- Allow text to wrap without clipping when browser zoom or language length increases.
- Keep confirmation dialogs focused and provide both cancel and confirm actions.
- Respect the operating-system theme when Appearance is set to System.



## 10. Content guidelines



### Voice

- Calm
- Direct
- Encouraging without empty praise
- Specific about reasoning
- Respectful of student authorship



### Preferred patterns

- “Name the specific group, setting, or context you want to study.”
- “Choose one outcome that would show meaningful change.”
- “You’re about to mark Focus as complete and continue to Evidence.”



### Avoid

- “Great job!” without explaining what is working.
- Repeating the same progress information in multiple areas.
- Vague labels such as “Dashboard,” “Insights,” or “Studio” when a clearer task label exists.
- Fabricated evidence, citations, conclusions, or source claims.
- Long instructional paragraphs when one clear sentence or action is sufficient.



## 11. Implementation map


| Design area                           | Implementation                                        |
| ------------------------------------- | ----------------------------------------------------- |
| Layout and component styling          | `ui/assets/styles/*.css` (injected via `ui/theme.py`) |
| Shared presentation helpers           | `ui/components.py`                                    |
| Theme tokens and overrides            | `ui/theme.py` → `render_theme_css()`                  |
| Column resize / scroll / composer DOM | `ui/layout/`                                          |
| Journey                               | `ui/studio.py` → `render_journey_track()`             |
| Review                                | `ui/studio.py` → `render_learning_review()`           |
| Notebook library                      | `ui/notebooks.py` → `notebooks_dialog()`              |
| Profile / preferences                 | `ui/profile.py` → `render_profile_menu()`             |
| Top bar and section nav               | `ui/topbar.py` → `render_topbar()`                    |
| Sources library UI                    | `ui/sources.py` → `render_sources_panel()`            |
| Critical-thinking state               | `backend/student_journey.py`                          |
| English-only coaching enforcement     | `backend/application.py`                              |
| Coaching orchestration/persistence     | `backend/application.py` + repository/store adapters  |
| Workspace/source application boundary | `backend/workspace_service.py`                        |
| Source ingestion and retrieval        | `backend/source_library.py` + `backend/retrieval.py`  |


Visual QA evidence is recorded in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## 12. Definition of done

A design change is complete when:

1. The primary student task is clearer or easier.
2. Journey, Review, Discussion, and Sources remain internally consistent.
3. Light, Dark, and System modes remain readable.
4. Desktop, tablet, and mobile layouts do not overlap, clip, or create horizontal scrolling.
5. Empty, disabled, confirmation, and error states are handled.
6. Semantic labels and keyboard interaction remain intact.
7. Automated tests pass.
8. Visual QA is captured and documented.
