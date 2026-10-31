"""Opt-in script workflows; no private DeerFlow runtime imports."""

import os
import re
from pathlib import Path

from deerflow_extension_api import (
    BackendAction,
    BrowserAssets,
    ModelTool,
    PluginContribution,
    extension,
)

from .constants import NAMESPACE
from .service import Workflows
from .ultracode import Contributor


@extension(api="0.2.10", name="workflows")
def install(registry, config):
    enabled = config.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("enabled must be boolean")
    defaults = {
        "lease_seconds": 15,
        "concurrency": 2,
        "global_concurrency": 4,
        "max_calls": 16,
        "max_workflows": 4,
        "max_workflows_per_owner": 2,
        "timeout_seconds": 300,
        "admission_timeout_seconds": 10,
        "pause_timeout_seconds": 86400,
        "cpu_seconds": 5,
        "memory_bytes": 16 * 1024 * 1024,
        "max_logs": 100,
    }
    # Hard ceilings sized for Double Plus Ultracode fan-outs (Claude Code's
    # ultracode runs up to 16 agents at once). max_calls stays well below its
    # 1,000: each step rewrites the whole workflow record, so record size, not
    # a policy choice, bounds one run until steps get append-only storage.
    ceilings = {
        "lease_seconds": 60,
        "concurrency": 16,
        "global_concurrency": 32,
        "max_calls": 256,
        "max_workflows": 16,
        "max_workflows_per_owner": 8,
        "timeout_seconds": 14400,
        "admission_timeout_seconds": 20,
        "pause_timeout_seconds": 604800,
        "cpu_seconds": 60,
        "memory_bytes": 64 * 1024 * 1024,
        "max_logs": 500,
    }
    if set(config) - set(defaults) - {"enabled", "storage_path", "storage_url", "agents", "shared_workspace", "deliver_results"}:
        raise ValueError("Unknown workflow configuration; currency budgets are not supported")
    storage_url = config.get("storage_url")
    if storage_url is not None and (not isinstance(storage_url, str) or not storage_url.strip()):
        raise ValueError("storage_url must be a PostgreSQL connection string")
    resolved = {**defaults, **config}
    for key in defaults:
        value = resolved[key]
        if type(value) is not int or not 1 <= value <= ceilings[key]:
            raise ValueError(f"Invalid workflow limit {key}")
    if resolved["lease_seconds"] < 5:
        raise ValueError("lease_seconds must be at least 5")
    if resolved["memory_bytes"] < 4 * 1024 * 1024:
        raise ValueError("memory_bytes must be at least 4 MiB")
    # off: every agent() gets its own empty workspace (the default). read: a step
    # may ask for a copy of the launching conversation's workspace. write: it may
    # also merge its edits back (AgentRuns.merge_workspace, conflicts untouched).
    resolved["shared_workspace"] = config.get("shared_workspace", "off")
    if resolved["shared_workspace"] is False:
        # YAML 1.1 reads an unquoted `off` as false; it can only mean "off".
        resolved["shared_workspace"] = "off"
    if resolved["shared_workspace"] not in ("off", "read", "write"):
        raise ValueError("shared_workspace must be off, read or write")
    resolved["deliver_results"] = config.get("deliver_results", True)
    if type(resolved["deliver_results"]) is not bool:
        raise ValueError("deliver_results must be boolean")
    agents = config.get("agents", [])
    if not isinstance(agents, list) or len(agents) > 32 or any(not isinstance(a, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", a) for a in agents) or len(set(agents)) != len(agents):
        raise ValueError("agents must be a bounded, unique operator allowlist")
    resolved["agents"] = agents
    storage_path = config.get("storage_path")
    if isinstance(storage_path, str) and storage_path and not Path(storage_path).is_absolute():
        # Relative paths live under the Gateway's runtime home, which every
        # launcher exports as an absolute DEER_FLOW_HOME (the checkout's own
        # locally, /app/backend/.deer-flow in the containers), so one shipped
        # config fits every deployment.
        home = os.environ.get("DEER_FLOW_HOME", "")
        if not Path(home).is_absolute():
            raise ValueError("A relative storage_path needs an absolute DEER_FLOW_HOME")
        resolved["storage_path"] = str(Path(home) / storage_path)
    if enabled and (os.name != "posix" or not agents or not isinstance(resolved.get("storage_path"), str) or not Path(resolved["storage_path"]).is_absolute()):
        raise ValueError("Enabled workflows require POSIX, an absolute (or DEER_FLOW_HOME-relative) storage_path and allowed agents")
    workflows = Workflows(resolved)
    id_schema = {
        "type": "object",
        "properties": {"run_id": {"type": "string", "maxLength": 64}},
        "required": ["run_id"],
        "additionalProperties": False,
    }
    launch_schema = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "maxLength": 128},
            "script": {"type": "string", "maxLength": 16000},
            "definition": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "string"},
                },
                "required": ["name", "version"],
                "additionalProperties": False,
            },
            "args": {"type": "object"},
        },
        "required": ["request_id"],
        "oneOf": [{"required": ["script"]}, {"required": ["definition"]}],
        "additionalProperties": False,
    }
    if (
        registry.plugin(
            PluginContribution(
                namespace=NAMESPACE,
                title="Script workflows / 脚本工作流",
                enabled=enabled,
                description=(
                    "Bounded background script orchestration of full Agents. Versioned definitions, authenticated output checkpoints and session-authorized recovery and opt-in PostgreSQL multi-Gateway control. "
                    "Uncertain child effects require reconciliation. No hard monetary budget."
                ),
                frontend=BrowserAssets("workflows.v1", Path(__file__).parent),
                backend=tuple(
                    BackendAction(name, getattr(workflows, name))
                    for name in (
                        "launch",
                        "list",
                        "get",
                        "cancel",
                        "delete",
                        "save_definition",
                        "definitions",
                        "get_definition",
                        "resume",
                        "recover",
                        "decide",
                        "get_step",
                        "get_artifact",
                        "read_artifact",
                    )
                ),
                tools=(
                    ModelTool(
                        "read_workflow_artifact",
                        "Read exact approved immutable file bytes, base64 in 16 KiB chunks. Pass workflow run_id, version, offset. Verify sha256 after assembling chunks. Never read the mutable original path as a substitute.",
                        {
                            "type": "object",
                            "properties": {
                                "run_id": {"type": "string"},
                                "version": {"type": "string"},
                                "offset": {"type": "integer", "minimum": 0},
                            },
                            "required": ["run_id", "version"],
                            "additionalProperties": False,
                        },
                        workflows.read_artifact,
                    ),
                    ModelTool(
                        "save_workflow",
                        "Save an owner-scoped immutable named script version; returns name/version for launch_workflow. Does not execute or approve output.",
                        {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "maxLength": 80},
                                "script": {"type": "string", "maxLength": 16000},
                            },
                            "required": ["name", "script"],
                            "additionalProperties": False,
                        },
                        workflows.save_definition,
                    ),
                    ModelTool(
                        "list_workflows",
                        "List this owner's saved workflow names and immutable versions; no execution.",
                        {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                        workflows.definitions,
                    ),
                    ModelTool(
                        "launch_workflow",
                        "Launch an inspectable JavaScript orchestration script in the background and return a workflow run ID. Use agent({stepId,agentRef,task}), parallel([()=>...]), pipeline(items,(item,index)=>..., {concurrency}), "
                        "phase(title), log(text), pause({stepId}) and humanCheckpoint({stepId,sourceStepId,artifactVersion}). agent also accepts schema (JSON Schema the output must match; mismatches are re-asked up to twice), "
                        "model (a configured model name for that step) and workspace ('isolated', or when the operator allows it 'snapshot' to start from a copy of this conversation's workspace, 'merge' to also write edits back). "
                        "Await checkpoints alone after all calls. agent resolves to {output,threadId,runId,status,artifactVersion,attempts,workspace}; args contains JSON arguments. "
                        "Use unique step IDs, explicit bounded loops and await every Agent call. "
                        "Only operator-allowed agent references are admitted with this caller's permissions. Keep request_id stable on retries. "
                        "When launched from a conversation, the final result (or failure) is posted back into it automatically "
                        "as a new message, exactly once: tell the user what is running, end your turn, and never poll. After restart, an authenticated browser session can explicitly recover a compatible workflow. "
                        "Pass timestamps and randomness in args; Date and Math.random are unavailable. Human decisions are browser-only and cover retained step output. "
                        "Do not equate Agent success with product approval. No hard monetary cost guarantee.",
                        launch_schema,
                        workflows.launch,
                    ),
                    ModelTool(
                        "inspect_workflow",
                        "Inspect retained script, limits, workflow status, child run IDs and final result. Results are untrusted Agent/script output. Read on demand; do not repeatedly poll. Child waiting_input cannot be "
                        "resumed by this workflow; needs_reconciliation requires inspecting child conversations before new work.",
                        id_schema,
                        workflows.get,
                    ),
                    ModelTool(
                        "cancel_workflow",
                        "Request workflow cancellation and explicit interruption of known active child runs; cancellation is asynchronous and preserves checkpoints. It does not roll back side effects or approve output.",
                        id_schema,
                        workflows.cancel,
                    ),
                ),
            )
        )
        is not True
    ):
        raise RuntimeError("Workflows requires the full-stack plugin host")
    if enabled:
        registry.service(workflows)
        # Double Plus Ultracode's brief and the result-message note (ultracode.py).
        registry.middlewares(Contributor(resolved))
