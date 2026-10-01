# Co-design Design Specification

## 1. Product intent

Co-design is a critical-thinking companion for university students. It combines a grounded
research notebook, a conversational coach, and a visible thinking journey in one workspace.

The interface should help students answer three questions at any point:

1. What am I working on?
2. What should I think about next?
3. Which evidence is shaping the discussion?

The product supports student reasoning rather than replacing it. Production
coaching pedagogy lives in the AgentCore runtime; the Streamlit app remains
the student shell. Guidance should be concise, actionable, transparent, and
connected to the student’s own discussion and selected sources.

## 2. Design principles



### Focus before features

Show the controls needed for the current task. Secondary settings belong in Preferences or
contextual dialogs instead of competing with the discussion.

### Thinking is a journey

The five research-aligned design-thinking phases are persistent and easy to scan. The active phase receives
the strongest emphasis; future stages remain visible without looking disabled.

### Feedback must lead to action

Review content should summarize the discussion, identify what is working, name concrete
improvements, and provide a useful next action. Do not repeat progress indicators already
shown in the Journey view.

### Sources remain easy to reach

Students should always know whether responses are grounded in selected sources or general
model knowledge. Source selection is a first-class Library destination in the center
workspace, not a hidden setting or a permanently competing side column.

### Calm, professional density

Use thin dividers, restrained color, compact controls, and generous working space. Avoid
decorative dashboards, excessive cards, redundant statistics, and unnecessary explanatory
copy.

### Student control

Potentially consequential actions require clear confirmation. Students can choose response
length, theme, sources, and when to manually move to the next journey step.

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
Workspace
├── Left nav (collapsible)
│   ├── CDE2300 identity
│   ├── New chat
│   ├── Search chats
│   ├── Library
│   ├── Recents (rename / download / delete)
│   └── Profile and settings
├── Center
│   ├── Chat (conversation + composer)
│   ├── Search chats
│   └── Library (Sources)
└── Analyse / Thinking Path (right, collapsible)
    ├── Journey roadmap
    └── Review insights
```

Desktop uses one center destination at a time. Search and Library replace Chat in
the center pane; selecting a chat returns to Chat, and selecting an already-active
Library destination returns to Chat. Tablet and mobile keep the selected center
destination visible beneath two temporary drawers: Navigation enters from the left
and Thinking Path enters from the right.

## 4. Desktop layout

The application fills the viewport with one continuous, header-free workspace.


| Region        | Width          | Purpose                                  |
| ------------- | -------------- | ---------------------------------------- |
| Left nav      | 284 / 72 px    | Identity, destinations, Recents, profile |
| Center        | flexible       | Chat, Search, or Library                  |
| Thinking Path | flexible / 72 px | Journey guidance and actionable review |


The areas share one outer surface. Thin vertical dividers create structure without
turning each area into a floating card. The two edge regions collapse symmetrically
to icon rails; resizing between the open center and Thinking Path remains available.

### Spacing

- Page inset: `0px`
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
| Background    | `#F7F9FC` | Cool-neutral application canvas           |
| Surface       | `#FFFFFF` | Discussion, header, dialogs, and controls |
| Panel         | `#F7F9FB` | Thinking Path surface                     |
| Muted surface | `#F1F4F8` | Low-emphasis controls and states          |
| Text          | `#1F2933` | Primary slate copy                        |
| Muted text    | `#66727F` | Supporting copy and metadata              |
| Border        | `#DDE3E9` | Soft dividers and control outlines        |
| Accent        | `#179E90` | Teal selected states and primary actions  |
| Accent hover  | `#11877B` | Primary-action hover                      |
| Accent soft   | `#DFF6F2` | Active stage and user messages            |
| Success       | `#15803D` | Positive status                           |
| Warning dot   | `#E11D48` | Review change notification                |


The light theme uses subtle surface contrast to clarify the workspace: quiet cool-slate side
panels frame a white discussion canvas, while teal is reserved for active states and actions.
Avoid flat all-white layouts and avoid using accent color for passive decoration.

#### Dark


| Token         | Value     | Usage                               |
| ------------- | --------- | ----------------------------------- |
| Background    | `#0F1011` | Application canvas                  |
| Surface       | `#101112` | Main workspace and dialogs          |
| Muted surface | `#1D1F20` | Low-emphasis controls and states    |
| Text          | `#E8EAED` | Primary copy                        |
| Muted text    | `#9AA0A6` | Supporting copy and metadata        |
| Border        | `#2D3033` | Dividers and control outlines       |
| Accent        | `#39CDBA` | Teal selected states and primary actions |
| Accent hover  | `#63DECF` | Primary-action hover                |
| Accent soft   | `#123A35` | Active stage and user messages      |
| Success       | `#53c9a2` | Source-grounding status             |


The application supports `System`, `Light`, and `Dark`. Theme changes must affect the whole
experience, including messages, inputs, menus, dialogs, upload areas, disabled states, and
empty states.

Select menus render in a portal outside the workspace. Their option text, hover surface,
selected surface, border, and shadow must therefore use explicit theme tokens so Short,
Long, language, and model choices remain readable in both light and dark appearances.

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



### Application shell and sidebar

The CDE2300 mark and wordmark anchor the top of the left sidebar. New Chat,
Search chats, and Library use quiet rounded navigation rows; teal appears only
for the active destination. Recents are compact and keep rename, transcript
download, and delete in their overflow menus.

