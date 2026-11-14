"""Unified plugins participate in the ordinary tool assembly and authorization path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType

from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.host_capabilities import HostCapabilityError
from deerflow_extension_api.plugins import PluginToolResult, ToolContext, plugin_run_options
from jsonschema import Draft202012Validator
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool, ToolException
from langgraph.types import Command

from deerflow.config.plugin_settings import defaults
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.tool_provenance import tag_plugin_tool

logger = logging.getLogger(__name__)


def plugin_settings(source, plugin):
    """Unified plugins use their deployment-owned manifest; no runtime override."""
    return defaults(plugin.settings_contribution())


def validate_schema(schema, *, tool=False):
    try:
        plain = json.loads(json.dumps(schema))
        if plain.get("type") != "object":
            raise ValueError("Plugin schemas must describe objects")

        # No reference resolution or network access during validation.
        def check(value):
            if isinstance(value, dict):
                if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                    raise ValueError("Inline plugin schemas are required")
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(plain)
        if tool and {"runtime", "config"} & plain.get("properties", {}).keys():
            raise ValueError("Reserved tool argument")
        Draft202012Validator.check_schema(plain)
    except Exception as exc:
        raise ValueError("Invalid plugin object schema") from exc


# Providers reject these at the root of a tool's parameters, and the 400 fails
# every request the tool is bound to, not just calls to it. They stay valid in
# the declared schema: each call is still validated against it in full.
_ROOT_ONLY_HOST_KEYWORDS = frozenset({"oneOf", "anyOf", "allOf", "enum", "not"})


def _model_facing_schema(schema):
    return {key: value for key, value in schema.items() if key not in _ROOT_ONLY_HOST_KEYWORDS}


def plugin_tool_name(namespace, name):
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).hexdigest()[:12]
    return f"ext_{re.sub('[^a-z0-9_]', '_', namespace)[:20]}_{name[:25]}_{digest}"


def _validate_artifact_keys(value):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Artifact object keys must be strings")
        for child in value.values():
            _validate_artifact_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_artifact_keys(child)


# --- A tool hands a file to its conversation (fork, FORK.md §50) -------------


def _checked_output_name(name):
    """Refuse anything but a bare file name; a path is never rewritten into one."""
    try:
        valid = isinstance(name, str) and 0 < len(name.encode()) <= 255
    except UnicodeError:
        valid = False
    if not valid or name == "." or ".." in name or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in name):
        raise HostCapabilityError("INVALID_NAME", "use a plain file name without a path")


def _output_limits(context):
    from deerflow.config.app_config import AppConfig, PluginOutputsConfig, get_app_config

    # The worker pins the run's AppConfig in the context. Anything else under
    # that key is not operator config, so the file is read instead.
    config = context.get("app_config")
    if not isinstance(config, AppConfig):
        try:
            config = get_app_config()
        except FileNotFoundError:
            # An embedded harness without a config.yaml has no operator value to read.
            return PluginOutputsConfig()
    return config.plugin_outputs


def _write_conversation_output(recorded, thread_id, user_id, name, content):
    from deerflow.community.comfyui.service import write_output
    from deerflow.config.paths import get_paths
    from deerflow.utils.output_names import output_name_candidates

    try:
        outputs_dir = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id)
    except ValueError:
        outputs_dir = None
    # The run's own thread and user decide the destination. Run state must name
    # the same directory, so a state that points elsewhere is not authority.
    if outputs_dir is None or not isinstance(recorded, str) or not recorded or Path(recorded) != outputs_dir:
        raise HostCapabilityError("FORBIDDEN", "this call is not bound to its conversation's outputs")
    for candidate in output_name_candidates(name):
        try:
            return write_output(outputs_dir, candidate, content, exclusive=True)
        except FileExistsError:
            continue
    raise HostCapabilityError("UNAVAILABLE", "no free file name")


class _CallOutputs:
    """What one tool call writes into the outputs of the conversation that called it."""

    def __init__(self, runtime, context, thread_id, user_id):
        self._runtime = runtime
        self._context = context
        self._thread_id = thread_id
        self._user_id = user_id
        self._bytes = 0
        self.paths = []
        self.ended = False

    async def write(self, name, content):
        if self.ended:
            # A writer kept after its call returned is bound to nothing.
            raise HostCapabilityError("FORBIDDEN", "this tool call has ended")
        _checked_output_name(name)
        if not isinstance(content, bytes):
            raise HostCapabilityError("INVALID_CONTENT", "content must be bytes")
        limits = await asyncio.to_thread(_output_limits, self._context)
        # Checked and reserved in one step, before the first byte: concurrent
        # writes of one call cannot pass the per-call cap together.
        if len(content) > limits.max_file_bytes or self._bytes + len(content) > limits.max_call_bytes:
            raise HostCapabilityError("LIMIT_EXCEEDED", f"a file may hold {limits.max_file_bytes} bytes and one call {limits.max_call_bytes} bytes")
        self._bytes += len(content)
        try:
            path = await self._deliver(name, content)
        except BaseException:
            self._bytes -= len(content)
            raise
        self.paths.append(path)
        return path

    async def _deliver(self, name, content):
        state = self._runtime.state
        thread_data = state.get("thread_data") if isinstance(state, Mapping) else None
        recorded = thread_data.get("outputs_path") if isinstance(thread_data, Mapping) else None
        try:
            written = await asyncio.to_thread(_write_conversation_output, recorded, self._thread_id, self._user_id, name, content)
            from deerflow.sandbox.sandbox_provider import get_sandbox_provider

            if not getattr(get_sandbox_provider(), "uses_thread_data_mounts", False):
                # This sandbox does not see the host's thread data. Give the run's
                # own sandbox the same bytes, or take the host copy back.
                from deerflow.sandbox.tools import ensure_sandbox_initialized_async

                try:
                    sandbox = await ensure_sandbox_initialized_async(self._runtime)
                    await asyncio.to_thread(sandbox.update_file, written.virtual_path, content)
                except BaseException:
                    await asyncio.to_thread(written.path.unlink, missing_ok=True)
                    raise
            return written.virtual_path
        except HostCapabilityError:
            raise
        except Exception as exc:
            logger.warning("Plugin file output failed (%s)", type(exc).__name__)
            raise HostCapabilityError("UNAVAILABLE", "the file could not be written") from None


def _register_outputs(runtime, name, outputs, content, artifact):
    """Register a successful call's files the way a built-in tool's Command does."""
    call_id = getattr(runtime, "tool_call_id", None)
    if outputs is None or not outputs.paths or not call_id:
        return None
    message = ToolMessage(content=content, artifact=artifact, tool_call_id=call_id, name=name)
    return Command(update={"messages": [message], "artifacts": list(outputs.paths)})


def _build_tool(source, plugin, declaration):
    schema = deepcopy(dict(declaration.input_schema))
    validator = Draft202012Validator(schema)
    name = plugin_tool_name(plugin.namespace, declaration.name)

    async def invoke(runtime: ToolRuntime, **payload):
        try:
            settings = await asyncio.to_thread(plugin_settings, source, plugin)
            if settings["enabled"] is not True:
                raise ToolException("Plugin disabled by administrator.")
            if len(json.dumps(payload, allow_nan=False).encode()) > 256 * 1024 or not validator.is_valid(payload):
                raise ToolException("Invalid plugin tool input.")
            context = runtime.context if isinstance(runtime.context, Mapping) else {}
            runs = context.get(AGENT_RUNS_CONTEXT_KEY)
            user_id = resolve_runtime_user_id(runtime)
            thread_id = context.get("thread_id")
            # Bound to the thread the run executes in; the tool names neither.
            outputs = _CallOutputs(runtime, context, thread_id, user_id) if isinstance(thread_id, str) and thread_id else None
            tool_context = ToolContext(
                ExtensionPrincipal(user_id),
                MappingProxyType(settings),
                thread_id,
                run_id=context.get("run_id"),
                output_writer=outputs.write if outputs is not None else None,
                agent_runs=runs.for_plugin(plugin.namespace) if runs is not None else None,
                # Only this plugin's slice, detached from the run context (the
                # Gateway bounded it in sanitize_plugin_options).
                run_options=MappingProxyType(deepcopy(dict(plugin_run_options(context, plugin.namespace)))),
            )
            try:
                async with asyncio.timeout(30):
                    result = await declaration.handler(MappingProxyType(payload), tool_context)
            finally:
                if outputs is not None:
                    outputs.ended = True
            if declaration.response_format == "content_and_artifact":
                if not isinstance(result, PluginToolResult) or not isinstance(result.content, str) or (result.artifact is not None and not isinstance(result.artifact, Mapping)):
                    raise TypeError("Expected PluginToolResult with text and a JSON object artifact")
                _validate_artifact_keys(result.artifact)
                artifact = result.artifact
                if artifact is not None and not isinstance(artifact, dict):
                    artifact = dict(artifact)
                envelope = {"content": result.content, "artifact": artifact}
                encoded = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode()) > 64 * 1024:
                    raise ToolException("Plugin result exceeds 64 KiB.")
                # A JSON roundtrip detaches nested values retained by the handler.
                artifact = json.loads(encoded)["artifact"]
                registered = _register_outputs(runtime, name, outputs, result.content, artifact)
                return (registered, None) if registered is not None else (result.content, artifact)
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > 64 * 1024:
                raise ToolException("Plugin result exceeds 64 KiB.")
            return _register_outputs(runtime, name, outputs, encoded, None) or encoded
        except ToolException:
            raise
        except Exception as exc:
            logger.warning("Plugin tool failed: %s/%s (%s)", plugin.namespace, declaration.name, type(exc).__name__)
            raise ToolException("Plugin tool unavailable or input rejected.") from None

    options = {"response_format": "content_and_artifact"} if declaration.response_format == "content_and_artifact" else {}
    tool = StructuredTool(name=name, description=declaration.description, args_schema=_model_facing_schema(schema), coroutine=invoke, handle_tool_error=True, **options)
    tag_plugin_tool(tool, namespace=plugin.namespace, declaration=declaration.name, installation=source)
    return tool


def build_plugin_tools(loaded, *, groups=None, reserved_names=()):
    tools = []
    names = set(reserved_names)
    for source, plugin in loaded.plugins:
        if not plugin.tools:
            continue
        try:
            if plugin_settings(source, plugin)["enabled"] is not True:
                continue
        except Exception as exc:
            logger.warning("Plugin policy unavailable: %s (%s)", plugin.namespace, type(exc).__name__)
            continue
        for declaration in plugin.tools:
            if groups is not None and declaration.group not in groups:
                continue
            tool = _build_tool(source, plugin, declaration)
            if tool.name in names:
                raise ValueError(f"Plugin tool name collision: {tool.name}")
            names.add(tool.name)
            tools.append(tool)
    return tools
