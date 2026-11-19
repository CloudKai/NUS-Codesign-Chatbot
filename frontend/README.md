# React student workspace

React serves students at `/` and keeps `/pilot/` as an alias. FastAPI owns
workspace data, evidence, and saved conversations. Use the
[local setup](../README.md#run-locally) to build with Node 22 and start the
same-origin Caddy stack. See [DESIGN.md](DESIGN.md) for layout and styles.

## Keep the browser contract

- **Authentication.** The proxy exposes specific reader and auth routes.
  FastAPI checks registered or guest identity, ownership and same-origin
  writes. Keep private responses out of caches. The browser uses cookies
  and application responses, with tokens kept out of JavaScript.
- **Turn recovery.** Lecture help and Project coaching share the NDJSON
  lifecycle and exact-key recovery. A preview is provisional until save
  completes. Stop watching leaves the server operation eligible to finish.
  Reconcile by reading the saved result with its original key. Retry the write
  only when the student explicitly asks.
- **Drafts and Review.** Scope the tab's draft and pending request to the
  verified owner and chat. Keep the composer mounted during navigation
  within the chat. Review reads saved feedback. FastAPI owns stage
  eligibility and applies a stage change after student confirmation.
- **Sources and Library.** Notebook Sources control future evidence.
  Attachments belong to the submitted turn unless added as a reusable
  source. Resolve saved citations against their original authorized evidence.
  A removed original may be unavailable even while its citation label
  remains. See [RAG architecture](../docs/RAG_ARCHITECTURE.md) for storage
  and retrieval behavior.
- **Ambiguous writes.** Refresh authoritative workspace state before further
  changes. Verify whether a notebook or upload already exists before retrying.

## Verify changes

```sh
npm run build --prefix frontend
```

Check affected browser journeys at desktop and 390 px. Include keyboard focus,
draft preservation and failure recovery when the change touches those paths.
Use the [testing guide](../docs/TESTING.md) for API coverage and the
[readiness decisions](../docs/operations/CLASSROOM_READINESS_DECISIONS.md#pilot-and-release-acceptance)
for the release criteria. The [prior React ticket history](https://github.com/CloudKai/NUS-Codesign-Chatbot/tree/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs)
records the original pilot scope.
