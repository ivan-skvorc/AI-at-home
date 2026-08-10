"""Middleware enforcing currency-denominated spend caps during a run.

Sibling of :class:`~deerflow.agents.middlewares.token_budget_middleware.TokenBudgetMiddleware`,
and deliberately the same shape: a soft in-context warning at
``warn_threshold``, then a hard stop at ``hard_stop_threshold`` that strips tool
calls so the agent produces a final answer from what it already has. It never
raises — a budget stop is an orderly wrap-up, not a crash.

What differs is the unit and the horizon. The token budget counts one run's
tokens; this counts **money across a window** (day / week / month), which means
two extra ingredients:

* **A baseline.** The Gateway resolves how much the window has already cost at
  run admission (``app/gateway/spend_budget.py``) and hands it to the agent
  through server-owned runtime context. This middleware adds the live run's own
  spend on top. Without that baseline — the embedded client, the TUI, a
  standalone LangGraph server — the cap degrades to "this run alone must stay
  under the limit", which is still a real ceiling and never a silent no-op.

* **Per-model pricing.** Run spend is read from the ``RunJournal``'s live
  per-model accumulator when one is reachable, so a premium lead with cheap or
  local subagents is billed correctly. That attribution is the point of a money
  cap in this fork: 200k tokens is five dollars or nothing depending on which
  model burned them. When no journal is reachable the middleware falls back to
  summing ``AIMessage.usage_metadata`` priced at each message's own reported
  model — accurate for the lead's own calls, and an over-estimate for subagent
  tokens that ``TokenUsageMiddleware`` folded into the dispatching message
  (they get the lead's rate). Over-estimating is the safe direction for a cap.

**Unpriced models contribute zero.** A fully local run costs nothing and must
never be blocked by a spend cap — that is a hard requirement of the fork's
"free local models" premise, not an accident of the pricing map being sparse.

Stop-reason surfacing mirrors the token budget: the hard stop records
``spend_capped`` for :meth:`consume_stop_reason` and on ``runtime.context`` so
the subagent executor and the run worker can tell a capped completion from a
clean one.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.config.spend_budget_config import SpendBudgetConfig
from deerflow.pricing import ModelPricing, lookup_pricing, token_cost

logger = logging.getLogger(__name__)

# Server-owned runtime-context key carrying the pre-run window spend. The
# ``__`` prefix is what makes it unforgeable: ``build_run_config`` strips every
# caller-supplied ``__``-key, so a client cannot seed a fake low baseline and
# widen its own cap.
SPEND_BUDGET_BASELINE_KEY = "__spend_budget"

STOP_REASON = "spend_capped"

_WARNING_MSG = "[SPEND BUDGET WARNING] This {period} budget is {percent:.0f}% spent ({spent:.4g} of {limit:g}{unit}). Wrap up your current work and produce a final answer. Avoid starting new tool calls unless absolutely necessary."
_EXCEEDED_MSG = "[SPEND BUDGET EXCEEDED] The {period} spend limit ({limit:g}{unit}) has been reached ({spent:.4g}{unit}). Producing a final answer with the results collected so far."


def _find_usage_journal(runtime: Runtime) -> Any | None:
    """The run's ``RunJournal``, if this graph run has one attached.

    Located by duck-typing ``current_token_usage_by_model`` over the callback
    handlers, the same way ``task_tool`` finds the usage recorder — the harness
    must not import the Gateway, and a middleware has no other handle on the
    run's accountant. Callbacks may be a list, a ``BaseCallbackManager``, or
    absent; anything else is treated as "no journal".
    """
    from langchain_core.callbacks import BaseCallbackManager

    configs: list[Any] = []
    runtime_config = getattr(runtime, "config", None)
    if isinstance(runtime_config, dict):
        configs.append(runtime_config)
    else:
        try:
            from langgraph.config import get_config

            configs.append(get_config())
        except Exception:  # noqa: BLE001 - outside a graph run there is simply no config
            return None

    for config in configs:
        if not isinstance(config, dict):
            continue
        callbacks = config.get("callbacks")
        if isinstance(callbacks, BaseCallbackManager):
            callbacks = getattr(callbacks, "handlers", None)
        if not isinstance(callbacks, list):
            continue
        for handler in callbacks:
            if hasattr(handler, "current_token_usage_by_model"):
                return handler
    return None


def price_usage_by_model(usage_by_model: dict[str, Any], pricing: dict[str, ModelPricing]) -> float:
    """Spend for a ``token_usage_by_model``-shaped map. Unpriced models cost 0."""
    total = 0.0
    for model, usage in (usage_by_model or {}).items():
        if not isinstance(usage, dict):
            continue
        price = lookup_pricing(pricing, model)
        if price is None:
            continue
        total += token_cost(
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
            price,
            int(usage.get("cache_read_tokens") or 0),
        )
    return total


def _message_model_name(message: AIMessage) -> str | None:
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, dict):
        for key in ("model_name", "model"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


class _Baseline:
    """Pre-run window spend, parsed from server-owned runtime context."""

    __slots__ = ("limits", "currency")

    def __init__(self, limits: list[tuple[str, float, float]], currency: str | None) -> None:
        self.limits = limits
        self.currency = currency


def _parse_baseline(runtime: Runtime, config: SpendBudgetConfig) -> _Baseline:
    """Read the Gateway's baseline, falling back to "this run only".

    A malformed or absent baseline degrades to zero prior spend against the
    configured limits rather than disabling the cap, so a non-Gateway caller
    still gets a real ceiling.
    """
    context = getattr(runtime, "context", None)
    raw = context.get(SPEND_BUDGET_BASELINE_KEY) if isinstance(context, dict) else None
    if isinstance(raw, dict):
        limits: list[tuple[str, float, float]] = []
        for entry in raw.get("limits") or []:
            if not isinstance(entry, dict):
                continue
            try:
                period = str(entry["period"])
                limit = float(entry["limit"])
                spent = float(entry.get("spent") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            if limit > 0:
                limits.append((period, limit, max(spent, 0.0)))
        if limits:
            currency = raw.get("currency")
            return _Baseline(limits, currency if isinstance(currency, str) else None)
    return _Baseline([(limit.period, limit.amount, 0.0) for limit in config.limits()], None)


class SpendBudgetMiddleware(AgentMiddleware[AgentState]):
    """Warn, then force a final answer, when a currency spend cap is reached."""

    def __init__(self, config: SpendBudgetConfig, pricing: dict[str, ModelPricing]) -> None:
        super().__init__()
        self._config = config
        self._pricing = pricing
        self._lock = threading.Lock()
        self._warned: BoundedDict[str, bool] = BoundedDict(1000)
        self._pending_warnings: BoundedDict[str, list[str]] = BoundedDict(1000)
        # Not cleared by ``after_agent`` so the subagent executor can consume it
        # after the run returns; bounded so abandoned runs cannot leak.
        self._stop_reason: BoundedDict[str, str] = BoundedDict(1000)

    @classmethod
    def from_config(cls, config: SpendBudgetConfig, pricing: dict[str, ModelPricing]) -> SpendBudgetMiddleware:
        return cls(config=config, pricing=pricing)

    def reset(self) -> None:
        with self._lock:
            self._warned.clear()
            self._pending_warnings.clear()
            self._stop_reason.clear()

    def consume_stop_reason(self, run_id: str | None) -> str | None:
        """Pop the stop reason recorded when the hard stop fired for this run."""
        with self._lock:
            return self._stop_reason.pop(run_id, None)

    @staticmethod
    def _get_run_id(runtime: Runtime) -> str:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict) and "run_id" in ctx:
            return ctx["run_id"]
        return str(id(runtime))

    # -- spend accounting --------------------------------------------------

    def _run_spend(self, state: AgentState, runtime: Runtime) -> float:
        journal = _find_usage_journal(runtime)
        if journal is not None:
            try:
                return price_usage_by_model(journal.current_token_usage_by_model(), self._pricing)
            except Exception:  # noqa: BLE001 - a broken accountant must not break the run
                logger.debug("spend budget: failed to read live per-model usage from the run journal", exc_info=True)
        return self._spend_from_messages(state)

    def _spend_from_messages(self, state: AgentState) -> float:
        """Fallback accounting: price each AIMessage at its own reported model."""
        total = 0.0
        for message in state.get("messages", []) or []:
            if not isinstance(message, AIMessage):
                continue
            usage = getattr(message, "usage_metadata", None)
            if not isinstance(usage, dict):
                continue
            price = lookup_pricing(self._pricing, _message_model_name(message))
            if price is None:
                continue
            details = usage.get("input_token_details")
            cache_read = int(details.get("cache_read") or 0) if isinstance(details, dict) else 0
            total += token_cost(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), price, cache_read)
        return total

    # -- enforcement -------------------------------------------------------

    @staticmethod
    def _append_text(content: Any, stop_msg: str) -> Any:
        if content is None:
            return stop_msg
        if isinstance(content, str):
            return f"{content}\n\n{stop_msg}" if content else f"\n\n{stop_msg}"
        if isinstance(content, list):
            return [*content, {"type": "text", "text": f"\n\n{stop_msg}"}]
        return f"{content}\n\n{stop_msg}"

    def _build_hard_stop_update(self, msg: AIMessage, stop_msg: str) -> dict[str, Any]:
        kwargs = dict(msg.additional_kwargs) if msg.additional_kwargs else {}
        kwargs.pop("tool_calls", None)
        kwargs.pop("function_call", None)
        response_metadata = dict(getattr(msg, "response_metadata", {}) or {})
        if response_metadata.get("finish_reason") == "tool_calls":
            response_metadata["finish_reason"] = "stop"
        stopped = msg.model_copy(
            update={
                "content": self._append_text(msg.content, stop_msg),
                "tool_calls": [],
                "additional_kwargs": kwargs,
                "response_metadata": response_metadata,
            }
        )
        return {"messages": [stopped]}

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        if not self._config.enabled or not self._pricing:
            return None
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        baseline = _parse_baseline(runtime, self._config)
        if not baseline.limits:
            return None

        spend = self._run_spend(state, runtime)
        run_id = self._get_run_id(runtime)
        unit = f" {baseline.currency}" if baseline.currency else ""

        highest = 0.0
        trigger: tuple[str, float, float] | None = None
        for period, limit, prior in baseline.limits:
            total = prior + spend
            fraction = total / limit if limit > 0 else 0.0
            if fraction > highest:
                highest = fraction
                trigger = (period, limit, total)
        if trigger is None:
            return None
        period, limit, total = trigger

        with self._lock:
            if highest >= self._config.hard_stop_threshold:
                logger.warning("Spend budget hard stop for run %s: %s limit %.4g reached (%.4g spent)", run_id, period, limit, total)
                self._stop_reason[run_id] = STOP_REASON
                ctx = getattr(runtime, "context", None)
                if isinstance(ctx, dict):
                    ctx["stop_reason"] = STOP_REASON
                return self._build_hard_stop_update(messages[-1], _EXCEEDED_MSG.format(period=period, limit=limit, spent=total, unit=unit))
            if highest >= self._config.warn_threshold and not self._warned.get(run_id, False):
                self._warned[run_id] = True
                logger.info("Spend budget warning for run %s: %s limit at %.1f%%", run_id, period, highest * 100)
                self._pending_warnings.setdefault(run_id, []).append(_WARNING_MSG.format(period=period, percent=highest * 100, spent=total, limit=limit, unit=unit))
        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> None:
        if not self._config.enabled:
            return
        run_id = self._get_run_id(runtime)
        with self._lock:
            self._warned.pop(run_id, None)
            self._pending_warnings.pop(run_id, None)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> None:
        self.after_agent(state, runtime)

    def _drain_pending_warnings(self, runtime: Runtime) -> list[str]:
        if not self._config.enabled:
            return []
        with self._lock:
            return self._pending_warnings.pop(self._get_run_id(runtime), None) or []

    @staticmethod
    def _inject_warnings(request: ModelRequest, warnings: list[str]) -> ModelRequest:
        if not warnings:
            return request
        message = HumanMessage(content="\n\n".join(warnings), name="spend_budget_warning")
        return request.override(messages=[*getattr(request, "messages", []), message])

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        return handler(self._inject_warnings(request, self._drain_pending_warnings(request.runtime)))

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        return await handler(self._inject_warnings(request, self._drain_pending_warnings(request.runtime)))
