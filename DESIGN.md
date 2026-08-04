# Co-design Design Specification

## 1. Product intent

Co-design is a critical-thinking companion for university students. It combines a grounded
research notebook, a conversational coach, and a visible thinking journey in one workspace.

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

Potentially consequential actions require clear confirmation. Students can choose response
length, language, theme, model, sources, and when to manually move to the next journey step.

## 3. Information architecture

```text
Top bar
├── Product identity
├── Current notebook title
├── Section switcher: Journey | Review | Chat | Sources | Notebooks
├── Guidance (Quick / Complex)
└── Profile avatar
    ├── Display name
    ├── Appearance
    ├── Language
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
| Muted surface | `#F7F9FA` | Low-emphasis controls and states          |
| Text          | `#15202B` | Primary slate copy                        |
| Muted text    | `#5B6B7C` | Supporting copy and metadata              |
| Border        | `#D5DCE3` | Soft dividers and control outlines        |
| Accent        | `#0F766E` | Teal selected states and primary actions  |
| Accent hover  | `#0D9488` | Primary-action hover                      |
| Accent soft   | `#E6F5F3` | Active stage and user messages            |
| Success       | `#15803D` | Positive status                           |
| Warning dot   | `#E11D48` | Review change notification                |


The light theme uses subtle surface contrast to clarify the workspace: quiet cool-slate side
panels frame a white discussion canvas, while teal is reserved for active states and actions.
Avoid flat all-white layouts and avoid using accent color for passive decoration.

#### Dark


| Token         | Value     | Usage                               |
| ------------- | --------- | ----------------------------------- |
| Background    | `#0e1420` | Application canvas                  |
| Surface       | `#151c2a` | Header, workspace, dialogs          |
| Muted surface | `#1a2232` | Low-emphasis controls and states    |
| Text          | `#f3f5fb` | Primary copy                        |
| Muted text    | `#a6afc1` | Supporting copy and metadata        |
| Border        | `#2b3548` | Dividers and control outlines       |
| Accent        | `#8d87ff` | Selected states and primary actions |
| Accent hover  | `#a49fff` | Primary-action hover                |
| Accent soft   | `#28285a` | Active stage and user messages      |
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



### Top bar

The top bar contains:

- Co-design identity and “Critical Thinking Companion” descriptor.
- Current notebook as the single page-level heading with an aligned edit action.
- Grouped Notebooks and New actions with no decorative space between them.
- A visible `Short` or `Long` response-detail selector.
- A compact Preferences trigger contained inside one bordered control.

Response detail remains visible because it changes the conversational experience. Language,
appearance, model, assignment context, and notebook details live in Preferences.

Inside the Preferences trigger, treat the tune icon and chevron as one compact group. Center
that group with a slight optical shift toward the chevron; do not distribute the two icons
across the full button width.

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

1. Current understanding level and explanation.
2. Discussion summary based on the student’s contributions.
3. What’s working.
4. What to strengthen, with two concrete actions.
5. Working conclusion.

Avoid:

- Repeating “1 of 6” or progress history inside Review.
- Generic praise without evidence or a next action.
- Duplicate summaries with different labels.
- Scores, charts, or analytics that do not help the student reason.



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

- Replace the three simultaneous columns with a panel switcher.
- Panels are labeled Sources, Discussion, and Thinking Path.
- Show only the selected panel.
- Hide the full brand descriptor and current notebook identity when space is constrained.
- Keep Notebooks, New, response detail, and Preferences available as compact controls.
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
| Layout and component styling          | `ui/assets/template.css` (injected via `ui/theme.py`) |
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

