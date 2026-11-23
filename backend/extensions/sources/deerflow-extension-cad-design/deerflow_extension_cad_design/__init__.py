"""The CAD design page: OpenSCAD drafts rendered in the browser, then a CadQuery part.

A design is its own stored entity with automatic versions (store.py). The model
drafts with ``scad_draft``, which only stores the file (tool.py); the page
renders it in the viewer's browser with OpenSCAD compiled to WebAssembly, so
the Gateway never runs model-written OpenSCAD or Python. Finalize starts a run
that ports the draft to CadQuery and builds it with the CAD module's
``cad_build`` (middleware.py records the result). The browser half is under
``ui/`` and ships as ``static/dist`` with ``ui_manifest.json``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import BackendAction, BrowserAssets, ExtensionInstall, ExtensionRegistry, ModelTool, PluginContribution, extension

from .actions import ACTIONS, Designs
from .constants import NAMESPACE, TOOL, TOOL_GROUP
from .middleware import Contributor
from .router import build_router
from .store import Store
from .tool import DESCRIPTION, INPUT_SCHEMA, make_handler

__all__ = ["NAMESPACE", "install"]

DEFAULTS: dict[str, Any] = {"enabled": True, "storage_path": "cad-design/designs.sqlite", "max_source_bytes": 65536}
MAX_SOURCE_BYTES = 256 * 1024


def resolve_config(config: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown cad-design configuration: {', '.join(sorted(unknown))}")
    resolved = {**DEFAULTS, **config}
    if type(resolved["enabled"]) is not bool:
        raise ValueError("enabled must be a boolean")
    size = resolved["max_source_bytes"]
    if type(size) is not int or not 1024 <= size <= MAX_SOURCE_BYTES:
        raise ValueError(f"max_source_bytes must be an integer from 1024 to {MAX_SOURCE_BYTES}")
    path = resolved["storage_path"]
    if not isinstance(path, str) or not path:
        raise ValueError("storage_path must be a path")
    if not Path(path).is_absolute():
        # Relative paths live under the Gateway's runtime home, which every
        # launcher exports as an absolute DEER_FLOW_HOME, so `make backup` keeps them.
        home = os.environ.get("DEER_FLOW_HOME", "")
        if not Path(home).is_absolute():
            raise ValueError("A relative storage_path needs an absolute DEER_FLOW_HOME")
        resolved["storage_path"] = str(Path(home) / path)
    return resolved


# 0.2.14 is the first API whose AgentRuns.start takes stream_mode.
@extension(api="0.2.14", name="cad-design")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    resolved = resolve_config(config)
    store = Store(resolved["storage_path"])
    designs = Designs(store, resolved["max_source_bytes"])
    accepted = registry.plugin(
        PluginContribution(
            namespace=NAMESPACE,
            title="CAD designs / CAD 设计",
            description="Draft a part in OpenSCAD with the assistant, see it rendered in your browser, tune its parameters, and finalize it as a checked CadQuery part.",
            enabled=resolved["enabled"],
            frontend=BrowserAssets(module="cad-design", root=Path(__file__).parent),
            backend=tuple(BackendAction(name, getattr(designs, name)) for name in ACTIONS),
            tools=(ModelTool(TOOL, DESCRIPTION, INPUT_SCHEMA, make_handler(store, resolved["max_source_bytes"]), TOOL_GROUP),),
        )
    )
    if accepted is not True:
        raise RuntimeError("The CAD design page requires the full-stack plugin host")
    # Registered even when the record starts disabled: an administrator can switch the
    # plugin on at runtime, and the tool must never reach an ordinary conversation.
    # The middleware removes it from every model call that is not a design run.
    registry.middlewares(Contributor(store))
    registry.routers((build_router(store),))


_entry_point: ExtensionInstall = install
