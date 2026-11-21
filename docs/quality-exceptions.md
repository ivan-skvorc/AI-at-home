# Quality exceptions

Redundancies kept on purpose. [change_cycle.md](../change_cycle.md) level 3
logs every quality finding it does not fix here, and checks each entry's
"Fix when" condition on every run: once the condition is met, the redundancy
is fixed and the entry deleted. Entries whose condition still holds are not
reported again.

Format (one entry per redundancy):

```markdown
### <what is duplicated, in a few words>
Where: <the files>
What: <the redundancy>
Why kept: <a cost estimate, a technical constraint, an external dependency, or "needs owner decision">
Fix when: <a condition anyone can check>
Added: <YYYY-MM-DD>, <PR link>
```

### Remaining thread-id resolver variants
Where: mcp/tools.py:458 _extract_thread_id; agents/middlewares/summarization_middleware.py:155 _resolve_thread_id; agents/middlewares/sandbox_audit_middleware.py:472 _get_thread_id; tools/skill_manage_tool.py:111 _get_thread_id; community/browser_automation/tools.py:79 _thread_id; agents/middlewares/artifact_capture_middleware.py:82 _thread_id; agents/middlewares/harness_guard_middleware.py:214 _get_thread_id; inline lookups in tools/builtins/task_tool.py:1072, tools/builtins/batch_task_tool.py:228 and :436, tools/builtins/invoke_acp_agent_tool.py:309, and in the view_image/uploads/thread_data/memory/safety_finish_reason middlewares (all paths under backend/packages/harness/deerflow/)
What: These still re-implement the 'thread id from runtime context, else RunnableConfig, else ambient config' lookup. Each one differs from utils.thread_id.runtime_thread_id in at least one rule: what counts as absent (None, falsy or non-string), whether it reads runtime.config or the ambient LangGraph config, the fallback value ('default', '' or None), or str() coercion.
Why kept: Folding any one of them into runtime_thread_id changes behavior for at least one input at that site, for example mcp/tools returning 'default' or str(non-string), or summarization skipping runtime.config. Together they also touch more than 10 files owned by several areas (mcp, community, sandbox audit, summarization, memory). That needs an owner decision on one uniform semantics.
Fix when: For each site, either its tests pin that the site's absent, empty and non-string cases match runtime_thread_id (with or without ambient), or the owner decides on one uniform rule. Then replace the local variant with runtime_thread_id, one area per change.
Added: 2026-11-21, PR #TBD

### SpendBudgetMiddleware keys context-less runs by id(runtime)
Where: backend/packages/harness/deerflow/agents/middlewares/spend_budget_middleware.py:211 _get_run_id
What: When the context has no run_id, it returns str(id(runtime)). LangGraph builds a new Runtime per graph node, so the key changes from node to node, and CPython can reuse the address after garbage collection. Pending spend warnings and stop reasons for such a run can then miss, or attach to a later invocation. LoopDetection, HarnessGuard and TokenBudget anchor on Runtime.control through utils.run_scope.
Why kept: needs owner decision: moving to run_scope.invocation_run_id (with release in after_agent) changes how spend warnings and stop reasons are keyed for runs without a run_id, which is a behavior change in a fork-only money control (FORK.md spend caps).
Fix when: The spend-cap owner confirms that a context-less invocation should be one spend scope, as in TokenBudgetMiddleware, and a test pins the warning crossing graph nodes in a context-less run.
Added: 2026-11-21, PR #TBD

### Async checkpointer builds the database: backend in its own copy
Where: backend/packages/harness/deerflow/runtime/checkpointer/async_provider.py (_async_checkpointer_from_database vs _async_checkpointer + store/provider.py::_resolve_store_config)
What: _async_checkpointer_from_database repeats _async_checkpointer's memory, sqlite and postgres branches for the unified database section. _select_inner_checkpointer could be _async_checkpointer(_resolve_store_config(app_config)), as make_store already is.
Why kept: Merging would send the database SQLite path through resolve_sqlite_conn_str, which rejects file: URIs and calls resolve_path; today that path is used verbatim. I could not cheaply prove the two give the same path for every accepted sqlite_dir. Tests also pin the separate _prepare_database_sqlite_checkpointer_path helper, so this needs an owner decision.
Fix when: A test shows resolve_sqlite_conn_str(DatabaseConfig.sqlite_path) == DatabaseConfig.sqlite_path for every accepted sqlite_dir (relative, absolute, symlinked). Then collapse _select_inner_checkpointer onto _async_checkpointer and the shared resolver.
Added: 2026-11-21, PR #TBD

