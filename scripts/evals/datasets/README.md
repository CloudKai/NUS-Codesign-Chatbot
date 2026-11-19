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
