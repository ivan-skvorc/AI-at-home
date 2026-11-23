"""Names shared by the tool, the actions, the middleware and the route."""

from __future__ import annotations

import hashlib
import re

NAMESPACE = "cad-design"
TOOL = "scad_draft"
#: The harness keeps this group when a conversation's internet switch is off; the
#: literal is repeated because the package depends on the extension API only.
TOOL_GROUP = "local_extensions"
#: The CAD module's tool, which a finalize run calls (examples/deerflow-extension-cad).
CAD_NAMESPACE = "cad"
CAD_TOOL = "cad_build"
PHASES = frozenset({"draft", "repair", "finalize"})
ID = re.compile(r"[0-9a-f]{32}")
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def bound_tool_name(namespace: str, name: str) -> str:
    """The name the host binds a plugin tool under.

    The same formula as ``deerflow.extensions.plugin_tools.plugin_tool_name``,
    repeated because an extension must not import the host;
    tests/test_middleware.py checks the two agree when the host is installed.
    """
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).hexdigest()[:12]
    return f"ext_{re.sub('[^a-z0-9_]', '_', namespace)[:20]}_{name[:25]}_{digest}"


SCAD_DRAFT_TOOL = bound_tool_name(NAMESPACE, TOOL)
CAD_BUILD_TOOL = bound_tool_name(CAD_NAMESPACE, CAD_TOOL)