### MCP config API models repeat the harness MCP models field by field
Where: backend/app/gateway/routers/mcp.py (McpServerConfigResponse, McpOAuthConfigResponse, McpUserScopedAuthConfigResponse, McpContextHeadersConfigResponse) vs backend/packages/harness/deerflow/config/extensions_config.py
What: The request and response models of /api/mcp/config re-declare every field of the harness models. Their validators are now shared (F2), but the field lists still have to be kept in step by hand.
Why kept: These models are the public HTTP API schema. They also differ on purpose: token_url is optional, there is no cwd field, and extra='allow' preserves round-trips. Deriving them from the harness models would change the OpenAPI contract, which is a public API change.
Fix when: The /api/mcp/config schema is allowed to change (an API version bump), or the harness models get an API-projection variant that the Gateway can reuse.
Added: 2026-11-21, PR #TBD

### Dead module-global copies of summarization/tool_search/guardrails/authorization config
Where: backend/packages/harness/deerflow/config/app_config.py:_apply_singleton_configs (load_summarization/tool_search/guardrails/authorization_config_from_dict) and the matching _<name>_config globals plus get/set/load/reset functions in summarization_config.py, tool_search_config.py, guardrails_config.py and authorization_config.py
What: Confirmed: no production code reads these four globals. Every reader goes through get_app_config(); authz uses app.gateway.authz._get_route_authorization_config. Only tests touch the accessors. tests/test_client_e2e.py:141 monkeypatches `_summarization_config` to disable summarization, which is a no-op because nothing reads it.
Why kept: Too costly: the full removal touches 12 files, over the 10-file budget. The 12 are app_config.py, the four config modules, and tests test_app_config_reload, test_app_config_explicit_path, test_authorization_provider, test_client_e2e, test_guardrail_middleware, test_runtime_lifecycle_e2e and test_tool_search. The functions are also importable from the published deerflow-harness package.
Fix when: `grep -rlE 'get_summarization_config|set_summarization_config|load_summarization_config_from_dict|get_tool_search_config|load_tool_search_config_from_dict|get_guardrails_config|load_guardrails_config_from_dict|reset_guardrails_config|get_authorization_config|load_authorization_config_from_dict|reset_authorization_config|"_summarization_config"|"_tool_search_config"|"_guardrails_config"' backend --include=*.py | wc -l` is 10 or fewer, or the owner approves a 12-file change
Added: 2026-11-21, PR #TBD

### duckdb is a core harness dependency used only by a public skill
Where: backend/packages/harness/pyproject.toml dependencies (duckdb>=1.4.4)
What: Only skills/public/data-analysis/scripts/analyze.py and .github/workflows/skill-review-ci.yml import duckdb. No harness or app code does.
Why kept: Needs owner decision. On the local sandbox the skill script runs in the Gateway's Python environment, so removing duckdb would break the data-analysis skill there; the SKILL.md install hint only covers other environments.
Fix when: The data-analysis skill no longer runs in the Gateway's interpreter (for example, the local sandbox gets its own environment), or the owner moves duckdb to an optional extra that the skill's install hint names
Added: 2026-11-21, PR #TBD

### Inline truthy string sets outside the shared coerce_bool
Where: aio_sandbox/local_backend.py:449, projects/documents.py:586, agents/memory/backends/openviking/config.py:197, config/tracing_config.py:122, tui/cli.py:116, app/gateway/auth/session_cookie.py:35, app/gateway/routers/uploads.py:388, app/gateway/routers/github_webhooks.py:83
What: Each module builds its own {"1","true","yes","on"} membership test.
Why kept: These are not copies of coerce_bool. Most read environment variables with no false set and no default. Folding them would change which inputs count as false or unset, and several sit outside this group's ownership (app/, sandbox providers).
Fix when: A shared env-flag helper with the same semantics (truthy set, else False) is added to deerflow.utils, or one of these sites needs to accept the false strings
Added: 2026-11-21, PR #TBD

