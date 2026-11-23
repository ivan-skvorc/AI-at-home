"""Isolating extension middleware failures from the user's run.

Extension middlewares execute inside LangChain's call chain, so an unhandled
exception would abort the user's run. Every contributed middleware is wrapped
so an observation failure degrades to a diagnostic and the call passes through.
The downstream handler is tracked so isolation recovery never adds another
model request or tool side effect: pre-handler extension failures invoke it
once, post-handler failures return its captured result, and handler failures
remain owned by the graph's error policy.

The wrapper must mirror the inner middleware's full interface, not just the
four wrap-call hooks: LangChain discovers capabilities by inspecting the
wrapper — hook participation via class-level identity checks
(`m.__class__.before_model is not AgentMiddleware.before_model`), tools,
state_schema and transformers via instance attributes. Lifecycle mirroring is
exact in both directions. LangChain deliberately treats each sync/async wrap
pair as one capability and wires both execution paths when either side exists,
so the wrapper supplies a silent pass-through counterpart when the inner
implements only one side; otherwise the base class raises
``NotImplementedError`` before isolation can fail open.

Contributions are observational, with one narrow exception. A model-call
wrapper the host places at ``Placement.MODEL_LOGICAL`` (``adjusts_model_requests``)
may adjust the request it hands on: remove bound tools and append to the system
message, so a plugin can scope its own tool and brief to the runs that use them.
Nothing else passes (another model, messages or tool choice, an added tool, a
rewritten system message); the original request goes on instead, with a warning
naming what was refused. The position is outer of retries and of the context
guard, so the guard measures the adjusted request. Every other placement and
every tool call stays observational, and a request handed on there is dropped
the same way, never silently. An adjustment is advice, not a decision, hence
still fail-open: a wrapper that fails before calling the handler sends the
original request. A decision-making contribution (vetoing a call, choosing the
model) would need to fail closed and must opt out of this wrapper explicitly.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import threading
from collections import Counter
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.errors import GraphBubbleUp

from deerflow.extensions.loader import Diagnostic

logger = logging.getLogger(__name__)

_UNSAFE_GRAPH_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def graph_safe_middleware_name(value: str) -> str:
    """Normalize a middleware identity for LangGraph node names."""
    return _UNSAFE_GRAPH_NAME.sub("_", value)


def _system_text(message: Any) -> str:
    """A system message's text, list content joined the way the bundled extensions join it."""
    content = getattr(message, "content", "") if message is not None else ""
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content or ())


def admit_model_request_adjustment(original: Any, proposed: Any) -> tuple[Any, str | None]:
    """The request an adjusting wrapper may hand on, and why a proposal was refused.

    Admitted: ``proposed`` differs from ``original`` only in ``tools``, a sub-multiset
    of the original tool objects, and ``system_message``, whose text extends the
    original's. Anything else is refused and ``original`` is returned.
    """
    if proposed is original:
        return original, None
    if type(proposed) is not type(original) or not dataclasses.is_dataclass(original):
        return original, "it handed on another object instead of the model request"
    changed = {field.name for field in dataclasses.fields(original) if getattr(proposed, field.name) is not getattr(original, field.name)}
    other = sorted(changed - _ADJUSTABLE_FIELDS)
    if other:
        return original, f"it changed {', '.join(other)}"
    if "tools" in changed and Counter(map(id, proposed.tools or ())) - Counter(map(id, original.tools or ())):
        return original, "it added tools; bound tools may only be removed"
    if "system_message" in changed and not _system_text(proposed.system_message).startswith(_system_text(original.system_message)):
        return original, "it rewrote the system message; text may only be appended to it"
    return proposed, None


