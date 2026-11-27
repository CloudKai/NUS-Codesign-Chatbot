# Deployment and Mantle safety record

This is an offline reconciliation dated 24 November 2026 SGT, not a statement
of current AWS state. The [versioned nonsecret manifest](../examples/deployment/architecture-ticket04-2026-11-24.json)
separates repository settings, historical deployment evidence and actually
verified live configuration. JSON `null` means unknown. Append a dated manifest
for each approved release; keep this snapshot as evidence. Never populate an
unknown from a default, an alias name or a successful health check.

## What the identifiers mean

| Layer | Repository / latest record | Reconciliation |
| --- | --- | --- |
| Application | Working tree based on `4f12995`; recorded app base `dc83707` with a separate settings patch | A dirty checkout is not a release SHA. The recorded image label alone does not describe its settings patch or current frontend. The exact recorded image ID and patch hash are in the manifest; carry-forward to the later restoration was not independently rechecked here. |
| Edge | Production `Caddyfile` permits GET bootstrap; `Caddyfile.local` does not | Ticket 01 reproduced the local gap. Direct FastAPI browser success is not edge parity. Live mounted Caddy hash is unknown. |
| Image | Dockerfile uses Python 3.12, Node 22 builder; ARM64 release recipe | Runtime packaging is a different artifact. No current registry digest or image contents were inspected. |
| Runtime | Direct-code Linux ARM64/Python 3.14, pinned requirements | Latest recorded restoration selects V1 deployment **38** through **GemmaStable37**. The name does not pin version 37. DEFAULT remained V2 **39** in that record. Current live versions remain unknown. |
| Model | Settings default is mock; `.env.example` and Compose select AgentCore/Haiku; restored deployment records Gemma/Mantle with Sonnet Deep Review | The example file is not a cost-safe mock configuration. Application environment does not set the remote runtime environment. Review all role settings on both sides. |
| Sessions | Settings `1`; example `7`; Compose `20261122-streaming` | The v37 rollout recorded `20261123-gemma37-nativejson`; the later V1 restoration records a new generation without its literal value. Latest recorded value is unknown. Never reuse an earlier value by inference. |
| Safety | Source suppresses Mantle provisional text before OUTPUT guardrail | Recorded v38/v39 publication predates this local fix. No record proves the fix is published. Health, historical successful guardrail calls and source tests do not establish deployed protection. |

