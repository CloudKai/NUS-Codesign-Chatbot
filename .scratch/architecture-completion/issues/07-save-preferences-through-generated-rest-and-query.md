# 07: Save preferences through generated REST and Query

**What to build:** Deliver typed preference/settings reads and writes with targeted reconciliation, identity-safe measured freshness and component/race tests.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** implemented and locally verified (2026-11-24 SGT, OpenCode) — pending programme-level acceptance; nothing staged, committed or deployed.

- [x] Preference and notebook-settings reads/writes use reviewed generated request/response/error contracts with stable operation IDs and preserved cookie renewal, origin guards and cancellation.
  - `ReaderError` moved to `backend/http/reader_workspace.py` (imported by `notebook_reader.py`, no cycle) so the four routes carry typed error models. `backend/http/reader_workspace.py` now registers stable operation IDs `readerPreferences`, `readerPreferencesUpdate`, `readerNotebookSettings`, `readerNotebookSettingsUpdate` with 401/403/404 error responses.
  - `scripts/export_reader_openapi.py` allowlist extended to eight operations; the export still fails closed on missing/untyped operations (red observed first: `ValueError: Browser contract requires a typed stable operation`), `openapi/reader.json` re-exported offline, SDK regenerated, `npm run api:check` green.
  - `frontend/src/api/client.ts` adds `readPreferences`, `updatePreferences`, `readNotebookSettings`, `updateNotebookSettings` over the generated SDK (same-origin, `no-store`, `AbortSignal`, status-only `ApiError`). Cookie renewal and origin guards stay in `currentSession`/`reader_owner`; the write frame still probes identity before and after every save.
- [x] Confirmed mutations update only relevant Query resources; verified bootstrap preferences are reused without an immediate duplicate read.
  - New `frontend/src/api/workspaceSettings.ts`: owner-fenced query/mutation option factories. A preferences save cancels superseded reads of only `['reader', owner, 'preferences']` and reconciles the confirmed response; a settings save reconciles only that notebook's key. No blanket invalidation; notebook-list refresh stays on the existing explicit `changed()` path for settings saves only.
  - `useReader.reload()` seeds the resource from the owner-verified bootstrap result (`seedPreferences`); the resource test proves `fetchQuery` then issues zero reads, and refetches once after the measured freshness expires.
- [x] Resource freshness/retention is measured and separately configured; expiry/account-switch/cross-tab and delayed response tests pass before positive retention is adopted.
  - `resourcePolicies` in `workspaceSettings.ts` configures freshness per resource (preferences 90 s / gc 5 min; notebook settings 30 s / gc 5 min — inside the approved investigation ranges) while `createReaderQueryClient` keeps zero global defaults (asserted by the existing test). Positive retention was adopted only after the lifecycle tests passed: measured-freshness expiry refetch, foreign-owner rejection, cleared-identity delayed-response fencing, and the sign-out/cross-tab path (the whole client is cleared by the existing identity reset, asserted by the component/storage tests). Same-owner cross-tab preference edits are not live-synced; they reconcile within the bounded freshness window or on the next write/navigation — recorded as a known limit.
- [x] Component tests observe save feedback and reload persistence; private Query state is never persisted to shared browser storage.
  - New jsdom/React Testing Library component suite `frontend/src/WorkspaceTools.test.tsx`: a theme save POSTs once through the generated contract, confirms "Changes saved.", applies the appearance and updates the cache without replaying a preference read; remount reuses the confirmed save with zero additional reads; `sessionStorage`/`localStorage` stay empty; a foreign-owner save answer expires the view and is never applied or cached.
  - `WorkspaceTools.tsx` now consumes the Query resources (preferences + per-notebook settings) and a shared write frame; create/remove remain on their existing routes until ticket 08 generates them, with the removed notebook's settings entry dropped on confirmed delete.
- [x] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
  - Cycles: (1) allowlist extended first → export failed closed for the intended reason → operation IDs/typed errors → green; (2) wrapper tests red on missing exports → generated wrappers → green; (3) resource tests red on missing module → keys/policies/fencing/reconciliation → green; (4) component tests red against the old read-after-write flow → Query-backed settings surface → green. No speculative tests; all deterministic mock transport.
- [x] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
  - `docs/TESTING.md` component-slice section and coverage row; `frontend/README.md` generated-contracts paragraph; `docs/operations/ARCHITECTURE_IMPROVEMENTS.md` generated-operations and freshness paragraphs; `docs/IMPLEMENTATION_STATUS.md` ledger entry. No staging, commit, deployment or paid call.

## Executed evidence

| Check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py` | 3 passed (red first for the intended reason, then green after the operation IDs). |
| `pytest tests/http/test_reader_workspace.py tests/http/test_reader_bootstrap.py tests/http/test_reader_conversation.py` | 21 passed. |
| `npm test --prefix frontend` | 48 tests / 6 files pass (7 new resource tests, 4 new component tests). |
| `npx tsc --noEmit` + `npm run build --prefix frontend` | Exit 0 (production Vite build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed** — the full ticket 05 slice is green after the WorkspaceTools refactor. |
| `.venv/bin/ruff check .` | Exit 0, "All checks passed!". |
| Full mock suite `.venv/bin/python -m pytest -q` | **3,210 passed, 1 skipped** — matches the historical count. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Post-run leak check | No disposable-stack/uvicorn processes or listeners left on ports 8121–8129. |
