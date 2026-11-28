"""The CAD design page: a design's conversation with its rendered versions beside it.

A design is a stored title and a hidden conversation (store.py). The model
follows the cad-modeling skill in that conversation's per-thread container:
it writes multi-body OpenSCAD and renders it with cadkit, and every render is
the next version folder under ``/mnt/user-data/outputs/design``. The Gateway
executes nothing: the backend actions (actions.py) manage designs and runs,
the lead middleware (middleware.py) adds the design brief to design runs only,
and the page lists and reads the version folders through the host's thread
file routes. The browser half is under ``ui/`` and ships as ``static/dist``
with ``ui_manifest.json``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import BackendAction, BrowserAssets, ExtensionInstall, ExtensionRegistry, PluginContribution, extension

from .actions import ACTIONS, Designs, HostSandbox
from .constants import NAMESPACE
from .middleware import Contributor
from .store import Store

__all__ = ["NAMESPACE", "install"]

DEFAULTS: dict[str, Any] = {"enabled": True, "storage_path": "cad-design/designs.sqlite"}
#: Keys an earlier release took. Migration 79 of scripts/config_upgrade.py removes
#: them; until it has run, an existing config.yaml still carries them, and refusing
#: them would stop the extension from loading. They are accepted and ignored.
RETIRED: frozenset[str] = frozenset({"max_source_bytes"})


def resolve_config(config: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(config) - set(DEFAULTS) - RETIRED
    if unknown:
        raise ValueError(f"Unknown cad-design configuration: {', '.join(sorted(unknown))}")
    resolved = {**DEFAULTS, **{key: value for key, value in config.items() if key not in RETIRED}}
    if type(resolved["enabled"]) is not bool:
        raise ValueError("enabled must be a boolean")
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


# 0.2.15 is the first API whose host policy says whether runs have per-thread containers;
# 0.2.14 added AgentRuns.start(stream_mode=...) and delete_thread, which this also uses.
@extension(api="0.2.15", name="cad-design")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    resolved = resolve_config(config)
    store = Store(resolved["storage_path"])
    sandbox = HostSandbox()
    designs = Designs(store, sandbox)
    accepted = registry.plugin(
        PluginContribution(
            namespace=NAMESPACE,
            title="CAD designs / CAD 设计",
            description="Design a part with the assistant: it writes OpenSCAD and renders, checks and exports it in the conversation's CAD container; each render is a version with its bodies in 3D, views, checks and files.",
            enabled=resolved["enabled"],
            frontend=BrowserAssets(module="cad-design", root=Path(__file__).parent),
            backend=tuple(BackendAction(name, getattr(designs, name)) for name in ACTIONS),
        )
    )
    if accepted is not True:
        raise RuntimeError("The CAD design page requires the full-stack plugin host")
    # Registered even when the record starts disabled: an administrator can switch the
    # plugin on at runtime, and the brief must reach only design runs from the start.
    registry.middlewares(Contributor(store))
    # Reads the host's sandbox mode once the Gateway is up (HostPolicySnapshot.sandbox_container).
    registry.service(sandbox)


_entry_point: ExtensionInstall = install
