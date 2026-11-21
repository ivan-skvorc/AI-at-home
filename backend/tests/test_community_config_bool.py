"""Shared boolean coercion for community provider tool entries.

``deerflow.community.config_bool.coerce_bool`` replaced seven byte-identical
private copies (``_coerce_bool`` / ``_as_bool``). These tests pin the value
table and keep a private copy from coming back under either name.
"""

import ast
from pathlib import Path

import pytest

import deerflow.community.config_bool as owner

COMMUNITY_ROOT = Path(owner.__file__).resolve().parent
FOLDED_PROVIDERS = ("browser_automation", "browserless", "crawl4ai", "exa", "fastcrw", "firecrawl", "jina_ai")


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (True, False, True),
        (False, True, False),
        ("true", False, True),
        ("YES", False, True),
        (" on ", False, True),
        ("1", False, True),
        ("false", True, False),
        ("No", True, False),
        ("off", True, False),
        ("0", True, False),
        ("maybe", True, True),
        ("maybe", False, False),
        (None, True, True),
        (123, False, False),
        (1, False, False),
    ],
)
def test_coerce_bool(value, default, expected):
    """Booleans and known strings convert; anything else falls back to the default."""
    assert owner.coerce_bool(value, default) is expected


@pytest.mark.parametrize("provider", FOLDED_PROVIDERS)
def test_folded_provider_uses_the_shared_function(provider):
    import importlib

    module = importlib.import_module(f"deerflow.community.{provider}.tools")
    assert module.coerce_bool is owner.coerce_bool
    for stale in ("_coerce_bool", "_as_bool"):
        assert not hasattr(module, stale), f"{provider} grew a private {stale} again"


def test_no_community_module_defines_a_private_bool_coercer():
    offenders = []
    for path in sorted(COMMUNITY_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_coerce_bool", "_as_bool"}:
                offenders.append(f"{path.relative_to(COMMUNITY_ROOT)}::{node.name}")
    assert offenders == [], f"use deerflow.community.config_bool.coerce_bool instead: {offenders}"
