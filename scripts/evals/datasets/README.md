# Retrieval question set

Labelled questions for measuring course-material retrieval (recall@4, wrong-skip, empty-result). Built from the PDFs in `lecture_notes/`. The eval script that reads these files is a separate piece of work.

| File | Purpose |
|---|---|
| `retrieval_questions.jsonl` | One JSON object per line, one question per object. |
| `course_materials.json` | Manifest of the 10 course PDFs. Maps each `material_id` to the identifiers retrieval returns. |
| `../../../tests/domain/test_retrieval_question_set.py` | Offline checks: schema, count, ids, page ranges, and that each evidence snippet is on the tagged page. |

## Question record

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `rq001` to `rq094`, unique. |
| `question` | string | Student-style question. Some are casual or lowercase on purpose. |
| `expected_material` | string | Primary `material_id` (see manifest). |
| `expected_pages` | list of int | 1-based PDF page indexes in the primary material. Non-empty, sorted, unique. One page is enough to count as a hit. Slide builds and repeated slides are listed together. |
| `alt_expected` | list of objects | Other places that answer the same question equally well, for content repeated across decks. Each entry has `material` (string), `pages` (list of int) and `evidence` (string). Usually empty (75 of 94). |
| `evidence` | string | Short verbatim snippet found on at least one of `expected_pages`. It is the page-tag proof. |
| `kind` | string | `definition`, `list`, `procedure`, `example`, `detail` or `logistics`. |
| `note` | string | How the question was derived (which slide or section). |

A retrieved chunk is a hit on the question if its material equals `expected_material` or any `alt_expected[].material`. When page information is available it must also fall in the matching `pages`.

## Page numbering

Pages are 1-based indexes into the PDF file, not the number printed on the slide or article page. They differ in these files:

- Reading 1 (HBR article): PDF page = printed page + 2.
- Week 2: printed slide numbers run 52 to 96 on PDF pages 42 to 84.
- Reading 3: printed page numbers equal PDF page numbers.

## Material names and retrieval results

`material_id` is the value `backend.retrieval.course_material_id_from_object_key` derives from the S3 object key, for example `course/lectureNotes/Week 10 Storytelling.pdf` gives `lecture_week_10_storytelling`. This is the same value used as the `course_material_id` Knowledge Base metadata attribute and in the metadata filter.

Retrieval results do not carry `course_material_id`. A `RetrievedChunk` from the Knowledge Base adapter carries `source_id` and `title`. Use the manifest to map them:

| Manifest field | Matches |
|---|---|
| `material_id` | `course_material_id` KB attribute and `RetrievalSource.course_material_id`. |
| `object_key` | `RetrievalSource.object_key` and the S3 location of a KB hit. |
| `filename` | `RetrievedChunk.title` (the source title is the file name). |
| `source_id` | `RetrievedChunk.source_id`, which is `backend.sources.library.virtual_course_source_id(object_key)`. |

`RetrievedChunk` has no page field today, so page-level scoring needs page metadata added to retrieval first. Until then score at material level. Whether the Knowledge Base returns page metadata for these PDFs has not been checked.

## Coverage

94 questions over all 10 PDFs.

| Material | Questions | PDF pages |
|---|---|---|
| Week 1 Introduction to innovation | 3 | 32 (27 have no extractable text) |
| Week 2 JTBD Framework | 14 | 88 |
| Week 4 Affinity Clusters, Product Values and Features | 8 | 83 (48 have no extractable text) |
| Week 7 Concept Generation, Prioritization, Prototyping | 16 | 92 |
| Week 8 Prototyping Plan, Metaphors, Analogy | 11 | 71 |
| Week 9 Testing, Feedback, Poster Design, Affordance, GenAI | 15 | 99 |
| Week 10 Storytelling | 6 | 27 |
| Reading 1 How Pixar fosters collective creativity | 8 | 16 |
| Reading 2 Engaging personas | 5 | 7 |
| Reading 3 A technique for getting ideas | 8 | 20 |

## How it was built

Text was extracted offline with PyMuPDF (`fitz`). Questions were written from slides and sections that have extractable text, then each tag was checked: the `evidence` snippet must appear on a tagged page after Unicode normalisation and whitespace collapse. `pytest tests/domain/test_retrieval_question_set.py` repeats that check. The test skips the evidence check if PyMuPDF is not installed.

The count of 94 is what the text supports: it spreads questions across every deck in proportion to its extractable content, and stays inside the 60 to 100 target.

## Limitations

