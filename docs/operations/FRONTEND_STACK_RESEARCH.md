# Frontend stack for chat waiting feedback

Reviewed 24 November 2026 SGT. Research only; no dependency, runtime, schema,
deployment, or paid model-call changes.

Later that day, the user chose incremental adoption of Query and Tailwind.
The local implementation is documented in the [frontend guide](../../frontend/README.md#query-and-styling).
The manifest observations below describe the research baseline.

## Recommendation

Keep **React + TypeScript + Vite + the existing CSS** for this feature. Add a
small request-scoped progress component/hook driven by the current stream.
Tailwind and TanStack solve different problems and can coexist with React;
neither is required to make waiting feedback attractive or responsive.
This is an application-specific recommendation from the evidence below, not a
claim that one stack is universally better.

The [manifest](../../frontend/package.json) currently pins React 19.2.0,
TypeScript 5.9.3 and Vite 7.3.8; it includes no Tailwind, TanStack, Motion or
component library. [main.tsx](../../frontend/src/main.tsx) imports
[styles.css](../../frontend/src/styles.css), which already contains animation
and reduced-motion rules. Preserve the [existing design](../../frontend/DESIGN.md).

## What each option contributes

| Layer | Role and fit here |
| --- | --- |
| React hooks | Keep local phase/estimate state in a hook; use a pure reducer if transitions become complex. Effects can scope timer setup and cleanup to the active request. This already fits the app. [useReducer](https://react.dev/reference/react/useReducer), [useEffect](https://react.dev/reference/react/useEffect). |
| Plain CSS | Enough for a compact progress track, soft pulse, colour and short transitions. Extend the existing tokens and reduced-motion rules rather than adding a styling migration to this feature. [Current styles](../../frontend/src/styles.css). |
| Tailwind CSS | Utility-based styling, not request state, retrieval or streaming. Consider it for a broader redesign if the team prefers utility classes. Its Vite integration adds `tailwindcss` and `@tailwindcss/vite`; the normal CSS import includes Preflight, which resets margins, borders and other defaults. Audit existing typography, forms, Markdown and both themes if adopted. It offers `motion-safe`/`motion-reduce` variants. [Vite setup](https://tailwindcss.com/docs/installation/using-vite), [Preflight](https://tailwindcss.com/docs/preflight), [motion variants](https://tailwindcss.com/docs/animation#supporting-reduced-motion). |
| TanStack Query | Server-state cache and refetch management. Consider it when repeated GET loading across notebooks, sources and Review demonstrates a maintenance/performance problem. It does not style the progress UI or replace this app's stream protocol. Its defaults require deliberate configuration; see below. [Defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults). |
| TanStack Router | Typed navigation, nested routes, URL/search parameters and route loading. Consider when expanding bookmarkable application routes, not to animate a pending reply. [Overview](https://tanstack.com/router/latest/docs/framework/react/overview). |
| TanStack Start | A full-stack React framework with SSR, server functions and client/server builds, built on Router. This feature supplies no reason to migrate the existing Vite frontend/FastAPI boundary. Its page streaming is not a drop-in replacement for the coach's NDJSON events. [Overview](https://tanstack.com/start/latest/docs/framework/react/overview). |
| Motion | Optional if a wider interaction design needs coordinated animations. CSS is sufficient for the proposed bar. If adopted, respect both OS reduced motion and the app's saved preference; `useReducedMotion` handles the OS setting. [Motion hook](https://motion.dev/docs/react-use-reduced-motion), [app preference](../../frontend/src/api.ts). |
| Radix Progress | Optional accessible progress primitive if adopting a broader primitive set. Its component does not determine how much LLM work remains. A single waiting indicator does not justify a component-library migration. [Progress](https://www.radix-ui.com/primitives/docs/components/progress). |

## Apply the existing feedback proposal

Use the detailed [progress and startup proposal](CHAT_PROGRESS_FEEDBACK_RESEARCH.md):
an explicitly **estimated** visual moves from 10% toward 65% while waiting,
then 90% on the first visible reply delta, 98% while saving, and 100% only after
saved completion or confirmed durable recovery. These are design milestones,
not measured backend completion. Keep truthful stage text and accessible
indeterminate progress; timers must never independently declare success.

The [stream contract](../../frontend/src/stream.ts) already distinguishes
`queued`, `retrieving`, `thinking`, `saving`, `reply_delta`, `reply_discard`,
`reply_ready` and saved `done`. [Conversation](../../frontend/src/Conversation.tsx)
already handles previews, idempotency keys and read-first recovery. Preserve
these behaviours, show text immediately, discard invalidated previews and
clean up timers on completion, cancellation, error, request change and unmount.
Do not let an animation delay a fast response or keep running after failure.

Conditional copy may explain that a new or idle chat **may** need AWS runtime
startup. The present event contract has no cold-start signal, so elapsed time
cannot prove that AWS startup is happening. The linked proposal records the
V1/V2 timing evidence and the V1 rollback. None of these frontend libraries
removes AgentCore provisioning or model time to first token; any latency
improvement needs separate backend measurement.

## If TanStack Query is introduced later

Its documented defaults consider cached queries stale, refetch stale queries on
mount/window focus/network reconnect, retain inactive queries for five minutes,
and retry failed queries three times. Mutations do **not** retry by default.
[Query defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults),
[mutation retries](https://tanstack.com/query/latest/docs/framework/react/guides/mutations#retry).

For this app, start with non-generating GETs only. Key private data by verified
owner, notebook/thread and relevant conversation revision, plus pagination/filter
inputs. Configure freshness/invalidation explicitly, cancel in-flight queries
and clear private cache on sign-out or owner changes, and preserve current
owner checks before showing cached content. HTTP `cache: 'no-store'` does not
itself define a JavaScript query cache's lifetime.
[Current GET/session boundary](../../frontend/src/api.ts),
[owner revalidation](../../frontend/src/useReader.ts).

Keep coaching and summary generation behind explicit user actions; never put
a paid generation POST in an auto-refetching query. Preserve `retry: false`
for generation mutations if they are ever wrapped, and do not resume/replay
them automatically on focus, reconnect or page restoration. A lost response
still requires saved-receipt recovery before another send. Query should not
become a second owner of the stream lifecycle.
[Existing summary action](../../frontend/src/ProjectBrief.tsx),
[existing recovery](../../frontend/src/Conversation.tsx).

## Validation and next action

Verified the manifest, CSS entry point, event contract, conversation recovery,
session revalidation and summary action against the official sources above.
Local Markdown targets were checked. No application tests were run because no
runtime code changed; this note does not establish UI or latency improvements.
No migration is needed; rollback is removal of this research note and its index
link. Next: implement the agreed progress component in the existing stack, then
verify fast/slow replies, discards, saving, stop/recovery, reduced motion, both
themes and desktop/390 px layouts using deterministic mock streaming.
