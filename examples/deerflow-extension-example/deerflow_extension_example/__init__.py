"""A compact, standalone DeerFlow extension exercising six contribution kinds."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_extension_example.plugin import (
    ExampleMiddlewareContributor,
    ExampleService,
    ExampleSystemObserver,
    ExampleTaskLifecycle,
    build_notes_plugin,
    build_router,
)

__all__ = ["install"]


# 0.2.12 is the first API whose ToolContext can write a file into a conversation.
@extension(api="0.2.12", name="example")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register one middleware, task lifecycle, system-model observer, service, router, and plugin tool."""
    if config.get("enabled", True) is False:
        return

    service = ExampleService()
    registry.middlewares(ExampleMiddlewareContributor())
    registry.task_lifecycle(ExampleTaskLifecycle())
    registry.system_model_observer(ExampleSystemObserver())
    registry.service(service)
    registry.routers((build_router(service),))
    # False means this host has no plugin support; the other five still work.
    registry.plugin(build_notes_plugin())


_entry_point: ExtensionInstall = install
