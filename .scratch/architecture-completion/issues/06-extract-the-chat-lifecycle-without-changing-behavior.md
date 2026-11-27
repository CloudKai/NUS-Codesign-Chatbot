# 06: Extract the chat lifecycle without changing behavior

**What to build:** Prefactor the existing chat controller into explicit request/owner/save/recovery states, preserving NDJSON, cancellation, previews, drafts and scroll behavior.

**Blocked by:** 05: Run an existing student journey in browser CI.

**Status:** implemented and locally verified (2026-11-24 SGT, OpenCode) — pending programme-level acceptance; nothing staged, committed or deployed.

- [x] Before prefactoring, existing public journeys cover generation, cancellation, discard, ambiguous save and exact-key recovery; add missing behavioral coverage at approved seams.
  - Generation, owner-switch isolation, exact-key recovery and restart persistence were already covered by the ticket 05 slice; **cancellation, ambiguous save and discard were not covered anywhere** and are new:
    - `frontend/tests/browser/student_stop_cancels.spec.ts` — real Stop click against a paused mock workflow (`tests/browser/cancellable_stack_app.py`, mirroring the proven paused-`CoachWorkflow.run` FastAPI test): real stop route answers `stopping`, terminal `reply_discard` → 409 `cancelled` arrives, prompt kept, nothing saved, no receipt, no replay across reload.
    - `frontend/tests/browser/ambiguous_save_recovers.spec.ts` — interrupted stream + `null` receipt read (the real unsaved body): pending question with explicit actions only; explicit check recovers the saved reply; explicit discard restores the composer text.
  - All 7 specs passed before the extraction (characterization) and again after it.
- [x] One explicit chat lifecycle owns request/owner identity and compatible states rather than contradictory booleans; confirmed Query data stays separate from provisional output.
  - New `frontend/src/chatLifecycle.ts`: `useChatLifecycle` owns the request state machine (`idle → requesting → streaming → saving → checking`), the shared owner/request identity (`active`, `controller`, `lock`, `verify`), progress, preview, status, the pending receipt and its `checkedKey` recovery metadata. The former independent `watching`/`canStop`/`checking` booleans are derived from the mutually exclusive phases.
  - `frontend/src/Conversation.tsx` (193 lines smaller) keeps rendering, drafts, scaffold, feedback, evidence and review panels, and consumes the lifecycle; confirmed conversation data still arrives only through owner-scoped props while provisional preview text stays in lifecycle state.
- [x] Preserve every existing NDJSON event, no automatic generation replay, late/duplicate rejection, account-switch isolation and safety-eligible text handling.
  - `send`/`reconcile`/`stopGeneration` moved verbatim (same status strings, same event handling, same fences); the cancelled branch never reconciles or replays; late/duplicate stream events are still rejected by `stream.ts` (unit-tested); owner switch and aborts still fence late responses (owner-switch spec green).
- [x] Composer drafts, pagination, reading position and ordinary notebook/stage navigation retain their current visible behavior; the prefactor introduces no unrelated feature change.
  - Draft persistence/restore covered by the guest, cancellation and ambiguous-save specs (including reload restore); scroll/pagination code untouched; no visible copy, layout or interaction change.
- [x] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
  - Prefactor: characterization first, zero behavior change, so no red/green cycle was manufactured; new coverage used the approved browser seam with deterministic adapters only. One pre-existing test-infra break was repaired: plain `vitest run` (used by `scripts/build.sh`) had been collecting the Playwright `*.spec.ts` files since ticket 05 and failing; `frontend/vitest.config.ts` now scopes Vitest to `src/**` (30 tests / 4 files, matching the historical count).
- [x] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
  - `docs/TESTING.md` slice table and fixture-app selection documented; `docs/IMPLEMENTATION_STATUS.md` ledger entry added. No staging, commit, deployment or paid call.

## Executed evidence

| Check | Result |
| --- | --- |
| `npm test --prefix frontend` | 30 tests / 4 files pass (Vitest scoped to `src/**`; see repair note above). |
| `npx tsc --noEmit` (via `npm run build`) | Exit 0. |
| `npm run build --prefix frontend` | Exit 0 (production Vite build). |
| `npm run test:browser --prefix frontend` | **7 passed** — guest, owner-switch, restart persistence, interrupted recovery, registered, stop-cancel, ambiguous/discard. Green before *and* after the extraction. |
| `.venv/bin/ruff check tests/browser/cancellable_stack_app.py tests/browser/disposable_stack.py` | Exit 0. |
| `compileall` on the changed fixture modules | Exit 0. |
| Full mock gate `sh scripts/build.sh` | See the ledger entry. |
| Post-run leak check | No disposable-stack/uvicorn processes or listeners left on ports 8121–8129. |