### Inline dialect INSERT choices and duplicate _dialect validators in persistence
Where: persistence/notification_deliveries/sql.py:167-177, scheduled_task_events/sql.py:72-74, mcp_oauth_tokens/sql.py:48 and :96, channel_leases/sql.py:55 and :85, channel_connections/sql.py:628, user/preferences.py:21, user/im_notifications.py:58 and :86
What: These sites use `sqlite_insert if dialect == ... else pg_insert` inline. mcp_oauth_tokens and channel_leases each define a `_dialect(session)` validator with the same shape.
Why kept: Different shape from the folded helper. Several validate the dialect once and reuse the name for other dialect-specific SQL (db_now); others fall back without raising for unknown dialects. Folding them changes error behavior for unsupported dialects and touches more than 10 files together with tests.
Fix when: A persistence change needs a third `_dialect(session)` validator, or one of these repositories is being edited for another reason (fold that one onto dialect_insert then)
Added: 2026-11-21, PR #TBD

### Locked boxlite 0.9.7 is no longer on the PyPI index
Where: backend/uv.lock [[package]] boxlite (the boxlite extra of deerflow-harness)
What: boxlite 0.9.x is gone from the PyPI simple index, though the locked wheel URLs still download. Any `uv lock` re-resolve therefore bumps it to 0.14.1, which happened here with uv 0.11.32, 0.12.x and 0.13.x. I put the 0.9.7 entry back by hand; `uv lock --check` passes with uv 0.11.1, 0.11.32 and 0.13.5.
Why kept: Bumping the boxlite SDK is a behavior change in a sandbox provider outside this group's ownership and needs testing against the new SDK.
Fix when: The boxlite provider is verified against boxlite>=0.10 (raise the floor in the harness boxlite extra and re-lock), or the next dependency change re-locks the backend
Added: 2026-11-21, PR #TBD

### Web Push calls skip the CSRF header and ignore a failed unsubscribe
Where: frontend/src/core/notification/push.ts:170,192,206
What: subscribeToPush, unsubscribeFromPush and sendTestPush send POST with the global fetch, not core/api/fetcher, so no X-CSRF-Token header is sent. When auth is enabled, the Gateway's CSRFMiddleware (should_check_csrf; /api/push/* is not exempt) answers 403. unsubscribeFromPush also ignores res.ok and unsubscribes in the browser anyway, so the server keeps a dead endpoint. Verified: push.ts has no imports.
Why kept: Fixing it changes behavior: push subscription starts working with auth on, and unsubscribe must handle the failure. That is a bug fix that needs its own PR and tests (push.test.ts), not a quality refactor.
Fix when: A bug-fix PR switches push.ts to core/api/fetcher fetch (or adds the CSRF header) and checks the unsubscribe response, with a push.test.ts case asserting the X-CSRF-Token header on POST.
Added: 2026-11-21, PR #TBD

### useAgentsApiEnabled still sends its own /api/features request
Where: frontend/src/core/agents/hooks.ts:21-27 (queryKey ["features","agents_api"]), frontend/src/core/agents/api.ts:3
What: Ten feature hooks now share the ["features"] query (core/features/query.ts). useAgentsApiEnabled still queries through fetchAgentsApiEnabled under its own key, so a page sends 2 /api/features requests instead of 11.
Why kept: Moving it onto useFeaturesQuery also means removing the fetchAgentsApiEnabled re-export from agents/api.ts and updating the task-form-dialog.dom.test.tsx mock of that export. That takes this finding to 11 files, over the 10-file limit.
Fix when: Do it as its own change: useAgentsApiEnabled uses useFeaturesQuery(selectAgentsApiEnabled, { staleTime: 0, refetchOnMount: true }), fetchAgentsApiEnabled and its re-export are removed, and task-form-dialog.dom.test.tsx mocks fetchFeatures instead. Done when grep -rn '"features", "' frontend/src finds nothing.
Added: 2026-11-21, PR #TBD

### About 22 modules parse Gateway error bodies themselves
Where: frontend/src/core/{subagents,projects,agents,agent-generation,system-prompt,trash,artifacts,mcp,memory,folder-ledger,thread-files,uploads,threads,integrations/lark,capabilities,settings,voice-input,skills}/..., frontend/src/components/workspace/input-box-helpers.ts
What: These modules read {detail} from error responses with their own code instead of core/api/errors.ts (parseGatewayApiError / throwGatewayApiError). Messages and the handling of structured detail differ from module to module.
Why kept: The fix touches more than 10 files, and error text visible to users would change.
Fix when: Split the change into area-sized PRs of 10 files or fewer, each moving a group of modules onto throwGatewayApiError with tests for the message it shows. Done when grep for '"detail" in' and 'body.detail' in frontend/src/core finds only core/api/errors.ts.
Added: 2026-11-21, PR #TBD

