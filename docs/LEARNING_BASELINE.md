# Learning funnel and formative usability baseline

Ticket [#22](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/22).
Instrumentation is implemented. **The 5–8-student formative study and two-week
usage pilot are pending external participants.** Deterministic tests and agent
browser checks are engineering evidence, not participant observations.

## Measures and safeguards

Lecturers open Participation → Lecture help and project progression, or call
`GET /api/v1/professor/learning-funnel`. Persisted lecturer/admin authorization
and the existing fail-closed research access audit apply. Only aggregate counts,
units and limitations leave this endpoint. Use existing audited Research review
and transcript routes to inspect reasoning; this report adds no transcript export.
No student text, source text, cookies, raw owner/notebook/message identifiers,
or identity-linking fields appear in its response or new telemetry logs.

`POST /api/v1/threads/{thread}/messages/{answer}/learning-signal` accepts only
`useful`, `not_useful`, `evidence_opened`, or `recommendation_displayed`; no free
text, timestamp or client identity is accepted. The server checks notebook
ownership, active revision, assistant role and event eligibility. Welcome/error
rows are ineligible. Ratings require lecture intent, evidence requires a cited
lecture answer, and display requires a saved recommendation. Receipts are client
assertions, not independently verified reading or quality. They confer no access,
grade, or stage change.

Each answer retains at most one current rating and two first-occurrence receipts
in existing message metadata. Duplicate submissions do not inflate counts. A
changed rating replaces the previous rating and its timestamp. Recommendation
details use an explicitly opened expander so mounting a hidden mobile drawer
does not itself record display. Failed display/evidence writes do not block the
learning action; missing receipts remain unknown. Rating save failure is visible
and can be retried. There is no page-load model call or new paid service.

All measures cover **all-time active conversation branches**, not a timed cohort
or immutable event history. Revised-away/deleted work disappears from this view;
no retroactive display/feedback history is fabricated. Existing unclassified
messages remain unknown and are counted separately. There is no person-level
census: owner identities, Guest owners and notebooks are counted separately.
Multiple Guest cookies, multiple notebooks, and later account claims can change
coverage. No anonymous identities are silently joined. The enrolled class size
and study consent roster must come from the lecturer; do not divide owner counts
by an invented enrollment count or label owners as students.

| Measure | Numerator | Denominator / unit |
| --- | --- | --- |
| Rated answers | Lecture answers with an explicit current rating | All classified saved lecture answers / answers |
| Useful answers | Current rating is Useful | Rated lecture answers / answers |
| Cited answers | Saved lecture answer has a citation | Classified saved lecture answers / answers |
| Evidence opened | Cited lecture answer with an explicit citation-action receipt | Cited lecture answers / answers |
| Returned after useful | Owner has a saved student turn on a later UTC day after its current useful rating | Owners with at least one currently useful answer / owner identities |
| Framing recognized | Project starter notebook with a model recommendation to Concept generation | Notebooks with a stage-tagged project student contribution / notebooks |
| Recommendation displayed | Concept-generation recommendation details explicitly opened | Notebooks with a saved Concept-generation recommendation / notebooks |
| Confirmed | Explicit saved confirmation of that recommendation, excluding automatic advancement | Notebooks with a saved Concept-generation recommendation / notebooks |
| Subsequent Stage 2 saved-turn proxy | Saved stage-tagged student turn in Concept generation after the confirmation timestamp | Notebooks with an explicit confirmation / notebooks |

| Stage 2 saved-turn participation | Project starter notebooks with any saved stage-tagged Concept-generation student turn (unreviewed proxy) | All project starter notebooks / notebooks |
| Human-reviewed substantive Stage 2 work | Unknown (`null`), requires authorized Research assessment | Not inferred from saved turns or rubric codes |

Zero denominator means no eligible observations, never 0% success. Counts are
separate measures, not a strictly nested conversion chart: historic confirmations
can exist without an observed display, and a return can be in another notebook
owned by the same identity. Saved contributions are a **candidate-work proxy**;
substantive reasoning must be assessed through authorized human Research review.
Model recognition, provisional rubric scores and stage selections do not prove
learning. Arrival, silent visits, reading time, abandoned drafts, repeated-question
semantics and consent are not measured by this snapshot. Use the observation
sheet below for these gaps. No statistical effectiveness or retention claim.

## Reproducible comparison session

Use a new disposable mock workspace per participant and interface. Retain the
same backend fixture, selected sources, viewport, task wording and network/device
conditions when comparing Streamlit with React. Record the code SHA and fixture
version. Never replay an easier task in the second interface without recording
order effects; counterbalance interface order. Do not collect real student work
without the institution's authorized consent and handling process.

Fixture A: selected text source “Analogy notes”: “Analogy transfers a relationship
from a familiar setting to a new design problem. Compare the relationship, not
only surface features.” Project scenario: older pedestrians need enough time to
cross at a road junction. No real student names. Use deterministic mock output;
do not score its pedagogy as real-model quality. For interruptions use a controlled
local mock delay, then disconnect/reload; never create paid calls for the study.

Run each task at desktop 1440×960 and mobile 390×844; alternate which device is
first across participants. Allow normal scrolling; record extra scrolls and
misdirected taps, not just final success. A facilitator may read the task but
must record every hint. Stop or recover after two minutes of blocked interaction;
that threshold is a study convention, not an application latency target.

| Task | Student prompt / action | Success evidence | Record failure |
| --- | --- | --- | --- |
| Lecture help | Ask “What is analogy in design?” in lecture mode; explain the answer in your own words; rate usefulness only if you wish | Answer and citation visible; current project stage unchanged; missing rating remains unknown | Wrong mode, evidence gap, misunderstood answer, rating discoverability |
| Evidence access | Open the answer's citation, locate the supporting relationship, return to chat | Correct source preview, usable close, draft/transcript intact | Wrong source, hidden action, clipped preview, extra taps/scrolls |
| Project framing | Apply the idea to older pedestrians; explain affected people, context and desired outcome in your own wording | Student-authored framing saved distinctly from generated feedback | Coaching supplies artifact without student reasoning; blocked wording |
| Recommendation / confirmation | Open the coach recommendation; choose Stay here first, then on a later recommended move explicitly confirm | Separate opening and decision; stage changes only on acceptance | Hidden details, unintended move, unclear reason, unavailable pending move |
| Subsequent contribution | In Concept generation compare longer crossing time and a refuge island with reasons | Saved student contribution attributed to Concept generation after confirmation | Stage-only success with no contribution; coach text mistaken for own work |
| Resume / revisit | Reload, reopen project, find your saved problem statement and next action; revisit completed stage and return | Exact own work and historical feedback remain distinguishable; draft survives navigation | Lost draft, stale stage, generated summary mistaken for own work |
| Interruption | Submit one synthetic question with a mock delay; reload/disconnect after acceptance; reconnect and recover saved answer | Single durable answer, clear pending/recovery copy; no duplicate contribution | Duplicate turn, silent failure, lost text, indefinite spinner |
| Lecturer interpretation | Open Participation report and explain each numerator/denominator; inspect authorized Research sample | Separates useful answers, display, confirmation and candidate work; understands Guest limits | Treats owners as people or stage change as learning; denominator unclear |

A mock fixture may not naturally emit a recommendation for a participant's
wording. Record “not elicited” and use a pre-seeded deterministic pending-state
fixture for the control task; do not mark framing success or fabricate model
quality. Record separate task completion for control mechanics and reasoning.

## Observation sheet (unfilled)

For each session: consent/reference held by facilitator, opaque participant code,
date, device/viewport, interface/build SHA, fixture, interface order, facilitator.
Do not place names, email, transcripts, cookies or raw screenshots of private work
in this repository. Use authorized study storage for identifiable material.

For each task record: start/end, completed/unassisted/completed-with-help/blocked,
first wrong action, hints, visible wait/error, draft loss, citation reached,
participant's optional usefulness judgement and reason (de-identified), exact
observed defect, severity, reproduction, and suggested comparison follow-up.
Human reasoning review records evidence use, alternatives, justification and
reflection using the existing authorized Research workflow, not this count report.

| Participant | Desktop tasks | Mobile tasks | Hints / stalls | Usefulness / return observation | Status |
| --- | --- | --- | --- | --- | --- |
| P01–P08 | Unobserved | Unobserved | Unknown | Unknown | Pending recruitment; zero completed sessions |

Recruit 5–8 students across lecture-only, project starters and returning users,
including relevant mobile/accessibility needs. Report actual sample and missing
tasks. Synthesize concrete recurring defects and divergent cases; retain negative
and incomplete observations. The later two-week pilot needs its own authorized
roster and dates. This formative sample diagnoses usability and cannot establish
statistical learning, retention or adoption gains.

## Engineering baseline defects and comparison backlog

These are reproducible engineering findings, not participant findings.

- Before #22, there was no explicit usefulness control, evidence-open receipt,
  or recommendation-display receipt. A saved or cited answer could not establish
  usefulness. New HTTP TDD and UI controls provide those separate observations.
- The initial #22 report incorrectly required a display receipt to count an
  existing confirmation. `ticket22-red2.log` reproduced 0 instead of 1; corrected
  by independent confirmation counting. Keep this case in the React comparison.
- Hidden mobile panels mount on the server. Counting every banner render would
  inflate display; explicit expander opening now records details exposure.
- Existing unclassified legacy work has no reliable intent/stage assignment;
  it remains unknown. Compare both interfaces with a legacy notebook fixture.
- Existing operational metrics and automated rubric scores are not usefulness
  judgements. Missing feedback, cohort identity and study observations remain
  open measurement limits rather than invented successes.

Browser evidence and further observed defects are recorded in handoff09. No
baseline defect outside #22 is silently fixed here; later comparison tickets
must report failures against these same tasks.

## Compatibility and rollback

No schema, student data, account, source-file or environment migration. Metadata
is additive and bounded. Existing entrypoints and transcript text are preserved;
old clients omit receipts safely. DSQL uses the existing whole-transaction OCC
wrapper for the new write. Revert only the ticket commit to roll back UI/API;
retain existing message metadata and do not rewrite student history. A future
adapter must preserve atomic metadata updates and active-owner/revision checks.
