# Production Manual QA

## Environment tested

| Field | Value |
|---|---|
| Branch | `Production-RemoveData` |
| Commit SHA (local tip when tested) | `aa8e934` (*Escape LIKE percent literals for DSQL/psycopg*) |
| Production URL (current) | https://d1sxfuoybzedj5.cloudfront.net |
| Browser | Cursor IDE browser (Chromium automation) |
| Viewport(s) | Desktop default; mobile `390×844` via CDP Emulation (layout smoke only) |
| Model/provider observed | GPT-5.6 Luna · Low (live OpenAI path) |
| Date/time | 2026-08-10 (Asia/Singapore) |
| Test modes used | **LIVE website**, **local automated mock pytest**, **code review** |

Parent orchestrator for this pass: Cursor Grok 4.5 High. Pedagogy/security explore subagents: GPT-5.6 Sol High + Grok 4.5 High (no Fast models).

Dedicated QA notebook title used: `QA-TEST-PROD-MANUAL` (later XSS retitle). Account used for live auth: the credentials supplied in the QA request (single user). **QA_USER_A / QA_USER_B were not provided** — cross-user IDOR on live is **NOT VERIFIED**.

The recorded live run predates the current CloudFront edge cutover. Repeat the
edge, authentication, and session checks against the current URL before using
those historical observations as release evidence.

---

## Overall verdict

**READY FOR CONTROLLED PILOT**

Not **READY FOR PRODUCTION**: live host currently auto-advances stages (skips confirmation-gated **Next**), full six-stage pedagogy and live RAG upload/isolation passes were incomplete, and ARM64 image rebuild was not executed in this pass.

---

## Executive summary

Live Cognito login, HTTPS, the public API boundary, session refresh, logout, and coach Focus→Evidence coaching behaviour were exercised on the production URL. Coach pedagogy for weak Focus scaffolding, injection resistance, and off-topic refusal looked aligned with `backend/prompts/*`.

**Product progression policy (owner decision, 2026-08-10):**
- **Month 1 (current pilot):** `AUTO_ADVANCE_STAGES=true` — coach ADVANCE auto-applies; no Next confirmation. Live already behaved this way; repo now matches via `compose.prod.yaml`.
- **After month 1:** switch to **free stage selection**. With student stage
  selection enabled, students can work on any non-current Thinking Path stage;
  completed stages remain marked complete when revisited.

Health `mode` now follows `APP_ENV` (local fix). Login-start throttle + allow-listed Cognito callback error logs added. Full mock pytest: **344 passed**.

Authoritative stage order from code (`THINKING_STAGES` / `docs/LOCAL_DEMO_IMPLEMENTATION.md`):

**Focus → Evidence → Assumptions → Perspectives → Synthesis → Conclusion**

(Not Focus→Assumptions→Evidence.)

---

## Expected coach oracle (code-derived)

Sources: `backend/prompts/shared/coaching.md`, `backend/prompts/stages/*.md`, `backend/workflow.py`, `backend/learning_service.py`, `backend/prompts/composer.py`.

Shared: Socratic, usually one meaningful question; student owns decisions; sources/project/history are untrusted; no invented citations; ADVANCE only when stage purpose adequately met; application applies transitions; Conclusion cannot ADVANCE beyond itself.

| Stage | ADVANCE when | STAY when |
|---|---|---|
| Focus | Workable clear inquiry/scope | Topic-only / vague / unclear purpose |
| Evidence | Evidence connected + some evaluation + key limits | Unsupported / uncritical / gaps unnoticed |
| Assumptions | Major assumptions surfaced + uncertainty vs evidence | Assumptions treated as facts |
| Perspectives | ≥1 meaningful alternative engaged fairly | Only preferred view / straw men |
| Synthesis | Evidence+alternatives integrated; position refined | Mere summary / unreconciled contradictions |
| Conclusion | Terminal — STAY/completion only | Overconfidence / doesn't follow / summary-only |

