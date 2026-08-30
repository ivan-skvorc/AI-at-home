### Server-side speech-to-text (`packages/harness/deerflow/community/speech/`)

The second tier of voice input. Read this before changing anything here: the
module is small, and most of what makes it correct is a refusal rather than a
feature.

**What the feature is for.** The composer's microphone used to wrap the browser
`SpeechRecognition` API, whose default implementation streams audio to the
vendor — Google in Chrome, Apple in Safari — *directly from the browser*. That
traffic never passes through the Gateway, so no amount of Tailscale or auth work
touched it. The tiers now run: browser on-device (`processLocally`, Chrome
139+), then this module, then the vendor cloud only if the operator opted in.

**Four properties are load-bearing. A refactor must not "simplify" any away.**

1. **The cloud tier is off by default.** `voice.allow_cloud_fallback` defaults
   to `False`, and the frontend's `DEFAULT_VOICE_SERVER_CONFIG` repeats that
   default so a Gateway that fails to answer *also* fails closed. An install
   with no local STT reports voice as unavailable. That is the feature working,
   not a gap to paper over by restoring a silent vendor fallback.
2. **The size cap is enforced while reading, not after.** `_read_bounded` in
   `app/gateway/routers/voice.py` refuses past the limit mid-stream. Replacing
   it with `await file.read()` plus a length check reintroduces exactly the
   unbounded-body problem the cap exists for, and every test still passes
   because they assert on the status code, not on memory.
3. **Errors never echo the service's response body.** A transcript is speech.
   `_read_transcript` and the `transcribe` error paths carry status codes and
   endpoint URLs only — see `test_client_error_text_never_echoes_the_service_body`.
   Adding `response.text` to a message for "better diagnostics" puts fragments
   of the user's speech into log files that outlive the conversation.
4. **`is_local_endpoint` treats Tailscale's CGNAT range as local.** CPython does
   *not* classify `100.64.0.0/10` as private (it is neither `is_private` nor
   `is_global`), so the shared `url_safety.is_blocked_address` predicate reports
   a tailnet peer as a public host. Reaching the stack over Tailscale is this
   fork's documented access path, so without the explicit `_CGNAT_NETWORK` check
   the composer would tell a user their own home server is sending audio off the
   machine.

**Do not widen `url_safety.is_blocked_address` to cover CGNAT instead.** That
predicate decides what the *web* tools may fetch; adding CGNAT there would newly
refuse tailnet URLs to every one of them. The two questions look identical and
are opposites: the shared guard stops the Gateway reaching *into* private space,
while this module's risk is an endpoint that sends audio *out*. Nothing here
refuses a public endpoint — a VPS you own is a legitimate if unusual choice — it
is logged at build time and surfaced through `local_service` in
`GET /api/voice/config` so the composer can label it.

**No engine is named on purpose.** The client speaks the OpenAI
`/v1/audio/transcriptions` shape, which faster-whisper-server, speaches,
whisper.cpp's `server` and LocalAI all implement. Keep it that way rather than
special-casing a backend; `_read_transcript` already tolerates both the JSON and
bare-text reply shapes those servers ship with.

**Tests** — `backend/tests/test_voice_stt.py` (endpoint contract, client
transport, screening) and `frontend/tests/unit/core/voice-input/` (tier
selection, recorder microphone release, capability fail-closed).
