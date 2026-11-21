"""Browser-only GLB and STL previews; file reads keep the host's artifact authorization."""

from pathlib import Path

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BrowserAssets, PluginContribution


@extension(api="0.2.3", name="cad-preview")
def install(registry, config):
    enabled = config.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    accepted = registry.plugin(
        PluginContribution(
            namespace="cad-preview",
            title="CAD model preview / CAD 模型预览",
            description="Rotate GLB and STL models in the artifact panel.",
            enabled=enabled,
            frontend=BrowserAssets(module="cad-preview", root=Path(__file__).parent),
        )
    )
    if not accepted:
        raise RuntimeError("This host does not support browser plugin contributions")