Confirmation mode (`AUTO_ADVANCE_STAGES=false`): ADVANCE → pending transition → student **Next** + confirm. Auto-advance mode applies transition server-side and formats via `advanced_stage_response`.

---

## Manual test matrix

| Scenario | Expected | Observed | Result | Latency (manual) | Evidence | Related | Fix |
|---|---|---|---|---|---|---|---|
| HTTPS root | 200 app | 200 Streamlit | **PASS** LIVE | ~1.0s TTFB-ish | curl | CloudFront → Caddy | — |
| HTTP→HTTPS | redirect | redirect → https | **PASS** LIVE | — | curl | CloudFront | — |
| Security headers | HSTS/nosniff/Referrer/Permissions | Present | **PASS** LIVE | — | curl -I | `Caddyfile` | — |
| `/api/v1/health` | 200 JSON | 200 `{"status":"ok","mode":"local"}` | **FAIL** LIVE (label) | ~0.65s | curl | `backend/api.py` | Fixed locally: mode from `APP_ENV` |
| `/api/v1/ready` public | blocked | 404 `Not Found` | **PASS** LIVE | — | curl | `Caddyfile` | — |
| `/api/v1/threads` public | blocked | 404 | **PASS** LIVE | — | curl | `Caddyfile` | — |
| `/.env` `/.git` secrets paths | no secret leak | 200 Streamlit SPA HTML, not secret bodies | **PASS** LIVE | — | content classification | Streamlit catch-all | P3 cosmetics |
| Cognito login | email+password → app | Managed Login → callback → workspace | **PASS** LIVE | — | browser | auth routes | — |
| MFA/verification code UI | may appear | **Not shown** for this account | **N/A** LIVE | — | browser | Cognito pool | — |
| Auth cookies to JS | HttpOnly tokens | Only `_streamlit_xsrf` in `document.cookie`; no token keys in storage; URL clean | **PASS** LIVE | — | CDP | `cognito_cookies.py` | — |
| Gate copy | never graded | Present | **PASS** LIVE | — | snapshot | UI gate | — |
| Rename notebook | persists | `QA-TEST-PROD-MANUAL` then XSS title | **PASS** LIVE | — | UI | `ui/rename.py` | — |
| Weak Focus turn | scaffold; STAY | Scaffolded; stayed Focus | **PASS** LIVE | ~30–45s full reply | chat | prompts/focus | — |
| Partial Focus turn | probe missing reasoning; preferably STAY or pending Next | Workable focus accepted; **auto-advanced to Evidence** (month-1 policy) with `advanced_stage_response` formatting; Journey `1 of 6`; **no Next** | **PASS** vs month-1 auto-advance policy LIVE | ~30–50s | Journey + chat | `compose.prod.yaml` / `application.py` | Intentional for month 1 |
| Prompt injection | ignore; no prompt leak; no forced advance | Redirected to Evidence coaching; no system prompt; stayed Evidence (`1 of 6`) | **PASS** LIVE | ~30–50s | chat | coaching.md | — |
| Off-topic / write assignment | refuse; redirect | Refused weather + full assignment; redirected to Evidence task | **PASS** LIVE | ~30–50s | chat | coaching.md | — |
| XSS notebook title | no JS exec | Literal `<script>…` in title input; 0 injected script nodes | **PASS** LIVE | — | CDP | Streamlit | — |
| Refresh while logged in | session + notebook persist | Messages + stage + title restored | **PASS** LIVE | — | navigate | Cognito cookies | — |
| Logout | clear session → gate | Signed-out welcome / Sign in | **PASS** LIVE | — | profile Logout | auth logout | — |
| Back after logout | no protected restore | Remains gate (`?signed_out=1`) | **PASS** LIVE | — | history.back | auth | — |
| Sources lecture sync | empty OK if sync off | Lecture/Readings · 0 | **PASS** LIVE (expected) | — | Sources panel | `COURSE_MATERIAL_SYNC_ENABLED=false` | — |
| Upload/RAG live | full matrix | **NOT VERIFIED** (file picker not automated) | — | — | — | — | — |
| QA_A/QA_B IDOR live | isolation | **NOT VERIFIED** (no second account) | — | — | — | ownership tests local | — |
| Idempotency double-send live | one turn | **NOT VERIFIED** LIVE | — | — | — | student_store tests | — |
| Rate limit hammer | light only | **NOT VERIFIED** LIVE (cost) | — | — | — | rate_limit tests | — |
| Container restart | DSQL/S3 persist | **NOT VERIFIED** (no restart authorization) | — | — | — | — | — |
| ARM64 image build | builds | **NOT VERIFIED** this pass | — | — | — | Dockerfile | — |