_WRAP_HOOKS = ("wrap_model_call", "awrap_model_call", "wrap_tool_call", "awrap_tool_call")
_MODEL_HOOKS = frozenset({"wrap_model_call", "awrap_model_call"})
#: The ModelRequest fields an adjusting wrapper may change, and only by narrowing or appending.
_ADJUSTABLE_FIELDS = frozenset({"tools", "system_message"})
_WRAP_HOOK_PAIRS = (
    ("wrap_model_call", "awrap_model_call"),
    ("wrap_tool_call", "awrap_tool_call"),
)
_LIFECYCLE_HOOKS = (
    "before_agent",
    "abefore_agent",
    "before_model",
    "abefore_model",
    "after_model",
    "aafter_model",
    "after_agent",
    "aafter_agent",
)


def _implemented_hooks(inner: AgentMiddleware) -> frozenset[str]:
    """The hooks ``inner`` actually overrides, by LangChain's own class-level
    identity check — instance-level attributes are invisible to the factory,
    so they are invisible here too."""
    return frozenset(hook for hook in (*_WRAP_HOOKS, *_LIFECYCLE_HOOKS) if getattr(type(inner), hook, None) is not getattr(AgentMiddleware, hook, None))


def _make_sync_wrap_delegate(hook: str):
    def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._invoke_sync(hook, getattr(self._inner, hook), request, handler)

    return delegate


def _make_async_wrap_delegate(hook: str):
    async def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await self._invoke_async(hook, getattr(self._inner, hook), request, handler)

    return delegate


def _make_sync_wrap_passthrough():
    def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(request)

    return delegate


def _make_async_wrap_passthrough():
    async def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(request)

    return delegate


def _make_sync_lifecycle_delegate(hook: str):
    def delegate(self: IsolatedMiddleware, state: Any, runtime: Any) -> Any:
        return self._invoke_lifecycle_sync(hook, state, runtime)

    return delegate


def _make_async_lifecycle_delegate(hook: str):
    async def delegate(self: IsolatedMiddleware, state: Any, runtime: Any) -> Any:
        return await self._invoke_lifecycle_async(hook, state, runtime)

    return delegate


# Async variants are named explicitly: startswith("a") would also catch the
# sync after_model/after_agent.
_ASYNC_HOOKS = frozenset(hook for hook in (*_WRAP_HOOKS, *_LIFECYCLE_HOOKS) if hook[1:].startswith(("wrap", "before", "after")))


def _delegate_for(hook: str):
    if hook in _WRAP_HOOKS:
        return _make_async_wrap_delegate(hook) if hook in _ASYNC_HOOKS else _make_sync_wrap_delegate(hook)
    return _make_async_lifecycle_delegate(hook) if hook in _ASYNC_HOOKS else _make_sync_lifecycle_delegate(hook)


_subclass_cache: dict[frozenset[str], type[IsolatedMiddleware]] = {}
_subclass_cache_lock = threading.Lock()


def _wrapper_subclass(hooks: frozenset[str]) -> type[IsolatedMiddleware]:
    """A cached IsolatedMiddleware subclass defining ``hooks`` and required
    wrap-hook pass-through counterparts.

    Per hook set, not per middleware: every inner middleware with the same
    implemented-hook combination shares one subclass.
    """
    with _subclass_cache_lock:
        subclass = _subclass_cache.get(hooks)
        if subclass is None:
            namespace = {hook: _delegate_for(hook) for hook in hooks}
            for sync_hook, async_hook in _WRAP_HOOK_PAIRS:
                if sync_hook in hooks and async_hook not in hooks:
                    namespace[async_hook] = _make_async_wrap_passthrough()
                elif async_hook in hooks and sync_hook not in hooks:
                    namespace[sync_hook] = _make_sync_wrap_passthrough()
            subclass = type(IsolatedMiddleware.__name__, (IsolatedMiddleware,), namespace)
            _subclass_cache[hooks] = subclass
        return subclass


