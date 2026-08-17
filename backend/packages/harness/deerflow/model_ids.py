"""Normalization for model ids as *reported by the provider*.

``response_metadata["model_name"]`` is the identity the whole cost pipeline
keys on — ``token_usage_by_model`` buckets, the spend cap, the spend report,
and the chat header's cost overview all start from it. It is also, for a
streamed response, an *assembled* value rather than a reported one, and that
assembly can corrupt it:

LangChain merges an ``AIMessageChunk`` stream with
``langchain_core.utils._merge.merge_dicts``, which **concatenates** two equal
string values under the same key. ``langchain_openai`` writes ``model_name``
into ``generation_info`` on every chunk that carries a ``finish_reason``, and
some OpenAI-compatible providers (OpenRouter, notably) send more than one such
chunk. Two of them therefore merge into::

    {"finish_reason": "stopstop",
     "model_name": "deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro"}

Nothing raises. The id simply stops matching any configured model, so every
token that model burned is treated as unpriced: the conversation's cost renders
as a bare dash and the "no price is configured for ..." note names a model id
that does not exist. That is the exact failure the unpriced note was added to
explain, so the note has to be given a real name to print.

The fix is deliberately *narrow*: only a whole id repeated end to end collapses,
never a partial or a mismatched pair. An id assembled from two **different**
names is left alone, because guessing which half is real would bill one model at
another's rate — the one outcome worse than showing no cost at all.
"""

from __future__ import annotations

# A one-character unit ("aaaa") is a coincidence of arithmetic rather than a
# duplicated id, so two characters is the shortest unit worth collapsing —
# short ids are real (``o3``, ``k2``) and get duplicated like any other.
_MIN_REPEATED_UNIT = 2


def normalize_reported_model_name(model: str | None) -> str | None:
    """Collapse a provider-reported model id that chunk merging duplicated.

    ``"deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro"`` becomes
    ``"deepseek/deepseek-v4-pro"``; an id that is not an exact whole-string
    repetition is returned **unchanged and identical** (same object), so this is
    safe to apply anywhere a reported id is read.
    """
    if not isinstance(model, str) or len(model) < _MIN_REPEATED_UNIT * 2:
        return model
    # The classic period search: ``s`` repeats iff it reappears in ``s + s`` at
    # an offset that divides its length. ``find`` returns the *smallest* such
    # offset, so a triple collapses to one copy rather than to a pair.
    period = (model + model).find(model, 1)
    if period >= len(model) or period < _MIN_REPEATED_UNIT:
        return model
    return model[:period]