- Image-only slides are not used. Week 1 and Week 4 are mostly images, so they have few questions. If the Knowledge Base ingestion does OCR or image parsing, questions about those slides can be added later.
- Several decks repeat the same slides (course schedule, JTBD template, prototyping types, Powers of Ten, Webb Young's five steps). These questions list the repeats in `alt_expected`. Other repeated content is not exhaustively listed, so a hit on an unlisted duplicate would count as a miss.
- Week 9 has slides where animated overlay text is extracted as one block. Tags there follow the extracted text.
- Questions are written from the slide text. They are not drawn from real student logs, so wording is cleaner than real traffic.

# Retrieval gate message set (SYNTHETIC)

**All 295 messages in `retrieval_gate_messages.synthetic.jsonl` are synthetic.** They were written by hand for this project to look like student messages. None is a real student message, none comes from logs, and wording is cleaner and more on-topic than real traffic. Every row carries `"synthetic": true`, the file name contains `synthetic`, and `tests/domain/test_retrieval_gate_message_set.py` fails if any row is not marked synthetic. The file name drops `.synthetic` only if real, anonymised messages are added later and kept in a separate file.

The set measures the retrieval gate: the logic that decides, before the model is called, whether to retrieve sources for a student message. The eval script that reads it is separate work.

| File | Purpose |
|---|---|
| `retrieval_gate_messages.synthetic.jsonl` | One JSON object per line, UTF-8. |
| `../../../tests/domain/test_retrieval_gate_message_set.py` | Offline schema, vocabulary and link checks. Does not run the gate. |

## Message record

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `gm001` onward, contiguous. |
| `message` | string | The student message. |
| `stage` | string | Thinking Path stage the notebook is in. One of `problem_identification`, `concept_generation`, `design_specification`, `deep_analysis`, `reflection` (`backend.domain.VALID_STAGE_IDS`). |
| `selected_sources` | list of `{title, filename}` | Student files already selected under My Sources before the turn. Course materials are never listed here: they are always available and cannot be selected. |
| `attachments` | list of `{title, filename}` | Files attached to this message only (`attachment_source_ids`). |
| `history` | list of `{role, text}` | Up to 2 earlier turns, `role` is `user` or `assistant`. Empty for most rows. The real gate does not read history; the field exists so follow-ups are labelled with their context. |
| `expected_decision` | `retrieve` or `skip` | What the gate should do. |
| `expected_scope` | `course`, `student_upload`, `both` or `none` | Where evidence should come from. `none` exactly when the decision is `skip`. `student_upload` and `both` need a selected source or attachment. |
| `category` | string | One of the 19 categories below. |
| `certainty` | `clear` or `borderline` | `borderline` means a reasonable reviewer could label it the other way. Report results with and without these rows. |
| `follow_up` | bool | True when the label depends on `history`. |
| `question_id` | string or null | Linked `rq...` id in `retrieval_questions.jsonl` when the message rephrases that question. Only on `retrieve` rows. |
| `expected_material` | string or null | Primary `material_id` from `course_materials.json`, taken from the linked question or set directly for week/reading rows. Only on course-scoped `retrieve` rows, and not on every one. |
| `rationale` | string | Why the label was chosen. |
| `synthetic` | bool | Always `true`. |

Labels describe what the gate *should* do, not what it does today. Many rows are expected to disagree with the current gate; that disagreement is the measurement.

## Categories

| Category | Decision | Rows |
|---|---|---|
| `course_content` | retrieve, course | 61 |
| `course_logistics` | retrieve, course | 11 |
| `named_material` | retrieve, course | 13 |
| `informal_or_multilingual` | retrieve, course | 8 |
| `mixed_project_and_course` | retrieve, course | 3 |
| `upload_question` | retrieve, student_upload | 20 |
| `attachment_question` | retrieve, student_upload | 13 |
| `upload_and_course` | retrieve, both | 12 |
| `course_with_unrelated_upload` | retrieve, course | 4 |
| `follow_up` | both outcomes | 16 |
| `greeting_thanks_chitchat` | skip | 33 |
| `procedural_ui` | skip | 20 |
| `stage_navigation` | skip | 11 |
| `stage_meta_guidance` | skip | 10 |
| `project_reasoning` | skip | 31 |
| `project_mentions_course` | skip | 9 |
| `ambiguous_generic` | skip | 9 |
| `out_of_scope` | skip | 7 |
| `not_in_course_material` | skip | 4 |

Totals: 154 `retrieve` (107 course, 35 student_upload, 12 both) and 141 `skip`. 227 rows are `clear` and 68 are `borderline`. Stages: 97 problem identification, 78 concept generation, 46 design specification, 38 deep analysis, 36 reflection. The `skip` share is higher than the real share would be if most traffic is project coaching; do not read the totals as traffic mix.

## Labelling rules

- A message that asks for course content (a concept, template, quote, figure, deadline or grading rule that is in the lecture PDFs) is `retrieve` with scope `course`, with or without words such as "lecture" or "week".
- A message that asks about the content of a selected file or attachment is `retrieve` with scope `student_upload`, with or without the file name. Any real question next to a fresh attachment counts.
- Comparing a student file with course material is `retrieve` with scope `both`.
- A course question asked while an unrelated file is selected is `course`, not `both`.
- Greetings, thanks, app/UI how-tos, stage navigation and status, "what should I do here" guidance, the student's own project reasoning, and text that only mentions a lecture in passing are `skip`.
- Bare follow-ups ("why?", "explain that more simply") are `skip` because the answer is already in history. Follow-ups that need a slide or quote again ("which slide?", "and the second quadrant?") are `retrieve`.
- General-knowledge questions and topics the lecture PDFs do not cover are `skip`. The lecture text never mentions ethics, machine learning or informed consent, and only mentions "design thinking" and "stakeholder" in passing.
- Course questions in Chinese and Indonesian are labelled `retrieve` even though the lecture PDFs are English.

## Limitations

- Synthetic, authored by one person, and not reviewed by a second labeller. `borderline` rows are the known disagreement risk.
- Course-content rows reuse topics from the 94-question file, so they cover the same lecture material and are as image-poor as that file (Week 1 and Week 4 have few rows).
- The set contains no real typos, long pasted text, or noisy traffic beyond a handful of informal rows.
- `history` is at most 2 turns and short.
- Image attachments (`Prototype photo.png`) follow the same label rule, but the real path treats image evidence as model input rather than text retrieval, so one row is `borderline`.
- Messages are evaluated as normal chat (`interaction_intent` unset or `project_coaching`). The React "lecture" path (`/lecture/stream`) forces retrieval for every message, so this set does not apply to it.