class IsolatedMiddleware(AgentMiddleware):
    """Wrap one extension middleware so its failures cannot break the run.

    Instantiation returns a cached subclass that defines exactly the hooks the
    inner middleware implements, so LangChain's class-level capability checks
    see the same interface on the wrapper as on the inner middleware itself.
    """

    def __new__(cls, inner: AgentMiddleware, source: str, on_error: Callable[[Diagnostic], None], *, name: str | None = None, adjusts_model_requests: bool = False):
        if cls is IsolatedMiddleware:
            cls = _wrapper_subclass(_implemented_hooks(inner))
        return super().__new__(cls)

    def __init__(
        self,
        inner: AgentMiddleware,
        source: str,
        on_error: Callable[[Diagnostic], None],
        *,
        name: str | None = None,
        adjusts_model_requests: bool = False,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._adjusts_model_requests = adjusts_model_requests
        self._refusal_reported = False
        self._source = source
        self._on_error = on_error
        if name is None:
            inner_name = getattr(inner, "name", type(inner).__name__)
            name = f"extension:{source}:{inner_name}"
        self._name = graph_safe_middleware_name(name)
        # Mirror the declared-contribution attributes LangChain reads off the
        # middleware instance (factory.py: m.tools, m.state_schema,
        # m.transformers). state_schema is a class attribute on the base but
        # must be per-instance here: cached subclasses are shared across
        # middlewares whose schemas differ.
        self.tools = getattr(inner, "tools", [])
        self.transformers = getattr(inner, "transformers", ())
        self.state_schema = getattr(inner, "state_schema", AgentMiddleware.state_schema)

    def __copy__(self) -> IsolatedMiddleware:
        """State-preserving shallow copy; never rebuilds from ``inner``.

        ``normalize_middleware_state_schemas`` (delta mode) and the
        authorization declaration view both copy middleware instances. A
        rebuild-based copy would re-run ``__init__`` and re-mirror
        ``inner.tools``, silently restoring declarations Layer 1 narrowed away
        on this build; the default copy protocol would call the argument-
        requiring ``__new__`` above and fail. Bypassing both keeps the
        narrowed ``tools``, transformers, and adapted ``state_schema`` through
        the whole copy chain.
        """
        clone = object.__new__(type(self))
        clone.__dict__.update(self.__dict__)
        return clone

    @property
    def name(self) -> str:
        """Stable graph and trace identity for this isolated contribution."""
        return self._name

    @property
    def adjusts_model_requests(self) -> bool:
        """Whether this wrapper hands on an admitted model-request adjustment (MODEL_LOGICAL)."""
        return self._adjusts_model_requests

    @property
    def inner(self) -> AgentMiddleware:
        """The wrapped middleware. Used by ordering checks and tests."""
        return self._inner

    @property
    def source(self) -> str:
        """Extension this middleware came from. Read by the provenance map."""
        return self._source

    def _report(self, hook: str, exc: Exception) -> None:
        message = f"{type(self._inner).__name__}.{hook} failed and was skipped: {exc}"
        logger.exception("Extension %s: %s", self._source, message)
        try:
            self._on_error(Diagnostic.error(self._source, message))
        except Exception:  # pragma: no cover - reporting must never raise
            logger.exception("Extension %s: diagnostic reporting failed", self._source)

    def _downstream(self, hook: str, original: Any, proposed: Any) -> Any:
        """The request to hand downstream when the inner hook called the handler with ``proposed``."""
        if proposed is original:
            return original
        if self._adjusts_model_requests and hook in _MODEL_HOOKS:
            admitted, refusal = admit_model_request_adjustment(original, proposed)
        else:
            admitted, refusal = original, "it handed on another request where wrappers may only observe"
        if refusal is not None and not self._refusal_reported:
            # Once per wrapper, which is once per agent build: a run makes many model calls.
            self._refusal_reported = True
            message = f"{type(self._inner).__name__}.{hook} handed on a changed request that was not used: {refusal}"
            logger.warning("Extension %s: %s", self._source, message)
            try:
                self._on_error(Diagnostic.warning(self._source, message))
            except Exception:  # pragma: no cover - reporting must never raise
                logger.exception("Extension %s: diagnostic reporting failed", self._source)
        return admitted

    def _invoke_sync(
        self,
        hook: str,
        inner_hook: Callable[[Any, Callable[[Any], Any]], Any],
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        handler_called = False
        handler_succeeded = False
        handler_result: Any = None
        handler_error: BaseException | None = None
        handler_error_traceback: TracebackType | None = None
        duplicate_call_error: RuntimeError | None = None

        def tracked_handler(inner_request: Any) -> Any:
            nonlocal handler_called, duplicate_call_error
            nonlocal handler_error, handler_error_traceback
            nonlocal handler_result, handler_succeeded
            if handler_called:
                duplicate_call_error = RuntimeError(f"{type(self._inner).__name__}.{hook} called the downstream handler more than once")
                raise duplicate_call_error
            handler_called = True
            handler_error = None
            handler_error_traceback = None
            handler_succeeded = False
            try:
                # Observational, except an admitted MODEL_LOGICAL adjustment
                # (see the module docstring): never a substituted request.
                handler_result = handler(self._downstream(hook, request, inner_request))
            except BaseException as exc:
                handler_error = exc
                handler_error_traceback = exc.__traceback__
                raise
            else:
                handler_succeeded = True
                return handler_result

        try:
            inner_hook(request, tracked_handler)
            if handler_error is not None:
                raise handler_error.with_traceback(handler_error_traceback)
            if duplicate_call_error is not None:
                raise duplicate_call_error
            if not handler_called:
                raise RuntimeError(f"{type(self._inner).__name__}.{hook} did not call the downstream handler")
            return handler_result
        except GraphBubbleUp as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            if handler_succeeded:
                self._report(hook, duplicate_call_error or exc)
                return handler_result
            raise
        except Exception as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            self._report(hook, exc)
            if handler_succeeded:
                return handler_result
            return handler(request)

    async def _invoke_async(
        self,
        hook: str,
        inner_hook: Callable[
            [Any, Callable[[Any], Awaitable[Any]]],
            Awaitable[Any],
        ],
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        handler_called = False
        handler_succeeded = False
        handler_result: Any = None
        handler_error: BaseException | None = None
        handler_error_traceback: TracebackType | None = None
        duplicate_call_error: RuntimeError | None = None

        async def tracked_handler(inner_request: Any) -> Any:
            nonlocal handler_called, duplicate_call_error
            nonlocal handler_error, handler_error_traceback
            nonlocal handler_result, handler_succeeded
            if handler_called:
                duplicate_call_error = RuntimeError(f"{type(self._inner).__name__}.{hook} called the downstream handler more than once")
                raise duplicate_call_error
            handler_called = True
            handler_error = None
            handler_error_traceback = None
            handler_succeeded = False
            try:
                handler_result = await handler(self._downstream(hook, request, inner_request))
            except BaseException as exc:
                handler_error = exc
                handler_error_traceback = exc.__traceback__
                raise
            else:
                handler_succeeded = True
                return handler_result

        try:
            await inner_hook(request, tracked_handler)
            if handler_error is not None:
                raise handler_error.with_traceback(handler_error_traceback)
            if duplicate_call_error is not None:
                raise duplicate_call_error
            if not handler_called:
                raise RuntimeError(f"{type(self._inner).__name__}.{hook} did not call the downstream handler")
            return handler_result
        except GraphBubbleUp as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            if handler_succeeded:
                self._report(hook, duplicate_call_error or exc)
                return handler_result
            raise
        except Exception as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            self._report(hook, exc)
            if handler_succeeded:
                return handler_result
            return await handler(request)

    def _invoke_lifecycle_sync(self, hook: str, state: Any, runtime: Any) -> Any:
        """Lifecycle hooks have no handler to fall through to: the fail-open
        degradation for a failed observation is applying no state update."""
        try:
            return getattr(self._inner, hook)(state, runtime)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            self._report(hook, exc)
            return None

    async def _invoke_lifecycle_async(self, hook: str, state: Any, runtime: Any) -> Any:
        try:
            return await getattr(self._inner, hook)(state, runtime)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            self._report(hook, exc)
            return None
