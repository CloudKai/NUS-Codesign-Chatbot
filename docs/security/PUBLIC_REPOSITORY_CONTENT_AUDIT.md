# Repository privacy audit

Audit date: 24 November 2026 SGT. This is a current-tree inventory and a
redistribution review queue, not permission to publish the repository or a
certificate that its history and binary contents contain no sensitive data.
The [implementation ledger](../IMPLEMENTATION_STATUS.md) owns ticket acceptance.

## Scope and method

Inspected the current bytes of all **865 tracked paths** at revision `4f12995`
on `improvement/architecture-responsiveness`, including existing uncommitted
ticket 01/02 edits. Used `git ls-files -z`, extension/size inventories, text
pattern checks that emit only rule names and path/line locations, JSON/JSONL
field/count inspection, archive member metadata and targeted provenance guides.
No raw captured messages, addresses, tokens or deployment identifiers are
reproduced here or in the [metadata inventory](../examples/security/repository-privacy-2026-11-24.json).
Group counts overlap with the binary inventory; they must not be summed as
distinct files. Newly untracked ticket 01 evidence and the local execution pack
are outside the 865-path count; they were preserved.

Never opened private `.env`, `.streamlit/secrets.toml`, developer databases,
uploaded files or ignored browser profiles. Did not deserialize learned weights,
extract PDF/slide text, inspect embedded images, traverse Git history, contact
external services or verify whether any credential is live. No Gitleaks or
TruffleHog executable is installed. Pattern checks miss encoded, split,
unrecognised and historical secrets; binary visual/OCR review remains unknown.

## Findings and owner actions

| Category and actionable location | Evidence and implication | Next action |
| --- | --- | --- |
| Course/restricted materials: `lecture_notes/lectureNotes/`, `lecture_notes/readings/` | Ten tracked PDFs, plus `lecture_notes/README.txt` (11 paths; 50,764,425 bytes total). Distribution permission is not established by this audit. Existing security guidance already flags these PDFs. | Course/content owner must establish redistribution rights before a public clone, archive or new distribution. Preserve files; any removal and any history rewrite require separate explicit authorization. |
| Course-derived evaluation content: `scripts/evals/datasets/retrieval_questions.jsonl`, `course_materials.json`, `passage_fact_labels.json` | The dataset README documents 94 authored questions with verbatim evidence snippets from the PDFs; the manifest maps ten materials. Fact labels contain questions and passage metadata. Derived excerpts remain a course-content publication concern even if PDFs are excluded from an image. | Review excerpt rights and necessity together with the corpus. Do not describe these as student logs or automatically publish them as unrestricted synthetic data. |
| Browser captures: `.playwright-cli/page-*.yml`, `brief-*-summary*.md`, `console-*.log` | 25 tracked paths: ten snapshots, five brief exports, ten logs; 128,621 bytes. Captures can hold rendered work, notebook identifiers and request locations. Text checks found no email or credential-term matches in this group; all 911 extracted URLs lack query/fragment components. 772 URLs are loopback, 139 use another hostname. This does not prove provenance, consent or absence of personal content. | Review capture provenance and necessity before sharing. Prefer new disposable synthetic captures outside the checkout. `.gitignore` already ignores this directory but does not remove tracked files. Preserve existing captures pending an owner decision. |
| Historical development/evaluation evidence: `.agents/tasks/` | 140 tracked paths; 9,371,499 bytes, including reports, training/evaluation text, before/after stdout/stderr and a learner ZIP. Rule locations in the inventory identify contact/author metadata and operational locators, e.g. `phase1-review.md:6`, `phase4-2026-11-19.md:433`, `phase3b-2026-11-19.md:227` and `phase3d-work/typed-decisions.json:534`. No private values are copied. | Review author/contact metadata, prompts/replies, course excerpts and release details for necessity and provenance before redistribution. Keep historical benchmark data distinct from student research data and current live state. Do not run historical training/live commands during review. |
| Research/student-like fixtures: `scripts/evals/datasets/`, `tests/fixtures/`, HTTP/browser test fixtures | Eleven dataset paths and three fixture JSONs inventoried. The dataset guide explicitly identifies the 295 gate messages as authored synthetic examples and the 94 retrieval questions as derived from slides rather than student logs. The Sol-teacher README declares synthetic messages and single-author evaluation. This supports those declared fixtures, not every captured artifact. | Retain documented synthetic fixtures unchanged. Any later real participant/research material needs consent/provenance review and restricted storage, never automatic substitution into public fixtures. No approved replacement target was identified in this ticket. |
| Configuration/operational metadata: `.env.example:226`, `scripts/deploy_ecr.sh:6`, `docs/deploy/AWS_STATELESS_EC2.md:544`, `docs/RETRIEVAL_EVAL.md:699`, `.agents/tasks/phase4-work/item5-notes.md:50` | Tracked templates, scripts and historical docs contain deployment/service locators and account-shaped identifiers; these are not proof of credentials. `.streamlit/secrets.toml.example` has placeholders. Private `.env`, real Streamlit secrets, `data/`, `.files/` and `output/` have no tracked paths in this inventory. | Review operational disclosure before wider publication. Ticket 04 must distinguish recorded identifiers from verified deployment state without copying secrets into its manifest. No rotation or live configuration change is authorized here. |
| Binary provenance: `.agents/tasks/phase3d-work/sol-teacher/sol-learner.zip`, `docs/CDE2300_Design_Thinking_Companion_System_Documentation.pptx` | ZIP metadata shows two members (JSON and NPZ weights), 1,370,066 expanded bytes. The slide deck has 76 members including one PNG and embedded fonts. Contents, speaker notes, image pixels, weight memorisation and distribution rights are not certified. Other binaries are ten PDFs, favicon PNG and three font assets. No standalone tracked screenshots or audio/video/HAR recordings were found. | Owner must review the deck and learner provenance before redistribution. Do not load opaque weights or infer safety from file names. Binary review is an outstanding publication gate, not an application failure. |
| Image build context: `Dockerfile` final `COPY . .`, `.dockerignore` | `docs/`, `lecture_notes/`, private `.env` variants (with `.env.example` explicitly allowed), real secrets, databases and `*.log` are excluded. `.agents/`, `.playwright-cli/` and `.scratch/` are not excluded as directories; their eligible text, YAML and ZIP artifacts can therefore enter the build context/final copy. Git ignore rules do not control Docker copying. No image was built or inspected in this audit. | Before a release, explicitly review context contents and allowlisted packaging. Do not assume hidden directories are excluded. Coordinate any packaging change with ticket 04/51 and verify it independently; this audit changes no runtime packaging. |