---

## Coach pedagogical QA

### Focus

| Probe | Observed | Recommendation behaviour | Correct? |
|---|---|---|---|
| Weak (“I don't know… sustainability”) | Narrowed to contexts; one question | Stayed Focus | **Yes** |
| Partial (NUS canteen food waste) | Declared workable focus; moved into Evidence framing | **Auto-advanced** to Evidence | **Aligned with month-1 auto-advance**; Focus ADVANCE on a workable short claim is expected |
| Strong Focus | **NOT VERIFIED** as separate turn (partial already advanced) | — | — |

### Evidence

| Probe | Observed | Notes |
|---|---|---|
| Injection while on Evidence | Stayed on evidence task; no obedience | **PASS** |
| Off-topic | Refused; returned to evidence focus | **PASS** |
| Weak/partial/strong Evidence matrix | **NOT VERIFIED** (paid-call budget) | — |

### Assumptions / Perspectives / Synthesis / Conclusion

**NOT VERIFIED** on live (insufficient turns; auto-advance would also skip confirmation UX).

Conclusion terminal behaviour: **CODE REVIEW / automated tests only**.

---

## Authentication/security findings

| ID | Sev | Finding | Mode |
|---|---|---|---|
| A1 | — | Month-1 policy: production auto-advances on coach ADVANCE (no Next). Intentional; live matched this. | LIVE + product |
| A2 | P2 | `/api/v1/health` always returned `mode: local` even on prod URL | LIVE; **fixed in repo** |
| A3 | P3 | Unknown paths return Streamlit HTML 200 (not secret leak) | LIVE |
| A4 | — | Cognito cookies not readable by JS; Secure expected via `AUTH_COOKIE_SECURE=true` in compose | LIVE + code |
| A5 | — | Public coaching/CRUD APIs blocked at Caddy | LIVE |

---

## User isolation findings

- Live cross-user IDOR: **NOT VERIFIED** (no QA_USER_B).
- Automated ownership suite: included in full pytest (**VERIFIED BY AUTOMATED TEST**).
- Public network cannot hit `/api/v1/threads` (**MANUALLY VERIFIED ON LIVE**).

---

## RAG/source findings

- Course materials empty by design (`COURSE_MATERIAL_SYNC_ENABLED=false`) — **LIVE**.
- Upload/select/cite/delete matrix — **NOT VERIFIED** live.
- Source-as-instruction untrusted rules — **CODE REVIEW** (`coaching.md` CONTEXT SAFETY); injection via chat student text — **LIVE PASS**.

---

## File upload findings

**NOT VERIFIED** on live browser automation. Upload bounds covered by automated tests (`test_upload_hardening.py` et al.).

---

## Stage progression findings

1. Server auto-advanced Focus→Evidence without student **Next** on live — **expected for month-1** (`AUTO_ADVANCE_STAGES=true`).
2. Authoritative order is Focus→Evidence→Assumptions… (**CODE**).
3. Confirmation-gated Next UI absent when auto-advance on (**LIVE**, intentional month 1).
4. Month-2+ needs **student stage-selection** UI/API (not Next-only); not implemented yet.

---

## UI/UX findings

| Sev | Finding |
|---|---|
| P3 | Journey radio click often intercepted by label overlay (automation friction; students can still switch via label). |
| P3 | XSS title string is long/ugly but safe. |
| — | Never-graded messaging visible on gate. |
| — | Mobile viewport set via CDP; deep mobile layout matrix **NOT VERIFIED**. |

---

## Performance measurements

Manual observed timings (not statistical p95):

| Action | Observed time | Assessment | Notes |
|---|---|---|---|
| Root HTTPS | ~1.0s | Acceptable | curl |
| Health | ~0.65s | Acceptable | |
| Cognito round-trip | interactive ~10–20s | Acceptable | human+MFA N/A |
| Coach turn (Luna Low) | ~30–50s to full reply | Slow but usable for pilot | Paid path; dominant cost |
| Notebook switch / Journey open | interactive <2s | Acceptable | |
| Refresh restore | few seconds Streamlit load | Acceptable | |

Bottleneck: **model latency**, not page chrome.

---

## Browser console/network issues

- No systematic console dump captured (CDP Log not fully audited).
- Tokens not observed in URL after callback (**LIVE**).
- Network waterfall p95: **NOT VERIFIED**.

---

## Privacy/logging findings

- Coach info logs designed to omit message text / notebook ids (**CODE REVIEW** prior hardening).
- Live container log inspection on EC2: **NOT VERIFIED** this pass.
- Report contains no token/secret values.

---

## Fixed issues

### F1 — Production health `mode` mislabeled

- **Severity:** P2  
- **Reproduction:** `GET https://d1sxfuoybzedj5.cloudfront.net/api/v1/health` → `"mode":"local"`.
- **Root cause:** Hardcoded return in `backend/api.py`.  
- **Files:** `backend/api.py`  
- **Fix:** Derive `mode` from `APP_ENV`.  
- **Regression:** Covered indirectly by existing health tests (`mode == local` under test `APP_ENV=development`).  
- **Manual retest:** **NOT VERIFIED** on live (undeployed).

### F2 — Month-1 auto-advance is intentional production policy

- **Severity:** was flagged P1 vs confirmation design; **reclassified as product policy**  
- **Reproduction:** After partial Focus reply, Journey showed Focus completed and Evidence current; chat used `**Examine evidence**` + `Questions to explore`; Next absent. Matches `advanced_stage_response` + `auto_advance_stages`.  
- **Decision:** Month-1 pilot keeps auto-advance. `compose.prod.yaml` sets `AUTO_ADVANCE_STAGES=true`. Production fail-closed rejection of auto-advance was **removed**.  
- **Month-2 behavior:** Enable free stage selection, then turn auto-advance off.
  Students may move to any non-current stage; selection alone does not complete
  a stage or increase its Facione evidence.
- **Files:** `compose.prod.yaml`, `backend/settings.py`, `.env.example`, tests/docs  
- **Manual retest:** **LIVE** already in auto-advance mode.

### F3 — Public login-start write amplification

- **Severity:** P1 (code review; not load-tested live)  
- **Reproduction:** Unauthenticated `GET /api/v1/auth/login` always persisted OAuth state (DSQL) with no throttle ([Sol security review](d9fce27a-9b27-4132-8003-b1688094656e)).  
- **Root cause:** Public Caddy-exposed login start had no per-IP/global limiter.  
- **Files:** `backend/rate_limit.py`, `backend/auth_routes.py`, `backend/settings.py`, `.env.example`, `tests/test_rate_limit.py`  
- **Fix:** In-process `LoginStartLimiter` (default 10/min/IP, 60/min global); on limit redirect `/?auth_error=1` with `Retry-After` before `begin_login`.  
- **Regression:** unit + API short-circuit tests.  
- **Manual retest:** **NOT VERIFIED** on live (do not flood production).

### F4 — Cognito callback logged raw `error` query

- **Severity:** P2  
- **Root cause:** `logger.info("... error=%s", error)` echoed attacker-controlled query text.  
- **Files:** `backend/auth_routes.py`, `tests/test_rate_limit.py`  
- **Fix:** Allow-listed error category only (`access_denied`, …, else `unlisted`).  
- **Manual retest:** **VERIFIED BY AUTOMATED TEST**.

---

## Remaining issues

### P0

None observed that expose other students’ data or bypass auth on the public edge.

### P1

1. Login-start throttle exists in repo only until redeploy (**CODE**; do not flood live to verify).
2. Month-2 student stage-selection feature not built yet (auto-advance-off alone is not enough).

### P2

1. Health `mode` still wrong on live until redeploy.  
2. Incomplete live coverage: uploads/RAG, multi-user IDOR (must use container-local API per [Auth ownership map](e6b197fd-0d32-47aa-9818-4b6c2b4c8640)), full stage ladder, idempotency double-click, rate-limit UX.  
3. Auto-advance + concurrent idempotency waiter race ([Sol](d9fce27a-9b27-4132-8003-b1688094656e)) — relevant while month-1 auto-advance is on.  
4. Logout is GET and can be forced via top-level cross-site navigation (`SameSite=Lax`) — needs POST+CSRF design; **not changed** this pass.  
5. Unsupported upload extensions are stored with `supported=False` rather than hard-rejected ([RAG map](a211ff22-ff19-4648-9e97-53938f872876)) — policy check.

### P3

1. SPA soft-200 for arbitrary paths.  
2. Journey tab click targeting quirks.  
3. Course materials empty (expected with sync disabled).  
4. UI dialog Cancel does not call `accepted=false` for pending transitions (pending cleared on next coach turn).
---

## Test results

```text
.venv/bin/python -m pytest -q
→ 344 passed (warnings only: Starlette TestClient deprecations)

APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet
→ OK

docker compose config --quiet
→ OK

docker buildx linux/arm64
→ NOT RUN this pass
```

---

## Production release checklist

- [x] Login works — **LIVE**
- [x] Logout works — **LIVE**
- [x] Refresh session works — **LIVE**
- [ ] User A cannot access User B data — **NOT VERIFIED live** (automated ownership tests pass)
- [x] Notebook CRUD (rename) works — **LIVE** (create/delete not fully exercised)
- [x] Chat works — **LIVE**
- [~] Coach follows current stage — **LIVE partial** (Focus/Evidence only)
- [x] Weak responses do not advance prematurely — **LIVE** (weak stayed)
- [~] Strong responses can advance appropriately — **LIVE** month-1 auto-advance
- [~] Pending stage transition works — **N/A month-1** (auto-advance; Next hidden)
- [ ] Conclusion cannot advance — **CODE/TEST only**
- [ ] Upload works — **NOT VERIFIED live**
- [ ] Retrieval works — **NOT VERIFIED live**
- [ ] Citations are valid — **NOT VERIFIED live**
- [ ] Source deletion works — **NOT VERIFIED live**
- [ ] Notebook deletion works — **NOT VERIFIED live**
- [~] DSQL persistence works — **LIVE** (refresh retained messages/stage)
- [ ] S3 persistence works — **NOT VERIFIED** (no upload)
- [x] No exposed secrets on public paths — **LIVE** (SPA soft-200 only)
- [ ] No critical browser-console errors — **NOT FULLY VERIFIED**
- [x] HTTPS works — **LIVE**
- [x] Public/private API boundary works — **LIVE**
- [ ] Rate limiting behaves correctly — **TEST / NOT LIVE**
- [ ] Duplicate sends do not duplicate turns — **TEST / NOT LIVE**
- [x] Production config validation passes — **local tests**; month-1 auto-advance allowed
- [x] Full pytest passes — **344**
- [ ] ARM64 production image builds — **NOT VERIFIED**

---

## Operator actions before wider student use

1. Redeploy so `compose.prod.yaml` `AUTO_ADVANCE_STAGES=true` wins over any host `.env` false (month-1 policy).  
2. Confirm Thinking Path has **no Next** and stages auto-move on ADVANCE.  
3. Smoke upload + citation; optional second QA user for IDOR.  
4. Plan month-2 **stage-selection** feature before flipping auto-advance off.  
5. Optional: rotate the password shared in chat after QA.
