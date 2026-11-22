# Production React and streaming release, 23 November 2026 (Singapore)

The existing CloudFront URL serves the React student workspace. The EC2 app
runs `workspace-20261122-24f4d2810da7` with image digest
`sha256:0ceca0a9da302927c6f53297645e257fefe346844f3a02f887a248ad921cc4c5`.
The release contains the approved working tree on top of Git
`77e16aa5eed61516d8851c4fcb3757109e73e202`. Its source manifest uses
SHA-256 `24f4d2810da725be05895a47124f8fe5d29fd2ecc3aa8a0bea433f6bdf65b511`.
The source files and freshly built React bundle were layered on the previous
production ARM64 image after Docker canceled the full dependency rebuild.
The dependency file checksum matched, `pip check` passed on the base, and the
release image passed network-free readiness, guest sign-in, normal and edited
streaming, and saved-revision checks.

AgentCore `DEFAULT` moved from v35 to v36 and reported `READY`. The existing
runtime configuration and vendored dependency pins were preserved. EC2 was
recreated with `AGENTCORE_SESSION_GENERATION=20261122-streaming-v36` and
reported healthy. Public health returned 200 and internal readiness returned
404 through CloudFront. No schema or IAM changes were applied. The previous
local image `cde2300-chatbot:bdba9d8` and host backup in
`releases/before-20261122-streaming` are available for rollback. Restore the
previous app and Caddy configs and DEFAULT v35 with a fresh session generation.

## Student tests

Five paid submissions used one synthetic guest notebook and two child chats.
The cohort is too small to estimate general answer quality or latency. Times
start at the browser stream request. Runtime first text is measured separately
inside the model path. The final column records the saved-response event.

| Case | First visible | Runtime first text | Saved | Reply fragments | Assessment |
| --- | ---: | ---: | ---: | ---: | --- |
| PDF problem framing | 13.69 s | 5.55 s | 14.04 s | 148 | Pass. Cited the PDF, got 18/24 = 75% and 12 seconds, and qualified survey limits. |
| Readiness and HMW | 6.58 s | 5.27 s | 6.94 s | 153 | Pass. Recommended Concept generation and waited for student confirmation. |
| Image concept comparison | 7.15 s | 5.90 s | 7.52 s | 133 | Partial. Read 14 seconds and S7 correctly, assigned an unsupported citation meaning to S7, and overstated one accessibility concern. |
| Edit the image prompt | 9.01 s | 7.16 s | 9.34 s | 183 | Partial. Retained the image and separate draft and proposed workable comparison measures, but again guessed what S7 meant and blurred the 12-second baseline with the 14-second concept. |
| New chat, same notebook | 11.08 s | 4.34 s | 11.34 s | 127 | Pass. Reused and cited the PDF, reported 12 m, 6 s current and 12 s calculated, and correctly acknowledged the prior chat's image was unavailable. |

Median first visible reply was 9.01 seconds. Median saved reply was 9.34 seconds.
All five showed multiple growing text updates before the final reply. The visible
lead time was roughly a quarter to a third of a second before validation, so
streaming worked but did little to shorten the initial wait on these prompts.

The first chat moved from Problem identification to Concept generation only
on confirmation. The edited reply recommended Design specification, which
remained pending. The second chat started in Problem identification. Reloading
preserved both chat states, active message counts (six and two), citations and
the selected notebook PDF. The downloaded PDF SHA-256 matched the original.

App telemetry recorded five Claude Haiku 4.5 Fast Chat generation attempts
with 25,687 reported input tokens and 2,634 output tokens. Student confirmation
triggered one automatic Haiku stage checkpoint with 17,999 input and 4,435
output tokens. The six application-visible attempts reported no SDK retries.
Two chat calls reported 6,565 cache-read tokens each. Model-internal call counts
were unreported. No extra Summary or Deep Review call was requested.

Production Review passed keyboard opening, My work selection, browser tab
switching and Escape close at 1440 px and 390 px in Light and Dark. The final
browser console showed zero errors or warnings. Live Summary generation was
excluded from the five-prompt run. The local mock preview on port 8081 also
responded successfully.

The next quality check is whether coaching describes visible image details
without assigning meaning to unlabelled markers. Use the mock Summary and Review
regressions in the [streaming handoff](REPLY_STREAMING_HANDOFF.md) for UI changes.
