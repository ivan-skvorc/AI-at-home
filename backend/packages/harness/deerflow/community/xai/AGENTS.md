### Grok API features (`packages/harness/deerflow/community/xai/`)

Fork feature (FORK.md §43): Grok Imagine (images, edits, video), X search and
voice through `https://api.x.ai/v1`, paid for by the Grok subscription that
Settings → Models connects. Chat stays on the CLI proxy (`models/subscriptions.py`).
Several properties here are **silent when broken**; read this before editing.

**Recorded extension-first exception.** This ships in core: every tool needs the
Grok credential, authentication stays in core, and the extension contract has
no credential capability — adding one would hand a refreshable plan token to
third-party code. Tools only ever get `grok_api_access(feature)`: one
switch-checked token for one request.

**Reach is measured, never assumed.** `_probe_grok` (in `models/subscriptions.py`)
runs on connect and on Refresh: `GET /models` (grouped by `output_modalities`)
and `GET /tts/voices`. Only a 401/403 is `not_on_plan`; an outage or a listing
that omits a family is `unknown`, keeps the previous answer, and stays
switchable — do not "tighten" that into a lock, or an xAI listing change locks
operators out of features they pay for. The probe never raises.

**Every feature is off until an administrator switches it on**, per connection,
and a new grant (reconnect) starts off again. Switches live in the encrypted
Grok record (`features`), not in config.

**Exposure is decided twice.** `get_available_tools` filters on
`AppConfig._subscription_features`, read in `merge_subscription_models` from the
same snapshot as the run's models — no extra store read per run. Each call then
resolves its token through `grok_api_access(feature)`, which re-checks the
switch and the plan under the shared lock. Keep both: the first keeps a dead tool
out of the model's schema, the second makes "off" take effect mid-run.
`features.py` keys tools by `use:` path so a renamed entry cannot escape the gate.

**`cloud_media`, never `media`.** `media` is on `OFFLINE_ALLOWED_TOOL_GROUPS`
because ComfyUI is local; a Grok tool there survives the internet switch.
`x_search` sits in `web`. Pinned by `test_tools_appear_only_for_ready_features`.

**Gateway process, token never stored.** Tools write to the host outputs path
like ComfyUI and resolve the token per request; nothing stores it on a tool,
client or file. `.request.json` beside each output records the request with
source images by *path*, never as data. Errors carry status and path only —
never a response body (bodies echo prompts and speech).

**No retries on plan quota** (429), matching subscription chat. Video polls
re-resolve the token each round; the wait is capped by `timeout_seconds`.

**Downloads are pinned.** Generated files come from xAI's temporary links:
HTTPS, a host under `download_hosts` (default `x.ai` and subdomains), a public
address, no redirects, and no `Authorization` header. Images ask for
`b64_json` first so usually nothing is fetched.

**Source images leave as data URIs** — a home server has no public URL — after
`_resolve_and_validate_user_data_path` confines them to the thread.

**No contact sheet for Grok video.** The backend has no video decoder; the tool
says so rather than claiming the model saw the clip. Adding PyAV/imageio-ffmpeg
is a separate dependency decision.

**Voice** (`voice.py`, routes in `app/gateway/routers/voice.py`): read-aloud and
a transcription tier, both gated on the Grok `voice` switch alone — deliberately
not on `voice.allow_cloud_fallback`, which means the *browser's* vendor cloud. A
configured local STT service always wins and its failures are never retried
against xAI. `/v1/stt` needs the file part last in the multipart body.

Tests: `tests/test_grok_features.py` (probe, switches, gate),
`tests/test_grok_xai_tools.py` (tools over offline HTTP),
`tests/test_subscription_providers.py` (Responses models), `tests/test_voice_stt.py`
(Grok voice tier). None of the xAI wire shapes were verified live from CI; the
first real connection is the check, and the shapes came from docs.x.ai.
