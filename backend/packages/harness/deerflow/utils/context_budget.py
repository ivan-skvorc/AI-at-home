"""Context-window-aware size budgets (fork feature).

Every size limit that protects the model context — the sandbox tools'
truncation caps, the tool-output budget thresholds, the chunk size used to
analyse a long document — shipped as a fixed character constant calibrated for
a 200K-token cloud model. Those constants are wrong in one direction only: on a
32K local model a single 50,000-character ``read_file`` result is ~40% of the
whole window, and on an 8K model it is larger than the window itself. The
result is a run that overflows (or, on Ollama, is silently truncated from the
*head*, dropping the system prompt) rather than one that reads less at a time.

This module resolves the window of the model that is actually serving the run
and turns it into character budgets. Two rules keep it safe:

* A configured value is a **ceiling, never a floor**. The budget can only lower
  it. A frontier model with a 200K window keeps every default it has today.
* An **unknown** window resolves to ``None``, and every helper here is then a
  no-op. A provider that does not declare its window behaves exactly as before.

``num_ctx`` (Ollama) and ``context_window`` (a config entry) both describe
prompt **and** generation, so the output reservation (``num_predict`` /
``max_tokens``) is subtracted: a model pinned at ``num_ctx: 32768`` with
``num_predict: 8192`` has 24576 tokens of prompt space, not 32768.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

# Characters per token. Deliberately conservative for English prose (~4) — the
# budgets it feeds are guards, so over-estimating the token cost of a string is
# the safe direction to be wrong in.
CHARS_PER_TOKEN = 4

# Floor for any derived character budget. A window so small that its share
# computes to a few hundred characters would make a tool useless; better to
# return a small-but-workable read and let the provider reject it loudly.
MIN_TOOL_CHARS = 2_000
MIN_CHUNK_CHARS = 4_000

# Chunk size used when the window is unknown. ~6K tokens: small enough that a
# mid-sized model handles it comfortably, large enough to hold a section.
DEFAULT_CHUNK_CHARS = 24_000

# Share of the usable prompt window a single value may consume. A tool result
# has to leave room for the conversation, the system prompt and the answer, so
# these are fractions rather than the whole window.
READ_FILE_SHARE = 0.25
COMMAND_OUTPUT_SHARE = 0.15
TOOL_RESULT_SHARE = 0.20
EXTERNALIZE_SHARE = 0.10
# The chunk *is* the payload of a map step, so it may claim a larger share —
# but never so much that the instructions and the answer have nowhere to go.
CHUNK_SHARE = 0.45

# Attributes a chat-model client may expose, most authoritative first.
_WINDOW_ATTRS = ("num_ctx", "context_window")
_RESERVE_ATTRS = ("num_predict", "max_tokens")
# Attributes that may hold the model's identifier, for config lookup.
_IDENTIFIER_ATTRS = ("name", "model_name", "model", "deployment_name")


@dataclass(frozen=True)
class ContextBudget:
    """The usable context of the model serving the current run, in tokens."""

    context_window: int
    reserved_output: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Tokens available for the prompt, after the output reservation.

        A reservation that swallows the whole window is nonsense config rather
        than a reason to return zero, so it degrades to half the window.
        """
        reserve = max(0, self.reserved_output)
        if reserve >= self.context_window:
            return max(1, self.context_window // 2)
        return self.context_window - reserve

    def chars(self, share: float, *, minimum: int = MIN_TOOL_CHARS) -> int:
        """Return ``share`` of the usable prompt window, in characters."""
        computed = int(self.prompt_tokens * CHARS_PER_TOKEN * share)
        return max(minimum, computed)


def clamp_to_context(
    configured: int,
    budget: ContextBudget | None,
    *,
    share: float,
    minimum: int = MIN_TOOL_CHARS,
) -> int:
    """Lower a configured character limit to fit ``budget``.

    ``configured`` is a ceiling: the result is never larger than it, so a model
    with a big window keeps the shipped default. ``configured <= 0`` is the
    explicit "no limit" switch in both the sandbox and tool-output configs and
    is left alone — a budget may lower a limit, never impose one the operator
    turned off.
    """
    if budget is None or configured <= 0:
        return configured
    return min(configured, budget.chars(share, minimum=minimum))


def chunk_chars_for(
    budget: ContextBudget | None,
    *,
    default: int = DEFAULT_CHUNK_CHARS,
    maximum: int | None = None,
) -> int:
    """Return the chunk size to feed one map step, in characters.

    This is the knob that makes one code path serve both ends: a frontier model
    reads a whole chapter per step, a local 8B reads a few pages, and neither
    is configured by hand.
    """
    if budget is None:
        chunk = default
    else:
        chunk = budget.chars(CHUNK_SHARE, minimum=MIN_CHUNK_CHARS)
    if maximum is not None and maximum > 0:
        chunk = min(chunk, maximum)
    return max(MIN_CHUNK_CHARS, chunk)


def _positive_int(value: Any) -> int | None:
    """Coerce to a positive int, or ``None`` for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _first_positive(source: Any, attrs: tuple[str, ...]) -> int | None:
    for attr in attrs:
        found = _positive_int(getattr(source, attr, None))
        if found is not None:
            return found
    return None


def _identifiers(model: Any) -> list[str]:
    values: list[str] = []
    for attr in _IDENTIFIER_ATTRS:
        value = getattr(model, attr, None)
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    return values


def _config_entry(model: Any, app_config: Any) -> Any | None:
    """Find the config entry for *model*.

    Cloud clients never carry ``context_window``: the model factory strips it
    from provider kwargs precisely so it cannot reach the completion payload,
    which means the config entry is the only place it exists.
    """
    if app_config is None:
        return None
    try:
        entries = list(app_config.models or [])
    except Exception:  # pragma: no cover - defensive; a broken config is not fatal here
        return None
    identifiers = _identifiers(model)
    if not identifiers:
        return None
    for entry in entries:
        for attr in ("name", "model"):
            value = getattr(entry, attr, None)
            if isinstance(value, str) and value in identifiers:
                return entry
    return None


def _profile_input_tokens(model: Any) -> int | None:
    """Read ``max_input_tokens`` from a LangChain model profile, if present.

    A profile's value is an *input* limit, so it is already prompt space and no
    output reservation is subtracted from it.
    """
    profile = getattr(model, "profile", None)
    if isinstance(profile, dict):
        return _positive_int(profile.get("max_input_tokens"))
    return None


def resolve_context_budget(model: Any, app_config: Any | None = None) -> ContextBudget | None:
    """Resolve the usable context of *model*, or ``None`` when it is unknown.

    Never raises: a budget that cannot be resolved must degrade to today's
    behaviour, not fail the run it was meant to protect.
    """
    try:
        window = _first_positive(model, _WINDOW_ATTRS)
        reserve = _first_positive(model, _RESERVE_ATTRS)

        if window is None:
            entry = _config_entry(model, app_config)
            if entry is not None:
                window = _first_positive(entry, _WINDOW_ATTRS)
                if reserve is None:
                    reserve = _first_positive(entry, _RESERVE_ATTRS)

        if window is None:
            profile_tokens = _profile_input_tokens(model)
            if profile_tokens is not None:
                return ContextBudget(context_window=profile_tokens, reserved_output=0)
            return None

        return ContextBudget(context_window=window, reserved_output=reserve or 0)
    except Exception:  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# Active budget (published for code that has no model reference)
# ---------------------------------------------------------------------------
#
# The sandbox tools compute their own truncation caps and have no way to reach
# the model serving the run. The middleware that *does* hold the model publishes
# the resolved budget here for the duration of a tool call, so the tools read it
# without a signature change and fall back to their configured values when
# nothing published one (a direct unit test, an extension calling a tool
# outside the agent loop).

_ACTIVE_BUDGET: ContextVar[ContextBudget | None] = ContextVar("deerflow_active_context_budget", default=None)


def active_context_budget() -> ContextBudget | None:
    """Return the budget published for the current call, if any."""
    return _ACTIVE_BUDGET.get()


@contextlib.contextmanager
def use_context_budget(budget: ContextBudget | None) -> Iterator[None]:
    """Publish *budget* for the duration of the block."""
    token = _ACTIVE_BUDGET.set(budget)
    try:
        yield
    finally:
        _ACTIVE_BUDGET.reset(token)
