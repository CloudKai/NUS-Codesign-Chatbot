# Course content in the React workspace

Every fill-in template under "Tools from the course" and the chips above the composer comes from the
CDE2300 notes in `lecture_notes/`. Page numbers are PDF pages. The mapping of tools to the five Thinking
Path stages is a product decision, not something the slides state. Edit `COURSE_TOOLS` in
`src/coachingContent.ts` to change it.

| Tool | Stage shown | Source |
|---|---|---|
| Job statement (WHEN I, BUT, HELP ME, SO I) | Problem identification | Week 2, p86 |
| Functional, emotional, social jobs | Problem identification | Week 2, p66-67 |
| Interview questions | Problem identification | Week 2, p74 |
| Empathy map (Says, Thinks, Does, Feels) | Problem identification | Week 3 per the course overview (Week 4, p3). Slides not in the folder, so it uses the standard four quadrants. Check against the Week 3 slides. |
| Persona (empathic title, quote, demographics, goals and frustrations, habits) | Problem identification | Week 4, p20 |
| How Might We (action, for user, so that outcome) | Problem identification | Week 7, p30, and the app's stage prompt |
| User journey map | Problem identification | Week 10, p24 |
| Creative matrix with POEMS | Concept generation | Week 7, p28-30, p52 |
| Crazy 8 | Concept generation | Week 4, p3 (named, no slide detail) |
| Powers of Ten | Concept generation | Week 8, p63-66 |
| Combine old elements | Concept generation | Week 7, p12 (Webb Young reading) |
| Metaphor or analogy (steps 1 to 4) | Concept generation | Week 9, p15-19 |
| Selection criteria | Design specification | Week 7, p56 |
| Prioritisation matrix | Design specification | Week 7, p59-60 |
| Goals, values, features | Design specification | Week 4, p30-37 |
| Riskiest assumption | Ethics & Critical Thinking | Week 8, p39 |
| Test questions | Ethics & Critical Thinking | Week 9, p31-32 |
| Prototyping plan | Ethics & Critical Thinking | Week 8, p39-40 |
| Feedback from my test | Ethics & Critical Thinking | Week 9, p34 |
| Story arc | Reflection | Week 10, p4-8 |

## Check lines added to course templates

Some templates end with one line that links the work back to evidence, using the course's own ideas: the job
statement and empathy map ask for fieldwork evidence, the persona separates fieldwork from assumptions (the course overview pairs
fieldwork with personas in Week 3), How Might We asks whether it stays open to many ideas (the app's Problem identification prompt),
and goals, values, features asks which job or goal a feature serves (Week 4, "User Goals – Why's behind the JTBD").

## Not from the lecture notes

- **Prompts with no week label:** "Who could be affected?", "What changed in my thinking?" and "What is still
  uncertain?". They follow the app's own stage prompts in `agentcore_runtime/prompts/stages/`.
- **Facione skill descriptions and tips:** written for this app. Facione is the app's own assessment model.
- **Hints, reflection after a stage move, the project summary download and the Home recap:** app features that
  do not add course content.

## Known gaps

- The Week 3 slides (Empathy Map, Fieldwork, Persona) are not in `lecture_notes/`. The empathy map uses the
  standard Says, Thinks, Does, Feels quadrants until they are added.
- "Rule of threes" (Week 10, p14) is a title slide with no readable text, so it is not included.