The profile avatar, display name, appearance, coaching style, notebook actions,
and logout remain anchored to the bottom of the sidebar. The same placement is
used in the mobile Chats destination. Collapsed navigation uses accessible
icon-only controls, while the collapsed right rail uses the Material Analytics
icon labeled “Analyse / Thinking Path.”

### Thinking Path: Journey

The journey contains five ordered phases:

1. Problem identification
2. Concept generation
3. Design specification
4. Ethics & Critical Thinking
5. Reflection

Rules:

- Show all stages in a vertical track.
- Expand only the active stage with its title and guidance.
- Use a filled accent number for the active stage.
- Use quiet borders and muted text for future stages.
- Present “Suggested questions” as a clear, bordered action inside the active stage.
- Opening it reveals three stage-relevant options.
- Treat those questions as view-only guidance. They never populate, submit, or otherwise
modify the discussion composer.
- Keep the five-phase track compact enough to remain fully visible in the desktop panel
without routine vertical scrolling.
- Do not show a separate phase counter; the numbered phases already communicate
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
2. Facione critical-thinking scores — six dimensions in a compact table with
   an ``n/4`` value before each Holistic rubric icon (0 not started, 1 Weak,
   2 Unacceptable, 3 Acceptable, 4 Strong): Analysis, Interpretation,
   Inference, Evaluation, Explanation, Self-Regulation.
3. Strengths — collapsed expander with one subsection per Thinking Path stage.
   Stages stay empty until coaching feedback exists, and earlier stage feedback
   is preserved.
4. Areas for improvement — collapsed expander, also grouped by stage, with
   concrete supportive next actions when available.
5. Working conclusion — collapsed expander.

Avoid:

- Repeating a phase counter or progress history inside Review. A single Deep Review eligibility caption beside Start Deep Review is not a Journey counter.
- Generic praise without evidence or a next action.
- Duplicate summaries with different labels.
- Charts, dashboards, or analytics beyond the Facione icon table.
- Quoting student prompts verbatim as the summary.
- Showing Strengths or Areas filler before the student has earned feedback.



### Discussion

The discussion is the primary workspace.

- Use the selected Recent row as the notebook title and avoid repeating it as
  a page-level heading above the discussion.
- Immediately state whether selected sources or model knowledge ground the response.
- Right-align student messages in a soft accent surface.
- Do not show a redundant student avatar; bubble alignment and surface color already
communicate authorship.
- Keep coach responses on the main surface for readability.
- Use “Coach” as the minimal assistant identity.
- Keep edit and regeneration actions contextual.
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

The library supports search, folder filtering, creating a notebook, folder management, and
opening existing notebooks.

Each notebook row includes:

- Notebook title.
- Folder.
- Current stage and stage number.
- A concise summary derived from the latest student thinking or working conclusion.
- A contextual menu for rename, move, transcript download, and deletion.

Use a two-column structure with folders on the left and notebooks on the right. When only a
few notebooks exist, retain the same structure rather than filling the dialog with decorative
content.

### Preferences

Preferences contains:

- Response language: English, 中文, Bahasa Melayu, or தமிழ்.
- Appearance: System, Light, or Dark.
- Model selection.
- Assignment context.
- Notebook details.

Use a consistent vertical rhythm in the popover: keep explanatory guidance clearly
separated from the first field, place labels close to their own controls, and leave a
distinct section gap before the next setting. Dividers separate groups but do not replace
spacing.

Changes apply to future responses. Source names, citations, proper nouns, and quoted evidence
retain their original wording when the response language changes.

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
- Keep response detail and Preferences visible.



### Tablet and mobile: `1050px` and below

- Show one compact, non-wrapping header row: Navigation, the ellipsized current
  chat name, Analyse / Thinking Path, New chat, and chat actions.
- Reuse the desktop Navigation and Thinking Path panels as full-height off-canvas
  drawers. Navigation enters from the left; Thinking Path enters from the right.
- Use one dimmed backdrop and allow only one drawer to be open at a time. Closing
  a drawer restores the exact Chat, Search, or Library view beneath it.
- Keep drawer width at `min(20.5rem, 88vw)` and use a short eased transition
  (approximately `220ms`). Disable the movement when reduced motion is requested.
- Keep rename, transcript download, and delete in chat actions. The dedicated
  Material Analytics control opens Thinking Path and carries its review-attention
  indicator.
- Preserve full-width drawer destinations, compact Recents, profile/settings at
  the bottom of Navigation, and the fixed chat composer.

Mobile controls must remain in one row at `390px` width. The current chat name
truncates with an ellipsis; icon controls never overlap or wrap.

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
- “You’re about to mark Problem identification as complete and continue to Concept generation.”



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
| Startup title/model preparation       | `ui/topbar.py` → `prepare_workspace_context()`        |
| Workspace shell and routing           | `ui/workspace.py`, `ui/panels/nav.py`, `ui/layout/`   |
| Sources library UI                    | `ui/sources.py` → `render_sources_panel()`            |
| Critical-thinking state               | `backend/student_journey.py`                          |
| Language-aware coaching prompt        | `backend/student_support.py`                          |
| Response persistence                  | `backend/chat_service.py`                             |
| Sources backend                       | `backend/source_library.py`                           |


Visual QA evidence is recorded in
`[docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)`. 

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
