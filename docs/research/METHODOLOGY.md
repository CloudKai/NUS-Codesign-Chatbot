# Research coding methodology

## Purpose and status

The CDE2300 coach records provisional, machine-generated observations about
how students formulate prompts and demonstrate reasoning during a
conversation. These observations support reflection and human research coding;
they are not grades, diagnoses, validated psychometric measurements, or claims
about a student's underlying ability.

The coding unit is one student utterance. Only reasoning explicitly present in
that utterance may be coded. The coach reply, stage completion, response
length, writing polish, and presumed student ability are not evidence.

## Automated observation

One structured model response produces the student-facing coaching result and
an optional research observation. The two sections are validated separately.
If the research section is missing or invalid, the coaching turn is retained
and the observation is marked `uncoded` or `partial`; keyword-based fallback is
not used.

Each coded observation contains:

- exactly one dominant CLEAR strategy;
- no more than two Facione critical-thinking behaviours;
- zero or more design-ethics concepts when they are demonstrated;
- short evidence quotations resolved to offsets in the student utterance;
- a rationale and confidence value for every assigned code;
- prompt, coding, provider, and model versions.

The five CLEAR categories are:

| Code | Operational meaning |
|---|---|
| Concise | Brief and focused without unnecessary complexity. |
| Logical | Coherent structure that communicates a reasoning path or relationship. |
| Explicit | Clearly states the task, context, constraints, criteria, or expected output. |
| Adaptive | Changes or refines the approach in response to prior output or evidence. |
| Reflective | Evaluates or revises the student's own prompt, assumptions, limitations, or reasoning. |

The six Facione behaviour codes are Analysis, Interpretation, Inference,
Evaluation, Explanation, and Self-Regulation. They are occurrence codes and
are distinct from the student's cumulative 0-4 Facione Review profile.

The ethics concepts are Fairness, Privacy, Transparency, Non-maleficence (harm
prevention), and Responsibility. They are **AT-EAI-informed design concepts**,
not an administration or scoring of the validated AT-EAI self-report
instrument.

## Holistic reflection candidate

Only a contribution in the Reflection phase may produce a provisional
holistic 1-4 candidate. It uses the student's final reflection synthesis and
evidence from the active conversation branch. It is labelled
"conversation-based provisional candidate" and is not equivalent to applying
the Holistic Critical Thinking Scoring Rubric to a completed project artifact.

The original study applied HCTSR to final instructional-design project
components. This application does not silently substitute chat activity,
message counts, or stage completion for that artifact-level assessment.

## Human validation

Automated codes are immutable. Lecturers and administrators submit independent,
append-only reviews with their authenticated identity, timestamp, codes, and
rationale. They can see the automated observation before submitting. A later
review supersedes rather than overwrites an earlier review. Adjudications are
also append-only and record the adjudicator, evidence, rationale, and referenced
reviews.

Active research views exclude conversation branches superseded by a student
revision. Historical observations and reviews remain available for an
authorised audit.

For a formal study, automated coding must be evaluated against a human-coded
sample. The reference study used two trained researchers, eight hours of
framework training, 50 practice utterances to 90% agreement, weekly
calibration, Cohen's kappa of .76, and consensus resolution. Those results
describe that study; they do not validate this application's model-generated
codes.

## Research visibility and privacy

Persisted `lecturer` and `admin` roles may access attributable research records
through the protected professor API and dashboard. Attribution includes the
student's display name, email, stable internal user ID, notebook, phase, and
message timestamp. Cognito subjects, tokens, authentication claims, object
storage keys, and secrets are not research fields.

Identifiable queue, transcript, detail, and export access is itself audited.
Audit entries record the staff actor, role, action, filters, affected internal
record identifiers or counts, request ID, and time; they never duplicate
transcript or source content.

## How coding may affect coaching

Research codes do not award Facione points, complete a phase, force a stage
transition, grade the student, or mandate a coaching move that manufactures
the behaviour being measured. The coach may adapt from the current stage, the
student's reasoning, evidence gaps, assumptions, V&V concerns, project
context, and relevant ethical issues. Provisional CLEAR / Facione / ethics
labels themselves are observational only.

## Co-occurrence and co-absence

CLEAR × Facione (and ethics) co-occurrence, and co-absence of codes, are
computed only as read-only professor/research summary analytics from persisted
observations. They are not used in the live coaching loop, are not grades, and
must not be read as proof that a student lacks a skill.

Absence of Inference, Explanation, or an ethics concept on coded utterances is
an aggregate pattern, not an ability diagnosis.

## Sources and adaptations

1. C. Yang, S. Bai, and S. S. Yeung, "From Prompts to Performance:
   Investigating Students' Critical Thinking in Artificial Intelligence
   Chatbot Interactions," *2025 IEEE TALE*, DOI
   [10.1109/TALE66047.2025.11346605](https://doi.org/10.1109/TALE66047.2025.11346605).
   This supplies the student-utterance unit, one dominant CLEAR code, up to two
   Facione codes, and human-coding procedure.
2. L. S. Lo, "The CLEAR path: A framework for enhancing information literacy
   through prompt engineering," *The Journal of Academic Librarianship* 49(4),
   2023, DOI
   [10.1016/j.acalib.2023.102720](https://doi.org/10.1016/j.acalib.2023.102720).
3. P. A. Facione and N. C. Facione, *Holistic Critical Thinking Scoring
   Rubric*, California Academic Press, 1994; and P. A. Facione, *Critical
   Thinking: A Statement of Expert Consensus*, 1990.
4. Y. Jang, S. Choi, and H. Kim, "Development and validation of an instrument
   to measure undergraduate students' attitudes toward the ethics of artificial
   intelligence," *Education and Information Technologies* 27, 2022, DOI
   [10.1007/s10639-022-11086-5](https://doi.org/10.1007/s10639-022-11086-5).
5. R. A. Fabio, A. Plebe, and R. Suriano, "AI-based chatbot interactions and
   critical thinking skills: an exploratory study," *Current Psychology*, DOI
   [10.1007/s12144-024-06795-8](https://doi.org/10.1007/s12144-024-06795-8).
6. D. Lee and S. Yeo, "Developing an AI-based chatbot for practicing responsive
   teaching in mathematics," *Computers & Education* 191, 2022, DOI
   [10.1016/j.compedu.2022.104646](https://doi.org/10.1016/j.compedu.2022.104646).

The original Replit implementation, the supplied system-architecture deck, and
the supplied NUS V&V slides informed phase wording, Socratic scaffolding, and
verification/validation questions. They are design artifacts, not evidence
that the resulting automated measures are valid.
