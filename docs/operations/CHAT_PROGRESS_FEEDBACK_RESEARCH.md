# Chat progress and waiting feedback

Reviewed 24 November 2026 SGT. Research and proposed behavior only; no runtime,
deployment, schema, or paid model-call changes.

The later local implementation follows this proposal with Query and Tailwind
as documented in the [frontend guide](../../frontend/README.md#query-and-styling).

## Recommendation

Use the existing React and plain CSS stack. Show the real request stage immediately
and stream reply text as soon as it arrives. An indeterminate bar is the most
accurate default because the server supplies stages, not a completed-work
denominator. If a percentage is wanted, label it **Estimated progress** and treat
it as a visual estimate, never elapsed-time evidence that the reply is almost
finished. A slower opening and quick completion can be implemented, but no clock
should independently declare success.

The current app uses React 19.2.0, Vite 7.3.8, and imported CSS; Tailwind is absent
from its package manifest, lockfile and source. This feature needs no additional
dependency. [Package manifest](../../frontend/package.json),
[CSS entry point](../../frontend/src/main.tsx),
[existing styles](../../frontend/src/styles.css).

## What the evidence supports

- **Progress semantics:** HTML defines determinate progress as the fraction of
  completed work and explicitly supports indeterminate progress while waiting
  for a remote host. Omitting the native `progress` element's `value` makes it
  indeterminate. WAI guidance says to omit `aria-valuenow` when the current value
  is unknown. A fabricated precise percentage should therefore not be exposed as
  measured completion to assistive technology.
  [HTML standard](https://html.spec.whatwg.org/dev/form-elements.html#the-progress-element),
  [WAI range guidance](https://www.w3.org/WAI/ARIA/apg/practices/range-related-properties/).
- **Perceived speed:** Harrison et al. tested 22 participants with equal-duration
  5.5-second progress bars. Accelerating curves were perceived as faster than
  linear progress; curves pausing near completion were perceived as slower.
  This supports testing a smooth ending and avoiding a long frozen 90%. It does
  not establish an optimal curve or a quantified benefit for variable-duration
  chatbot replies. The paper explicitly leaves other durations for future work.
  [Original UIST 2007 paper, pp. 116–118](https://chrisharrison.net/projects/progressbars/ProgBarHarrison.pdf).
- **AWS startup:** AgentCore provisions an isolated execution environment on a
  new session's first invocation. Idle sessions can have their compute stopped;
  a later invocation provisions new compute. These facts support conditional
  explanatory text, not diagnosing every slow reply as a cold start.
  [AWS session lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html),
  [AWS lifecycle configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html).
- **Local timings:** The eight-turn V1 comparison recorded first-visible-reply
  median 11.36 s and maximum 12.85 s for fresh sessions, versus 4.41 s and 4.99 s
  warm. These are small-sample end-to-end timings, including more than startup,
  and are unsuitable as countdown guarantees. V2's 33.99 s maximum also included
  substantial in-runtime delay. Production was restored to V1 deployment 38.
  [Measured comparison](AGENTCORE_V2_LIVE_COMPARISON.md#browser-measurements).

## Proposed behavior and copy

The existing stream distinguishes `queued`, `retrieving`, `thinking`, `saving`,
`reply_delta`, `reply_discard`, `reply_ready`, `done`, and `error`. It supplies
neither actual percentage nor a cold-start flag.
[Current event handling](../../frontend/src/Conversation.tsx),
[stream contract](../../frontend/src/stream.ts).

| Signal | Student-facing copy | Optional estimated visual progress |
| --- | --- | --- |
| Send / started | Reading your message… | Start at 10%; gently approach 65% while waiting. |
| `queued` | Waiting for a reply slot… | Keep the same bounded estimate; do not imply model work has begun. |
| `retrieving` | Looking through your sources… | Retain the bounded estimate; stage text comes from events. |
| `thinking` | Preparing your reply… | Retain the bounded estimate. |
| First `reply_delta` | Writing your reply… | Advance to 90%; show streamed text immediately. |
| Further `reply_delta` | Writing your reply… | Optionally approach 95% slowly; never infer remaining tokens. |
| `reply_discard` | Preparing your reply… | Remove discarded preview and return to indeterminate feedback, avoiding a misleading near-complete estimate. |
| `reply_ready` / `saving` | Saving your reply… | Advance to 98%, never 100%. |
| Saved `done` / confirmed durable recovery | Reply saved | Complete to 100% briefly, then remove the indicator. |

These numbers are design proposals, not measurements. Use a short CSS transition
for event-driven changes, allow fast replies to skip intermediate values, and
never delay displayed text or completion to finish an animation. The streamed
reply itself becomes the main evidence of activity after the first delta. If
the estimate sits at its cap during a long wait, continue honest stage text
instead of inventing further milestones.

Suggested secondary copy after about six seconds without visible reply text:

> A new or idle chat may need AWS to start its secure runtime before preparing a reply.

The six-second delay is a proposed disclosure threshold, not a service promise
or cold-start detector. Remove the explanation when text begins. For a continuing
wait after about 20 seconds, use **Still preparing your reply. You can stop this
request.** Show the stop sentence only while the existing stop action is available;
during saving use **Still saving your reply.** Do not promise a completion time or
claim that AWS startup is currently happening without a backend signal.

On Stop, show **Stopping…** and await the server outcome. A confirmed cancellation
shows **Generation stopped. Your prompt is kept.** Errors clear progress and show
the existing recovery/retry action; a disconnected stream uses receipt recovery
before showing success or starting another generation. Retry starts a fresh
visual estimate while retaining the existing idempotency and recovery rules.

## Implementation and verification

Keep stage and rendered estimate in React state. Keep request identity, start
time and timer handles in refs; changing a ref does not render the UI. Scope any
timer to the active request and clean it up on terminal outcomes, retry, notebook
change and unmount. React Effects run cleanup before replacement and on unmount;
Strict Mode also exercises an extra setup/cleanup cycle in development.
[React useRef](https://react.dev/reference/react/useRef),
[React useEffect](https://react.dev/reference/react/useEffect).

Prefer a labelled indeterminate native `progress` element and a separate polite
status region for meaningful stage changes. If using the decorative estimated
fill, hide that fill from assistive technology and expose the equivalent
indeterminate progress plus stage text; do not announce timer ticks or false
numeric precision. Preserve the existing reduced-motion rule and turn off
fill animation/transitions for that preference while retaining stage feedback.
Tailwind offers `motion-safe` / `motion-reduce` utilities if adopted later, but
ordinary CSS provides the same behavior without introducing Tailwind here.
[WAI progress guidance](https://www.w3.org/WAI/ARIA/apg/practices/range-related-properties/),
[Tailwind animation documentation](https://tailwindcss.com/docs/animation).

Before implementation handoff, verify mock sequences for quick completion,
long pre-text wait, long streaming, discarded preview, saving, confirmed Stop,
error, dropped connection with saved-receipt recovery, retry, and navigation.
Inspect desktop and 390 px mobile layouts, reduced motion, keyboard/screen-reader
status behavior and the browser console. No new live model calls are required
for these checks. Research-note validation: cited primary pages were fetched;
repository links and the event/package claims were checked locally. Next exact
action: implement request-scoped feedback in `frontend/src/Conversation.tsx` and
`frontend/src/styles.css`, preserving the stream and recovery contract.
