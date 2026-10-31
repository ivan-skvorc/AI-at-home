"""Unified, optional browser/backend contributions from one trusted package.

Backend actions run in the Gateway process. The host supplies current settings
and an authenticated principal for each admitted call; this is not a sandbox.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from deerflow_extension_api.agent_runs import AgentRuns
from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.settings import FrontendBinding, SettingsContribution, SettingsField, SettingValue

#: Run-context key carrying per-run options a client addresses to plugins by
#: namespace (API 0.2.10). The host keeps it run-only (never a checkpoint
#: default) and bounds its size; the values are untrusted user input, so a
#: plugin validates and clamps them against its own operator configuration.
PLUGIN_OPTIONS_CONTEXT_KEY = "plugin_options"

_EMPTY_OPTIONS: Mapping[str, Any] = MappingProxyType({})


def plugin_run_options(context: Mapping[str, Any] | None, namespace: str) -> Mapping[str, Any]:
    """Return one plugin's slice of a run context's ``plugin_options``, read-only.

    Middleware reads it from ``runtime.context``; model tools receive the same
    slice as :attr:`ToolContext.run_options`. Anything malformed reads as empty.
    """
    if not isinstance(context, Mapping):
        return _EMPTY_OPTIONS
    options = context.get(PLUGIN_OPTIONS_CONTEXT_KEY)
    if not isinstance(options, Mapping):
        return _EMPTY_OPTIONS
    selected = options.get(namespace)
    if not isinstance(selected, Mapping):
        return _EMPTY_OPTIONS
    return MappingProxyType(dict(selected))


@dataclass(frozen=True)
class ActionContext:
    principal: ExtensionPrincipal
    settings: Mapping[str, SettingValue]
    agent_runs: AgentRuns | None = field(default=None, kw_only=True)
    # Host-stamped browser session; model tools and other callers default closed.
    interaction: Literal["session", "other"] = field(default="other", kw_only=True)


@dataclass(frozen=True)
class BackendAction:
    name: str
    handler: Callable[[Mapping[str, Any], ActionContext], Awaitable[Any]]


@dataclass(frozen=True)
class ToolContext(ActionContext):
    """Host-bound identity for a model tool call.

    Resource ownership remains the plugin provider's responsibility,
    using principal.user_id. ``run_options`` is this plugin's slice of the
    calling run's ``plugin_options`` (see :func:`plugin_run_options`).
    """

    thread_id: str | None
    run_options: Mapping[str, Any] = field(default=_EMPTY_OPTIONS, kw_only=True)


@dataclass(frozen=True)
class PluginToolResult:
    """Model-visible text plus optional JSON artifact for an opted-in tool."""

    content: str
    artifact: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ModelTool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any], ToolContext], Awaitable[Any]]
    group: str = "extensions"
    response_format: Literal["content", "content_and_artifact"] = field(default="content", kw_only=True)


@dataclass(frozen=True)
class BrowserModule:
    """Self-contained browser module; use BrowserAssets for relative resources."""

    module: str
    code: str
    public_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_fields", tuple(self.public_fields))


@dataclass(frozen=True)
class BrowserAssets:
    """Versioned manifest and static files inside a trusted installed package.

    The host validates and snapshots the allowlisted files during registration.
    Relative paths in the manifest are resolved against root, never a request.
    """

    module: str
    root: str | Path
    manifest: str = "ui_manifest.json"
    public_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_fields", tuple(self.public_fields))


@dataclass(frozen=True)
class PluginContribution:
    """One identity, one enabled switch, optional settings and implementations.

    The host owns the boolean ``enabled`` field. Other fields are non-secret
    settings, private to the backend unless explicitly projected by its browser declaration.
    Supply at least one browser module, backend action, or model tool. Backend implementations
    are installed through the existing operator-controlled Python loader.
    """

    namespace: str
    title: str
    description: str = ""
    enabled: bool = False
    fields: tuple[SettingsField, ...] = ()
    frontend: BrowserModule | BrowserAssets | None = None
    backend: tuple[BackendAction, ...] = ()
    api_version: int = 1
    tools: tuple[ModelTool, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "backend", tuple(self.backend))
        object.__setattr__(self, "tools", tuple(self.tools))

    def settings_contribution(self) -> SettingsContribution:
        return SettingsContribution(
            namespace=self.namespace,
            title=self.title,
            description=self.description,
            fields=(SettingsField("enabled", "启用 / Enabled", "boolean", self.enabled), *self.fields),
            applies="request-and-page-load" if (self.backend or self.tools) and self.frontend else "next-request" if self.backend or self.tools else "page-load",
            frontend=FrontendBinding(self.frontend.module, ("enabled", *self.frontend.public_fields)) if self.frontend else None,
        )
