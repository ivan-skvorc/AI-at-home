# Gateway route and skill-listing authorization

Split out of [`AGENTS.md`](AGENTS.md) to keep it within its guidance budget
(`scripts/check_agent_guidance.py`).

### Route and skill-listing authorization

`authz.authorize_model_use` shares the `model:use` decision between model details
and follow-up suggestions, including the factory's first configured model when
the caller omits `model_name`. Suggestions check admission before their
best-effort LLM error handler: explicit denies return 403 without invoking the
model, while provider failures honor `authorization.fail_closed`.

`authz.py::resolve_route_permissions()` is shared by HTTP, decorator-only auth, and Live Browser WebSocket admission. It evaluates full `resource:action` route targets; provider errors follow `authorization.fail_closed`, while disabled authorization preserves the legacy permission set. Owner/admin checks stay separate. Live requires `threads:write` with `is_internal=False` after login/Origin checks but before acceptance or session acquisition; denial closes 4403 and unexpected setup errors close 4501. Admission is connection-scoped. On disconnect, Live drains owned `stop_screencast()` cleanup across cancellation before releasing the session lease, so cancellation cannot strand a manager pin and consume browser-session capacity. Tests: `test_authorization_route_permissions.py`, `test_browser_readonly_security.py`, `test_auth.py`, `test_auth_middleware.py`.

Skill listing authorization mirrors the models pattern: `routers/skills.py` routes resolve `(provider, principal)` through `authz.py::resolve_skill_authorization()` — a thin sibling of `resolve_model_authorization`, both delegating to the shared `_resolve_route_scoped_authorization` core — and the shared `_filter_visible_skills` helper filters the user-scoped catalog (public + caller's custom skills) through `filter_resources(principal, "skill", ...)` by name. Three user-facing surfaces apply it: `GET /api/skills` (the frontend skill list / slash-command autocomplete), `GET /api/skills/custom`, and `GET /api/skills/{name}` — the detail endpoint returns the standard 404 for an invisible skill so it cannot become an existence oracle the filtered list closed (`get_model`'s 403 is an execution decision via `authorize("model", "use")`, which has no skills equivalent in this layer). Anonymous callers are unfiltered (mirroring `list_models`), and provider resolution/decision errors follow `authorization.fail_closed` (fail-closed → empty listing / 404, fail-open → full listing). Skill management endpoints (`install`/`upload`/`reload`/custom-skill CRUD) stay `require_admin_user`-gated, and runtime activation authorization is a separate layer. The built-in RBAC provider maps this to the per-role `skills` policy key. Tests: `tests/test_skills_listing_authorization.py`.

Batch workers pin `app.state.extensions`; never persist snapshots.
