"""Unit tests for provider-reported model-id normalization (``deerflow.model_ids``).

The bug these pin is real and silent: LangChain merges an ``AIMessageChunk``
stream by ``merge_dicts``, which *concatenates* equal string values in
``response_metadata``. A provider that repeats ``model`` on more than one chunk
carrying a ``finish_reason`` (OpenRouter does, on the trailing usage frame)
therefore produces ``"deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro"`` as the
model id the whole cost pipeline keys on — which matches no configured model, so
the conversation silently reports no cost at all.
"""

from __future__ import annotations

import pytest

from deerflow.model_ids import normalize_reported_model_name


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        # The reported bug, verbatim: two stream chunks each carrying `model`.
        ("deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
        # Three or more chunks repeat it three or more times.
        ("claude-opus-5claude-opus-5claude-opus-5", "claude-opus-5"),
        # An Ollama tag has the same shape as an OpenRouter variant suffix.
        ("qwen3:32bqwen3:32b", "qwen3:32b"),
        # A dated snapshot id survives the round trip.
        ("gpt-5.6-sol-2026-01-15gpt-5.6-sol-2026-01-15", "gpt-5.6-sol-2026-01-15"),
        # Short ids are real, and duplicate like any other.
        ("o3o3", "o3"),
    ],
)
def test_a_repeated_model_id_collapses_to_one_copy(reported, expected):
    assert normalize_reported_model_name(reported) == expected


@pytest.mark.parametrize(
    "reported",
    [
        "deepseek/deepseek-v4-pro",
        "claude-opus-5-20260115",
        "qwen3:32b",
        # Two *different* ids concatenated are not a repetition; collapsing a
        # guess here would bill one model at another's rate.
        "claude-opus-5claude-haiku-4-5",
        # A partial repeat (an alias followed by the snapshot it resolved to)
        # is likewise left alone rather than guessed at.
        "claude-opus-5claude-opus-5-20260115",
        # A model id that merely *contains* a repeated substring.
        "llama-4-maverick",
    ],
)
def test_an_ordinary_model_id_is_returned_unchanged(reported):
    assert normalize_reported_model_name(reported) is reported


@pytest.mark.parametrize(("reported", "expected"), [(None, None), ("", ""), ("   ", "   ")])
def test_missing_and_empty_ids_pass_through(reported, expected):
    assert normalize_reported_model_name(reported) == expected


def test_a_single_repeated_character_is_not_collapsed():
    """The unit must be a plausible id, not one repeated character.

    ``"aaaa"`` is a repetition of ``"a"`` by the arithmetic, and nothing that
    short is a model id — collapsing it would be the rule inventing data.
    """
    assert normalize_reported_model_name("aaaa") == "aaaa"


def test_non_string_input_is_returned_unchanged():
    """``response_metadata`` is provider-controlled and not always a string."""
    sentinel = object()
    assert normalize_reported_model_name(sentinel) is sentinel  # type: ignore[arg-type]