The manifest references the [restoration ledger](../IMPLEMENTATION_STATUS.md#agentcore-platform-v1-restored-in-production-2026-11-24-sgt),
[v38 aggregate artifact](../examples/classroom-capacity/gemma-results-2026-11-24.json)
and [V2 comparison](../operations/AGENTCORE_V2_LIVE_COMPARISON.md). Earlier
release-checklist v35/generation 11, `.env.example` v19 comments, Haiku-only IAM
narrative and v37 promotion describe earlier states. They are not current live
assertions. Compose's DEFAULT/Haiku settings cannot be copied over the recorded
Gemma pin without an approved coordinated release.

The [privacy audit](../security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md) also found
that `.dockerignore` does not exclude `.agents/`, `.playwright-cli/` or
`.scratch/` directories. The final `COPY . .` can include eligible historical
artifacts. Before release, review a sanitized build context and the resulting
image inventory, preserve originals, and resolve packaging in ticket 51. The
`.dockerignore` exclusions were added by ticket 51 (recorded in the
[coordinated release rehearsal](COORDINATED_RELEASE_REHEARSAL.md)); the image
inventory review still precedes any release. No packaging change, deletion or
image build is part of ticket 04. The Compose edge image is the mutable
`caddy:2-alpine` tag; its running digest is unknown.
Runtime requirements comments describe an earlier Python 3.12 dependency check
and Haiku-only path; the deployment recipe records Python 3.14/ARM64 and later
Gemma/Mantle evidence. These comments are not artifact compatibility proof; run
the pinned runtime-compatibility job against the actual release package.

## Reviewable publication and verification procedure

These steps are a release plan, **not executed here**. Live configuration
changes need explicit authorization; model checks additionally need a stated
request/token or cost cap. The old test allowances are exhausted permissions
for their historical runs, not permission for this plan. Stop on mismatches;
do not automatically repair live state or run extra probes.

1. **Prepare a release tuple.** Record approved full application SHA, generated
   reader-contract and lockfile hashes, built frontend identity, immutable app
   tag plus registry digest and running image ID, image revision/patch labels,
   production Caddy hash, runtime source/package hash and dependency pins,
   platform/version, selected qualifier and its liveVersion, DEFAULT liveVersion,
   each role's provider/model/region, guardrail version on both sides, and old
   and proposed session generations. Exclude tokens, cookies, private prompts,
   account locators and full environment dumps from the published manifest.
   Unavailable fields stay null and block the corresponding release gate.
2. **Check compatibility offline.** Run the deterministic commands below and
   the full build. Preserve the tolerant application parser for old JSON and
   current SSE, browser NDJSON, validated `reply_ready`/save/discard and
   exact-key recovery. Include both the Gemma canonical-nullability correction
   and Mantle provisional-output suppression in the runtime artifact. Keep
   additive storage compatibility. Deploy the compatible app parser before a
   runtime contract change. Review the exact Caddy allowlist with the frontend;
   never expose `/ready`, internal APIs or a wildcard reader route to fix a 404.
3. **Capture pre-publication state privately.** On the authorized host/control
   plane, inspect the selected endpoint as well as DEFAULT. The established
   control-plane operations are `get-agent-runtime` (for the specific version)
   and `get-agent-runtime-endpoint` (for the selected endpoint). Record only
   allowlisted version, status, artifact and configuration fields in the
   nonsecret release record. Use the existing runtime ARN; do not create a new
   runtime. Confirm candidate and rollback artifact safety before any update.
4. **Publish the reviewed artifact.** Follow [runtime packaging/publication](AWS_STATELESS_EC2.md#publish-an-agentcore-runtime-version).
   Wait for the new version to be READY and inspect effective runtime model,
   role, guardrail and lifecycle settings. An update may move DEFAULT
   automatically; check immediately. Inspect the application's selected
   qualifier separately: a pinned `GemmaStable37` will not follow DEFAULT.
   Change the selected endpoint only as authorized, and confirm it resolves
   to the intended READY version and artifact. Version/alias equality is
   necessary but does not prove session replacement.
5. **Roll sessions before admitting generation.** Set a new unique nonsecret
   `AGENTCORE_SESSION_GENERATION`, distinct from the captured serving value,
   and recreate FastAPI so it reads it. Do this for runtime publication,
   endpoint changes and rollback. Do not reuse an earlier generation. Inspect
   only the named generation/qualifier values in the running process, plus
   image identity and Caddy identity. Do not dump `docker compose config` or
   `printenv` unfiltered into shared evidence. Confirm existing saved notebooks
   remain available; no database restore/reset or runtime session history copy.
6. **Prove a fresh runtime session.** Use approved synthetic identities and a
   disposable notebook within the cap. Record an opaque session correlation
   digest, creation time after recreation, resolved runtime version/platform
   and observed model provenance from authorized telemetry. Also reopen an
   existing synthetic notebook under the new generation to check affinity
   rollover. Do not publish owner/notebook IDs or raw session IDs. If telemetry
   cannot associate the invocation with the intended new version/session,
   leave fresh-session verification unknown and stop promotion. A new browser
   cookie alone does not establish that an old notebook's warm runtime changed.
7. **Check allowed and blocked output through the real path.** Before any paid
   check, approve the exact synthetic cases and number of invocations (including
   possible retries) within the cap. Observe runtime frames, same-origin app
   stream and browser rendering for normal and edited turns. An allowed Mantle
   case may emit operation status, then checked final reply/save; it must emit
   no provisional model/reply text before OUTPUT approval. Use a controlled
   output-block fixture in a disposable staging runtime with the same candidate
   artifact and an authorized guardrail policy: it must reach OUTPUT blocking,
   not merely INPUT refusal. Expect `safety_blocked`, zero text preview,
   no unsafe saved assistant reply and no unsafe receipt after reload/restart.
   A harmless response to an unsafe prompt is not proof of output blocking.
   If an authorized deterministic live block cannot be induced, keep the
   blocked-output field unknown; local forced-block tests cannot replace it.
   Log event categories/timing and pass/fail only, never blocked text or traces.
8. **Accept only the observed tuple.** Verify health, host-local readiness,
   exact bootstrap edge access, registered/Guest ownership, saved citations,
   explicit stage confirmation, normal/edit streaming and restart recovery.
   Do not mutate/delete real student data. Save dated nonsecret evidence and
   fill `actually_verified_live` only for checks performed against this exact
   tuple. Record command results, unresolved fields, capped usage and approver.
   The [full release checklist](../PRODUCTION_RELEASE_CHECKLIST.md) still applies;
   the coordinated release/rollback preparation and disposable rehearsal are in
   [COORDINATED_RELEASE_REHEARSAL.md](COORDINATED_RELEASE_REHEARSAL.md) and its
   [2026-11-26 manifest](../examples/deployment/release-rehearsal-ticket51-2026-11-26.json).

### Offline checks available now

```sh
.venv/bin/python -m pytest -q -o addopts='' \
  tests/domain/test_runtime_reply_stream.py \
  tests/domain/test_runtime_model.py \
  tests/domain/test_agentcore_session_affinity.py \
  tests/domain/test_reply_streaming.py \
  tests/test_deployment_config.py tests/http/test_production_config.py
sh scripts/build.sh
```

These existing tests use deterministic external substitutes. The forced OUTPUT
block regression proves the source gate for both passing and blocked results;
it does not load a live published artifact. Session tests prove generation and
owner/role isolation locally. Missing optional Strands middleware integration
is recorded as a skip, never a deployment pass. Ticket 01/02 retain real
disposable startup, citation, explicit progression and process-restart evidence;
no new browser/layout or startup claim is made by this documentation change.

## Safe rollback

The old host rollback script and `HaikuRollback36` are historical candidates,
not automatically safety-approved targets. Verify the exact package and model
path first. Never roll Mantle back to v38/v39 or another artifact that lacks
the provisional-output suppression. Prefer a separately prepared known-good
artifact that retains the fix and canonical validation, with compatible app,
frontend/contracts and Caddy. A Haiku target requires its own path-specific
safety evidence; the Mantle fix is retained in the source/release baseline.

For an approved rollback, select the verified READY artifact/endpoint, change
session generation again, recreate FastAPI, and repeat version/fresh-session,
blocked-output and saved-data checks. Preserve additive schema and data. Do not
restore old databases to roll back application code. If no verified safe tuple
exists, suspend generation/access via an approved operational action and
preserve saved work until a safe candidate is prepared. Do not restore unsafe
text streaming to recover latency or availability. No live rollback or drill
was performed in this ticket.
