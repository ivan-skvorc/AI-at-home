# Tools: fork notes

Reference detail for [AGENTS.md](AGENTS.md), which holds the rules. Each
feature's rationale is in the FORK.md section named beside it.

## The per-conversation internet switch (`internet_access.py`, FORK.md §27)

`get_available_tools(..., internet_enabled=False)` drops every tool that reaches
the internet on the model's behalf, before any downstream layer sees a catalog.
Four invariants, all silent when broken:

- **Only an explicit `False` opts out** (`internet_access_enabled`). Absent means
  "no opinion": IM channels, the TUI, the scheduler and embedded callers send no
  key and must keep the configured tools. `"false"` and `0` are not opt-outs; the
  frontend normalizes before sending.
- **The group classification is an allowlist** (`OFFLINE_ALLOWED_TOOL_GROUPS`:
  `file:read`, `file:write`, `bash`, `media`, `knowledge`). An unrecognized group
  is dropped. Do not rewrite it as a blocklist of `web`/`browser`: that passes the
  next provider group anyone adds. MCP and ACP tools are dropped wholesale.
- **Filter here, not at call time.** Removing the tool from the catalog is what
  keeps deferred tool search, skill `allowed-tools` policy and the bound tool
  schemas consistent. A `GuardrailProvider` deny would be one exemption away from
  being bypassed.
- **`task_tool` inherits it from the parent run context**, so delegation is not an
  escape hatch; the lead-agent factory writes the resolved value back into
  `context` and `configurable`.

`bash` deliberately stays: the shell is the sandbox's local execution surface,
and its network belongs to the operator's container. Pinned by
`tests/test_internet_toggle.py`.

## Grok subscription tools (FORK.md §43)

Every exclusion rule in `_select_tool_configs` is a per-entry predicate. The
Grok one drops a tool whose `required_grok_feature(tool.use)` is not in
`AppConfig._subscription_features`: the operator switched the feature on and the
plan is not known to refuse it, read from the same snapshot as the run's
subscription models. Grok media sits in the `cloud_media` group, not `media`, so
the internet switch also removes it. Exposure is decided twice; the
[xAI guide](../community/xai/AGENTS.md) explains why both checks stay. Pinned by
`tests/test_grok_features.py::test_tools_appear_only_for_ready_features`.
