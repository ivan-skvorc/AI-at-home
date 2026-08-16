"""Model fallback chains (fork feature).

FORK.md §3 notes that models flagged ``supports_tools: false`` stay selectable
and "tool-using subagents will simply fail at runtime". That is one instance of
a general problem: running local models means absorbing local-model failure
modes — daemon down, OOM, context overflow, no tool support — and until now the
user absorbed them by hand, one failed turn at a time. This is the reliability
cost of the fork's central bet (mix free local models with paid cloud ones), and
paying it is what makes a cost-aware routing policy safe to turn on.

The distinction this module exists to draw is between a **failure** and a
**decision**. A provider that is down, overloaded, or handed too many tokens has
failed, and trying the next model is strictly better than failing the turn. A
user interrupt, a spend cap, and a guardrail refusal are things the system
*meant* to do: retrying those on another model would defeat them and spend money
doing it. The default for anything unrecognized is therefore **not** to fall
back — an unknown bug should cost one request, not two.

The chain is **flat by construction**: a fallback model is built without its own
chain, so `a -> b -> a` is not a cycle that has to be detected, it is a shape
that cannot be expressed. That plus ``MAX_CHAIN`` is the whole bound.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Any, ClassVar

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

logger = logging.getLogger(__name__)


# Substrings that identify a *recoverable* provider rejection. Matched against
# the lowercased exception text, because provider SDKs carry these as prose in
# wildly different exception classes and there is no portable error code.
_CONTEXT_LENGTH_PATTERNS = (
    "context length",
    "context_length_exceeded",
    "context window",
    "maximum context",
    "too many tokens",
    "input is too long",
    "prompt is too long",
    "reduce the length",
)

_UNSUPPORTED_TOOLS_PATTERNS = (
    "does not support tools",
    "not support tool",
    "tool calling is not supported",
    "tools is not supported",
    "tools are not supported",
    "function calling is not supported",
)

_CONNECTION_PATTERNS = (
    "connection refused",
    "connection error",
    "connection reset",
    "connect error",
    "failed to establish a new connection",
    "name or service not known",
    "temporary failure in name resolution",
    "no route to host",
    "read timeout",
    "timed out",
    "server disconnected",
    "remote end closed connection",
)

# Exception class-name fragments that mark an *intentional* stop. These never
# fall back: a cap that retries on another model is not a cap.
_INTENTIONAL_STOP_CLASS_PATTERNS = (
    "budget",
    "guardrail",
    "authorization",
    "unauthorized",
    "interrupt",
    "cancel",
    "refus",
    "moderation",
    "contentfilter",
    "content_filter",
)

_STATUS_ATTRS = ("status_code", "http_status", "status", "code")

# A bound on how many models one call may try. The flat-chain construction
# already prevents cycles; this stops a long config from turning one failed turn
# into a slow tour of every provider the user owns.
MAX_CHAIN = 3


def _status_code(error: BaseException) -> int | None:
    for attr in _STATUS_ATTRS:
        value = getattr(error, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    # httpx/openai often nest the response object.
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _looks_like(text: str, patterns: Sequence[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def should_fall_back(error: BaseException) -> bool:
    """Is *error* a provider failure worth retrying on the next model?

    Deliberately conservative: unrecognized errors return ``False``. Falling
    back by default would double the cost of every bug and bury the original
    error behind a second, unrelated one.
    """
    # ── Decisions, not failures ─────────────────────────────────────────────
    if isinstance(error, asyncio.CancelledError | KeyboardInterrupt | GeneratorExit):
        return False
    class_name = type(error).__name__.lower()
    if _looks_like(class_name, _INTENTIONAL_STOP_CLASS_PATTERNS):
        return False
    # LangGraph's interrupt control-flow signal.
    if class_name in {"graphinterrupt", "nodeinterrupt"}:
        return False

    text = str(error).lower()
    status = _status_code(error)

    # An auth failure is a configuration error the operator must see. Silently
    # degrading to another model hides a wrong key until the bill arrives.
    if status in {401, 403}:
        return False

    # ── Failures ────────────────────────────────────────────────────────────
    if status is not None and status >= 500:
        return True
    if isinstance(error, ConnectionError | TimeoutError | OSError):
        return True
    if _looks_like(text, _CONNECTION_PATTERNS):
        return True
    if _looks_like(text, _CONTEXT_LENGTH_PATTERNS):
        return True
    if _looks_like(text, _UNSUPPORTED_TOOLS_PATTERNS):
        return True
    if re.search(r"\b5\d\d\b", text) and "error" in text:
        return True
    return False


def resolve_fallback_chain(
    name: str,
    model_configs: dict[str, Any],
    global_chain: Sequence[str] | None = None,
    known: set[str] | None = None,
) -> list[str]:
    """Resolve the ordered fallback model names for *name*.

    Per-model ``fallback:`` wins over the global chain. The model itself is
    always removed (a global chain would otherwise retry the model that just
    failed), duplicates collapse, unknown names are dropped rather than raising,
    and the result is capped at :attr:`FallbackChatModel.MAX_CHAIN`.
    """
    config = model_configs.get(name)
    declared = getattr(config, "fallback", None) if config is not None else None
    chain = list(declared) if declared else list(global_chain or [])

    resolved: list[str] = []
    for candidate in chain:
        if not isinstance(candidate, str) or candidate == name or candidate in resolved:
            continue
        if known is not None and candidate not in known:
            logger.warning("model fallback: %r lists unknown model %r; dropping it from the chain", name, candidate)
            continue
        resolved.append(candidate)
    return resolved[:MAX_CHAIN]


class FallbackChatModel(BaseChatModel):
    """Delegate to the first model in the chain that answers.

    Token attribution is a non-goal here precisely because it is automatic: the
    wrapper returns the serving model's ``ChatResult`` untouched, so the
    ``response_metadata.model_name`` that ``RunJournal`` keys
    ``token_usage_by_model`` on already names whichever model actually ran. That
    is load-bearing for the spend cap and the spend report — rewriting it to the
    primary's name would bill a cloud fallback at a local model's rate of zero.
    """

    # Module-level MAX_CHAIN, not a class attribute: an annotated attribute on a
    # pydantic model becomes a *field*, not a constant.
    MAX_CHAIN: ClassVar[int] = MAX_CHAIN

    primary: Any
    fallbacks: list[Any] = []
    model_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return f"deerflow-fallback[{'>'.join(self.model_names)}]"

    def _members(self) -> list[tuple[str, Any]]:
        names = self.model_names or []
        members = [(names[0] if names else "primary", self.primary)]
        for index, model in enumerate(self.fallbacks, start=1):
            members.append((names[index] if index < len(names) else f"fallback-{index}", model))
        return members

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        last_error: BaseException | None = None
        members = self._members()
        for index, (name, model) in enumerate(members):
            try:
                result = model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised below unless recoverable
                last_error = exc
                if not should_fall_back(exc) or index == len(members) - 1:
                    raise
                logger.warning("model %r failed (%s: %s); falling back to %r", name, type(exc).__name__, exc, members[index + 1][0])
                continue
            if index:
                logger.warning("model %r served this call after %r failed", name, members[0][0])
            return result
        raise last_error  # pragma: no cover - the loop always raises or returns

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        last_error: BaseException | None = None
        members = self._members()
        for index, (name, model) in enumerate(members):
            try:
                result = await model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised below unless recoverable
                last_error = exc
                if not should_fall_back(exc) or index == len(members) - 1:
                    raise
                logger.warning("model %r failed (%s: %s); falling back to %r", name, type(exc).__name__, exc, members[index + 1][0])
                continue
            if index:
                logger.warning("model %r served this call after %r failed", name, members[0][0])
            return result
        raise last_error  # pragma: no cover

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> FallbackChatModel:
        """Bind tools across the whole chain, tolerating a member that cannot.

        A local model with no tool support is precisely why the chain exists, so
        a member that raises on ``bind_tools`` is kept unbound rather than
        failing the build — it will be skipped at call time by the
        unsupported-tools classification.
        """

        def _bind(model: Any) -> Any:
            try:
                return model.bind_tools(tools, **kwargs)
            except (NotImplementedError, AttributeError, TypeError) as exc:
                logger.warning("model in fallback chain cannot bind tools (%s); leaving it unbound", exc)
                return model

        return FallbackChatModel(
            primary=_bind(self.primary),
            fallbacks=[_bind(model) for model in self.fallbacks],
            model_names=list(self.model_names),
        )