### Four byte formatters with different visible formats
Where: frontend/src/components/workspace/messages/message-list-item.tsx:812 formatBytes; frontend/src/core/uploads/file-validation.ts:120 formatUploadSize; frontend/src/core/models/sorting.ts:393 formatModelSize; frontend/src/components/workspace/artifacts/artifact-file-preview.tsx:74 formatArtifactBytes
What: formatBytes prints decimal-looking 'KB/MB' labels (1024-based), '—' for 0 and no GiB. formatUploadSize drops a trailing .0 ('50 MiB'). formatModelSize prints whole MiB below 1 GiB, then GiB with one decimal. formatArtifactBytes prints KiB below 1 MiB and MiB above it, so 1048575 B reads '1024.0 KiB' and 5 GiB reads '5120.0 MiB'. formatFileSize always prints one decimal and moves up a unit at 1024.
Why kept: Merging them changes visible text, and the tests pin each format (file-validation.test.ts, sorting.test.ts). The owner has to pick the format. A level-3 commit moved formatArtifactBytes onto formatFileSize and was reverted, because it changed sizes of 1023.95 KiB and up and GiB-sized files.
Fix when: The owner picks one display format per context. Then they go through formatFileSize, with an option for trailing-zero trimming, plus formatModelSize kept for the VRAM comparison.
Added: 2026-11-21, PR #TBD

### Two formatRunDuration functions with different output
Where: frontend/src/core/usage/format.ts:18 and frontend/src/core/messages/run-duration.ts:127
What: The usage page prints Intl unit text ('1.5 min', '42 sec'). The chat duration badge prints localized parts ('1m 30s', with a less-than-a-second label). They share a name and have different signatures.
Why kept: Unifying them changes visible duration text on one surface. Needs owner decision.
Fix when: The owner chooses one duration format for usage and chat. Until then, renaming one (for example formatUsageRunDuration) removes the name clash without changing output.
Added: 2026-11-21, PR #TBD

### Unreachable model-picker-content.tsx and model favorites
Where: frontend/src/components/workspace/model-picker-content.tsx, frontend/src/core/models/{favorites,favorites-store,use-model-favorites}.ts
What: Nothing renders model-picker-content.tsx, and favorites are used only from it. MODEL_PICKER.md:32-48 documents that this is upstream's code, carried unchanged until favorites are integrated into the fork's picker.
Why kept: Kept on purpose so upstream syncs stay clean (MODEL_PICKER.md). Deleting it is a product and sync decision.
Fix when: Favorites are integrated into the fork's picker, or upstream drops model-picker-content.tsx. Then delete or wire the files and update MODEL_PICKER.md.
Added: 2026-11-21, PR #TBD

### Duplicate memory proxy route handlers
Where: frontend/src/app/api/memory/route.ts and frontend/src/app/api/memory/[...path]/route.ts
What: Both files define the same BACKEND_BASE_URL, buildBackendUrl and proxyRequest. They are reachable only without nginx, which proxies /api/memory itself (docker/nginx/nginx.conf:154).
Why kept: Logged by direction of the task. Merging into an optional catch-all route would change which methods /api/memory accepts.
Fix when: Someone decides whether the Next.js memory proxy is still needed without nginx. If it is, move proxyRequest into a shared non-route module beside the two route.ts files. If not, delete both and document the route.
Added: 2026-11-21, PR #TBD

