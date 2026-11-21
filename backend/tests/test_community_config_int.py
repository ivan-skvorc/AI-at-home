"""Shared integer coercion for community provider tool entries.

``deerflow.community.config_int.coerce_int`` replaced four private copies
(``_as_int`` in browser_automation and browserless, ``_coerce_int`` in
camoufox_fetch, ``_coerce_timeout`` in jina_ai). These tests pin the value table
and keep a private copy from coming back under those names.
"""

import ast
import importlib
from pathlib import Path

import pytest

import deerflow.community.config_int as owner

COMMUNITY_ROOT = Path(owner.__file__).resolve().parent
FOLDED = {
    "browser_automation": "_as_int",
    "browserless": "_as_int",
    "camoufox_fetch": "_coerce_int",
    "jina_ai": "_coerce_timeout",
}


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (30, 10, 30),
        (0, 10, 0),
        (-5, 10, -5),
        ("45", 10, 45),
        (" 45 ", 10, 45),
        ("not-a-number", 10, 10),
        ("4.5", 10, 10),
        (True, 10, 10),
        (False, 10, 10),
        (None, 10, 10),
        (1.5, 10, 10),
    ],
)
def test_coerce_int(value, default, expected):
    """Ints and decimal strings convert; booleans, floats and junk fall back to the default."""
    assert owner.coerce_int(value, default) == expected


@pytest.mark.parametrize(("provider", "stale"), sorted(FOLDED.items()))
def test_folded_provider_uses_the_shared_function(provider, stale):
    module = importlib.import_module(f"deerflow.community.{provider}.tools")
    assert module.coerce_int is owner.coerce_int
    assert not hasattr(module, stale), f"{provider} grew a private {stale} again"


def test_no_folded_provider_defines_a_private_int_coercer():
    offenders = []
    for provider, stale in FOLDED.items():
        path = COMMUNITY_ROOT / provider / "tools.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_as_int", "_coerce_int", stale}:
                offenders.append(f"{provider}::{node.name}")
    assert offenders == [], f"use deerflow.community.config_int.coerce_int instead: {offenders}"
