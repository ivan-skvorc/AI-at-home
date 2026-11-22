"""A CAD module that builds a part without running the model's code.

Installing the package adds one model tool, ``cad_build``. The tool reads a
short CadQuery script as a syntax tree, performs an allow-list of operations
itself in a child process, measures the result and writes STEP, STL and GLB
files into the calling conversation's outputs. See README.md.

Importing this package does not import CadQuery: the kernel is loaded only by
the worker process, so a Gateway with the extension installed starts as fast
as one without it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, ModelTool, PluginContribution, extension
except ModuleNotFoundError as missing:
    # The checks and measure_cli run outside the host too (the CAD eval, a container), where the
    # extension API is not installed. The package still imports there; it just offers no install().
    if missing.name != "deerflow_extension_api":
        raise
    extension = None

__all__ = ["NAMESPACE", "TOOL_GROUP", "install"]

NAMESPACE = "cad"
#: The harness keeps this group when the conversation's internet switch is off
#: (``deerflow.tools.internet_access.LOCAL_EXTENSION_TOOL_GROUP``). The literal is
#: repeated here because the package depends on the extension API only.
TOOL_GROUP = "local_extensions"


if extension is not None:
    from deerflow_extension_cad.tool import DESCRIPTION, INPUT_SCHEMA, make_handler, settings_from

    # 0.2.13 is the first API whose ToolContext can write a file into a conversation.
    @extension(api="0.2.13", name="cad")
    def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
        """Register the ``cad_build`` tool. In this fork the package ships installed and its record enabled."""
        if config.get("enabled", True) is False:
            return
        settings = settings_from(config)
        registry.plugin(
            PluginContribution(
                namespace=NAMESPACE,
                title="CAD parts",
                description="Builds a mechanical part from a CadQuery script without running the script, checks it, and saves STEP, STL and GLB files.",
                enabled=True,
                tools=(ModelTool("cad_build", DESCRIPTION, INPUT_SCHEMA, make_handler(settings), TOOL_GROUP),),
            )
        )

    _entry_point: ExtensionInstall = install
