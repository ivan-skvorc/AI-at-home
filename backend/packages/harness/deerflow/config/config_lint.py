"""Lint checks for config.yaml content beyond pydantic schema validation.

DeerFlow's config models deliberately use ``extra="allow"`` — model entries
pass provider-specific fields (``base_url``, ``api_key``, ``extra_body``, …)
straight through to the LangChain constructor, and the sandbox section carries
provider-specific keys. The downside is that typos are silently accepted and
only surface as puzzling runtime behavior (a mistyped model field once
surfaced only as a 400 deep inside a provider call; a mistyped sandbox key is
simply ignored). This module turns those silent cases into load-time warnings
without ever failing the load.

Two checks:

* ``sandbox:`` — every key must be a declared ``SandboxConfig`` field (or a
  known provider-specific key); anything else warns, with a did-you-mean hint.
* ``models:`` entries — extras are legitimate passthrough, so only keys that
  look like a *typo of a declared field* warn (difflib close match).
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any

# Sandbox keys read via ``getattr(sandbox_config, ...)`` / ``model_extra`` by
# specific providers. Kept as an explicit allowlist so the lint stays correct
# even if a provider consumes a key that SandboxConfig does not declare.
KNOWN_SANDBOX_EXTRA_KEYS = frozenset({"base_url", "request_timeout", "provisioner_url"})

# Close-match cutoff for flagging a model-entry key as a suspected typo of a
# declared field. High on purpose: extras are usually legitimate passthrough.
_MODEL_TYPO_CUTOFF = 0.8


def lint_unknown_config_keys(config_data: Any) -> list[str]:
    """Return human-readable warnings for suspicious keys in raw config data.

    Args:
        config_data: The parsed config.yaml document (as loaded, before
            pydantic validation).

    Returns:
        Warning strings; empty when nothing looks wrong. Never raises on
        malformed input — schema validation owns that.
    """
    if not isinstance(config_data, dict):
        return []

    warnings: list[str] = []
    warnings.extend(_lint_sandbox_keys(config_data.get("sandbox")))
    warnings.extend(_lint_model_entries(config_data.get("models")))
    return warnings


def _lint_sandbox_keys(sandbox: Any) -> list[str]:
    if not isinstance(sandbox, dict):
        return []

    from deerflow.config.sandbox_config import SandboxConfig

    known = set(SandboxConfig.model_fields) | set(KNOWN_SANDBOX_EXTRA_KEYS)
    warnings = []
    for key in sandbox:
        if not isinstance(key, str) or key in known:
            continue
        close = get_close_matches(key, sorted(known), n=1, cutoff=0.6)
        hint = f" — did you mean '{close[0]}'?" if close else ""
        warnings.append(f"unknown key '{key}' under sandbox: is ignored by DeerFlow{hint}")
    return warnings


def _lint_model_entries(models: Any) -> list[str]:
    if not isinstance(models, list):
        return []

    from deerflow.config.model_config import ModelConfig

    declared = sorted(ModelConfig.model_fields)
    warnings = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "<unnamed>")
        for key in entry:
            if not isinstance(key, str) or key in ModelConfig.model_fields:
                continue
            close = get_close_matches(key, declared, n=1, cutoff=_MODEL_TYPO_CUTOFF)
            if close:
                warnings.append(f"models entry '{name}': key '{key}' is passed through to the provider as-is, but looks like a possible typo of '{close[0]}'")
    return warnings