## Credential and session checks

Across tracked text, private-key headers, AWS access-key IDs and JWT-shaped
tokens had **zero matches**. The provider-token rule matched only the deliberate
fake-secret constant at `tests/http/test_security_readiness.py:773`; the public
HTTP regression checks that server/provider errors and logs do not echo it.
Retain this synthetic fixture. No active credential exposure was confirmed;
credential validity was not tested.

Broader heuristic results were 24 files/95 line locations for email shapes,
52/99 for AWS/account/endpoint shapes and 31/65 for credential-assignment shapes.
These include author metadata, deployment references, example/test literals and
source-code variable assignments. They are review candidates, not counts of
people, sessions or leaked credentials. Exact path/line candidates are in the
metadata inventory; no matched values are retained there. These rules do not
exclude arbitrary opaque session credentials, so a zero JWT count is not a
claim that all captures are session-free.

## Validation and safe repetition

Read-only inventory commands (run from the repository root):

```sh
git status --short --branch
git ls-files -z
git ls-files '*.log' '*.har' '*.png' '*.jpg' '*.webm' '*.mp4' '*.jsonl' '*.pdf' '*.pptx' '*.zip'
git ls-files .env .streamlit/secrets.toml data .files output
git check-ignore --no-index .playwright-cli/page-2026-11-22T11-26-55-276Z.yml .env .streamlit/secrets.toml data/privacy-probe.db
```

Do not `cat` suspected secrets/captures into a terminal transcript or attach raw
scan output. For a repeat content scan, read only the tracked manifest and emit
rule names, counts and path/line locations; exclude binaries from text claims.
The temporary audit implementation and complete starting hashes are at
`/private/tmp/ticket03-audit.py` and `/private/tmp/ticket03-inventory.json` on
the audit machine. Those temporary paths are not portable release artifacts;
the checked-in metadata inventory is the durable redacted evidence.

Existing deterministic public checks used for this audit:

```sh
.venv/bin/python -m pytest -q -o addopts='' tests/http/test_security_readiness.py tests/domain/test_retrieval_question_set.py tests/domain/test_retrieval_gate_message_set.py tests/scripts/test_extra_messages.py
sh scripts/build.sh
```

Executed outcomes and logs belong to the ticket 03 entry in the implementation
ledger. These checks verify application/fixture contracts, not repository
publication rights or live security. No new test seam or behavior change was
needed; no synthetic failing test was fabricated.

## Preservation and release decision

No tracked artifact, history, credential, application setting or schema was
deleted, untracked, rewritten, rotated, migrated or replaced. This ticket adds
documentation and redacted evidence only. Rollback consists of reverting just
these audit-document changes; there is no data rollback.

Before redistribution, the owner must resolve course/excerpt permissions,
capture/research provenance, author/operational disclosure and binary review.
If an active secret is later confirmed, report only its category/location to
the owner and obtain explicit authorization for rotation and any history
remediation. Do not broaden the local audit's acceptance into a public release
or live protection claim. Existing copies/history remain relevant even after
any separately approved current-tree removal.
