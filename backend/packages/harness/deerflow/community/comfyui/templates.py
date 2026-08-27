"""Workflow templates: typed parameters in, an API-format graph out.

Two rules shape this module.

**The model never authors graph JSON.** It passes typed parameters (prompt,
seed, steps, dimensions, checkpoint) and a template name; everything else is
fixed by a file an operator can read. A model that can emit arbitrary node
graphs can also load arbitrary files and run arbitrary custom nodes on the
machine holding the GPU.

**A template is only valid against the build that will run it.** API-format
graphs address nodes by numeric id, so a custom-node update or a renamed input
silently invalidates a template, and ComfyUI's native complaint is a validation
dump rather than a sentence. :func:`validate_template` compares the graph
against ``/object_info`` and names the node that moved.

Each template file wraps the submittable graph so the binding metadata never
reaches ComfyUI:

.. code-block:: json

    {"name": "txt2img", "kind": "image",
     "bindings": {"prompt": {"node": "6", "input": "text"}},
     "outputs": {"image": "9"},
     "prompt": {"6": {"class_type": "CLIPTextEncode", "inputs": {...}}}}

``prompt`` alone is submitted, and ``prompt`` alone is what gets saved beside
the output as ``<name>.workflow.json`` — so the saved file opens in ComfyUI and
reproduces the image by hand.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .client import declared_inputs, enum_values

TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateError(ValueError):
    """A template is missing, malformed, or no longer matches the ComfyUI build."""


@dataclass(frozen=True)
class Binding:
    """Where one typed parameter lands in the graph."""

    node: str
    input: str


@dataclass(frozen=True)
class WorkflowTemplate:
    """A named, parameterized API-format graph."""

    name: str
    kind: str
    bindings: dict[str, Binding]
    outputs: dict[str, str]
    graph: dict[str, Any]
    description: str = ""

    def node_class(self, node_id: str) -> str | None:
        node = self.graph.get(node_id)
        return str(node.get("class_type")) if isinstance(node, dict) and node.get("class_type") else None


def _parse_template(name: str, data: Any) -> WorkflowTemplate:
    if not isinstance(data, dict):
        raise TemplateError(f"Workflow template '{name}' is not a JSON object")
    graph = data.get("prompt")
    if not isinstance(graph, dict) or not graph:
        raise TemplateError(f"Workflow template '{name}' has no 'prompt' graph; export it from ComfyUI with 'Export (API)'")
    raw_bindings = data.get("bindings") or {}
    if not isinstance(raw_bindings, dict):
        raise TemplateError(f"Workflow template '{name}' has a malformed 'bindings' block")
    bindings: dict[str, Binding] = {}
    for param, spec in raw_bindings.items():
        if not isinstance(spec, dict) or not spec.get("node") or not spec.get("input"):
            raise TemplateError(f"Workflow template '{name}' binding '{param}' must name both 'node' and 'input'")
        bindings[str(param)] = Binding(node=str(spec["node"]), input=str(spec["input"]))
    outputs = {str(key): str(value) for key, value in (data.get("outputs") or {}).items()}
    return WorkflowTemplate(
        name=str(data.get("name") or name),
        kind=str(data.get("kind") or "image"),
        bindings=bindings,
        outputs=outputs,
        graph=graph,
        description=str(data.get("description") or ""),
    )


def available_templates(templates_dir: Path | None = None) -> list[str]:
    directory = templates_dir or TEMPLATES_DIR
    return sorted(path.stem for path in directory.glob("*.json"))


def load_template(name: str, templates_dir: Path | None = None) -> WorkflowTemplate:
    """Load a template by name. Path traversal is refused, not sanitized."""
    directory = templates_dir or TEMPLATES_DIR
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise TemplateError(f"Invalid workflow template name: {name!r}")
    path = directory / f"{name}.json"
    if not path.is_file():
        raise TemplateError(f"Unknown workflow template '{name}'. Available: {', '.join(available_templates(directory)) or 'none'}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateError(f"Workflow template '{name}' could not be read: {exc}") from exc
    return _parse_template(name, data)


@lru_cache(maxsize=8)
def load_template_cached(name: str) -> WorkflowTemplate:
    return load_template(name)


def patch_graph(template: WorkflowTemplate, params: dict[str, Any]) -> dict[str, Any]:
    """Apply typed parameters to a copy of the template's graph.

    Unset parameters (``None``) are left at the template's own value, so a
    template stays runnable on its own. A parameter the template does not bind
    is an error rather than a silent no-op — that failure mode ("I set the seed
    and nothing changed") is exactly what makes an iteration loop unreadable.
    """
    graph = copy.deepcopy(template.graph)
    for param, value in params.items():
        if value is None:
            continue
        binding = template.bindings.get(param)
        if binding is None:
            raise TemplateError(f"Workflow template '{template.name}' does not expose a '{param}' parameter (it binds: {', '.join(sorted(template.bindings)) or 'nothing'})")
        node = graph.get(binding.node)
        if not isinstance(node, dict):
            raise TemplateError(f"Workflow template '{template.name}' binds '{param}' to node {binding.node}, which the graph does not contain")
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            raise TemplateError(f"Workflow template '{template.name}' node {binding.node} has malformed inputs")
        inputs[binding.input] = value
    return graph


def validate_template(template: WorkflowTemplate, object_info: dict[str, Any]) -> list[str]:
    """Check a template against the running ComfyUI build.

    Returns human-readable problems, each naming the offending node. An empty
    list means the template is submittable.
    """
    problems: list[str] = []
    for node_id, node in sorted(template.graph.items()):
        if not isinstance(node, dict):
            problems.append(f"node {node_id}: malformed entry in template '{template.name}'")
            continue
        class_type = node.get("class_type")
        if not class_type:
            problems.append(f"node {node_id}: no class_type")
            continue
        if class_type not in object_info:
            problems.append(f"node {node_id} ({class_type}): this ComfyUI build does not have that node — install the custom node it comes from, or update the template")
            continue
        known = declared_inputs(object_info, str(class_type))
        for input_name in node.get("inputs") or {}:
            if input_name not in known:
                problems.append(f"node {node_id} ({class_type}): input '{input_name}' no longer exists on that node — it was renamed or removed")

    for param, binding in sorted(template.bindings.items()):
        node = template.graph.get(binding.node)
        if not isinstance(node, dict):
            problems.append(f"binding '{param}' points at node {binding.node}, which the template graph does not contain")
            continue
        class_type = str(node.get("class_type") or "")
        if class_type and class_type in object_info and binding.input not in declared_inputs(object_info, class_type):
            problems.append(f"binding '{param}' targets node {binding.node} ({class_type}) input '{binding.input}', which that node no longer declares")

    for label, node_id in sorted(template.outputs.items()):
        if node_id not in template.graph:
            problems.append(f"output '{label}' points at node {node_id}, which the template graph does not contain")
    return problems


def validate_value_against_enum(template: WorkflowTemplate, object_info: dict[str, Any], param: str, value: str) -> str | None:
    """Return an error when a value is outside the node's enum, else None."""
    binding = template.bindings.get(param)
    if binding is None:
        return None
    class_type = template.node_class(binding.node)
    if not class_type:
        return None
    allowed = enum_values(object_info, class_type, binding.input)
    if allowed and value not in allowed:
        preview = ", ".join(allowed[:10])
        return f"'{value}' is not installed for {param} (node {binding.node}, {class_type}). Installed: {preview}{' …' if len(allowed) > 10 else ''}"
    return None