### Remaining production audit advisories in transitive dependencies
Where: frontend/package.json via @streamdown/mermaid (mermaid <11.16.1, dompurify, lodash-es), @langchain/core (langsmith <0.6.0, uuid), @langchain/langgraph-sdk (uuid), nextra (zod <4.6.6, brace-expansion, minimatch), ai (@ai-sdk/provider-utils <4.0.33), katex <0.18.2 (direct, low)
What: After the next bump and the nuxt-og-image removal, pnpm audit --prod still reports 51 advisories (9 high, 32 moderate, 10 low). All are transitive except katex.
Why kept: Fixing them means upgrading @streamdown/mermaid, @langchain/*, nextra or ai, or adding pnpm overrides. Mermaid and markdown rendering behavior could change, and nextra's zod is held on purpose (pnpm-workspace.yaml override, nextra issue 5036).
Fix when: A dependency PR upgrades each parent to a release that pulls the patched versions (or adds a tested pnpm override) and runs pnpm test, pnpm build and the mermaid/markdown E2E. Done when pnpm audit --prod reports no high findings.
Added: 2026-11-21, PR #TBD

### Copying a scheduled task ID fails silently
Where: frontend/src/components/workspace/scheduled-tasks/task-detail.tsx copyTaskId
What: A failed copy shows nothing. Before this change, .catch(() => undefined) swallowed the error. Now only a successful writeTextToClipboard result shows the toast.
Why kept: Showing a failure toast is new UI and needs new en-US and zh-CN strings. That is a behavior change.
Fix when: A 'copy failed' string is added for scheduled tasks (or a shared one exists). Then copyTaskId shows toast.error when writeTextToClipboard returns false.
Added: 2026-11-21, PR #TBD

### API docs live at /api/docs locally but /docs in Docker and Helm
Where: docker/nginx/nginx.local.conf (location /api/docs, /api/redoc) vs docker/nginx/nginx.conf and deploy/helm/deer-flow/templates/configmap-nginx.yaml (location /docs, /redoc)
What: The same Gateway docs are served under different public paths per deployment.
Why kept: Unifying them changes a public URL; needs an owner decision.
Fix when: The owner picks one public path. Then change the losing config(s) and delete the two RENAMED entries in backend/tests/test_nginx_route_parity.py; the test fails until both are done.
Added: 2026-11-21, PR #TBD

### Helm Live browser stream lacks the connect/send timeouts
Where: deploy/helm/deer-flow/templates/configmap-nginx.yaml, location ~ ^/api/threads/[^/]+/browser/stream
What: Docker and local set proxy_connect_timeout and proxy_send_timeout to 600s on the WebSocket stream. Helm sets only proxy_read_timeout 600s, so it falls back to nginx's 60s defaults. Found by the new parity test.
Why kept: deploy/helm is outside this group's files, and the fix changes Helm runtime behavior.
Fix when: Someone who owns the Helm chart adds the two directives. Then delete the (HELM, browser/stream) entry in test_nginx_route_parity.DIRECTIVE_DIFFERENCES; the test fails until it is removed.
Added: 2026-11-21, PR #TBD

### Helm frontend location forces Connection: upgrade on every request
Where: deploy/helm/deer-flow/templates/configmap-nginx.yaml, location /
What: Helm sends `proxy_set_header Connection 'upgrade'` and has no `map $http_upgrade $connection_upgrade`. Docker and local send $connection_upgrade, so only real upgrade requests are marked. Found by the parity test.
Why kept: deploy/helm is outside this group's files, and the fix changes Helm behavior.
Fix when: The Helm owner adds the map and uses $connection_upgrade. Then delete the (HELM, '/') parity allowlist entry.
Added: 2026-11-21, PR #TBD

### Local nginx forwards X-Forwarded-Proto $scheme (no $forwarded_proto map)
Where: docker/nginx/nginx.local.conf, every location (and its rendered copy from scripts/nginx-local-conf.sh)
What: Behind a TLS-terminating proxy in front of `make dev` (Caddy, Traefik, tailscale serve), the Gateway sees http. Docker's comment says this leads to a 403 'Cross-site auth request denied' on login and to dropped Secure cookie flags. Docker and Helm preserve the upstream scheme through the map. Found by the parity test.
Why kept: This is a behavior change to the local stack, and docker/** was in scope only for parity-test inputs.
Fix when: The owner of docker/nginx adds the forwarded_proto map to nginx.local.conf. Then delete the (LOCAL, '*') entry in test_nginx_route_parity.DIRECTIVE_DIFFERENCES.
Added: 2026-11-21, PR #TBD

### make clean on Windows deletes nothing and still prints Cleanup complete
Where: Makefile clean target (SHELL := cmd.exe on Windows_NT)
What: Under cmd.exe, `rm -rf ... 2>/dev/null || true` fails, and the `-` prefix hides the error. Windows users are told the runtime data was deleted when it was not. The Q3 check is POSIX-only on purpose.
Why kept: Making it really delete changes Windows behavior. Needs an owner decision.
Fix when: The owner agrees Windows `make clean` should delete. Then move the delete and survival check into a script run through $(RUN_SHELL_SCRIPT) (Git Bash), and drop the ifneq guard.
Added: 2026-11-21, PR #TBD

### docker.sh keeps a third dotenv parser with different rules
Where: scripts/docker.sh load_proxy_env_from_dotenv
What: It reads proxy, AUTH_TRUSTED_PROXIES and DEER_FLOW_CREDENTIALS_KEY with its own grep. It ignores `export KEY=` lines and whitespace around `=`, and strips quotes from each end independently. It does not use dotenv_line/dotenv_unquote. Its comment also says Compose runs 'without --env-file', which _refresh_compose_cmd no longer does.
Why kept: Switching it to the shared helpers changes which .env forms are honored for exported credential and proxy values.
Fix when: The owner accepts Compose-style parsing for these keys. Then use dotenv_line/dotenv_unquote from scripts/docker_launch_lib.sh and fix the comment.
Added: 2026-11-21, PR #TBD

### Exposure summary reports local nginx as every-interface
Where: scripts/exposure.py resolve_facts (surface == 'local' hard-codes 0.0.0.0, wildcard) and the scripts/serve.sh comment above the exposure call
What: Verified: docker/nginx/nginx.local.conf listens on 127.0.0.1:2026 and [::1]:2026, and scripts/nginx-local-conf.sh renders BIND_HOST. The summary still says wildcard.
Why kept: Bug fix that changes the output of make dev and make doctor (an output change).
Fix when: The owner accepts the changed output. Then resolve the local bind from BIND_HOST (default 127.0.0.1) the way nginx-local-conf.sh does, and update test_exposure.
Added: 2026-11-21, PR #TBD

### Upstream history docs kept in docs/
Where: docs/CODE_CHANGE_SUMMARY_BY_FILE.md, docs/superpowers/
What: Upstream-owned history docs, relayed as given; both paths exist.
Why kept: Upstream owns them, and deleting them creates sync conflicts.
Fix when: Upstream drops them, or the owner decides to delete them in the fork.
Added: 2026-11-21, PR #TBD

### Compose service definitions duplicated across compose files
Where: docker/docker-compose*.yaml
What: Relayed as given.
Why kept: The fix touches more than 10 files.
Fix when: A change already restructures the compose files, or the owner approves a multi-file consolidation.
Added: 2026-11-21, PR #TBD

### setup-uv step repeated across workflows
Where: .github/workflows/*.yml
What: Counted 13 workflows using astral-sh/setup-uv; the reviewer said 14.
Why kept: The fix touches more than 10 files.
Fix when: The owner approves a composite action or reusable workflow for uv setup.
Added: 2026-11-21, PR #TBD

### MiniMax helpers duplicated across generation skills
Where: skills/public/{image,music,podcast,video}-generation/scripts/generate.py
What: Verified: all four reference minimax.
Why kept: Each skill ships self-contained; sharing code across skills breaks that packaging.
Fix when: The skill packaging supports a shared library resource.
Added: 2026-11-21, PR #TBD

### README/Install.md clone bytedance/deer-flow
Where: README.md (Quick Start, the `git clone` line), Install.md:3 and :38
What: Verified: the fork's install instructions clone upstream.
Why kept: Owner decision on which repository installs should point to.
Fix when: The owner chooses the canonical clone URL.
Added: 2026-11-21, PR #TBD

### DingTalk channel opens one HTTP client per OpenAPI call
Where: backend/app/channels/dingtalk.py (each OpenAPI call runs `async with httpx.AsyncClient(...)`)
What: Every token fetch, send and download builds and closes its own client, so no connection is reused across calls. A level-3 commit pooled one client and was reverted: stop() closed it under in-flight requests, and a call after stop() rebuilt a client that nothing ever closed.
Why kept: A pooled client needs a lifecycle the channel does not have yet, and the per-call cost is small at IM message rates.
Fix when: The pooled client is created in start(), calls after stop() refuse (as the QQ channel's request paths do when the client is None or closed), and stop() waits for in-flight calls before aclose(), with a test for each of the three.
Added: 2026-11-21, PR #TBD
