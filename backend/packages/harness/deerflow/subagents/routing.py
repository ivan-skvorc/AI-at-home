"""Cost-aware model routing for subagents (fork feature).

The fork exposes the lever — a per-thread lead model and a per-thread subagent
override — but the user has to pull it every session. FORK.md's own worked
example puts Sonnet-lead / Haiku-subagents at ~63% cheaper than all-Sonnet, and
Sonnet-lead / local-subagents at ~95%. A policy turns that UI affordance into a
standing saving.

Three things keep this honest rather than clever:

**No LLM classifies the task.** Requirements are read from facts already on the
table — whether the subagent was given tools, whether it can view images,
whether the operator declared it needs thinking, and how big the prompt is.
Adding a classification call would spend money to decide how to save money, and
would make the routing decision non-deterministic.

**The user's explicit choice always wins.** The policy fills the *default*.
An explicit per-thread subagent selection is applied before this module is ever
consulted, and a rule can only ever narrow what would otherwise have been the
lead's model.

**A model is only chosen if it can actually do the job.** A rule expresses a
preference order; capability filtering is applied to it, not merely alongside
it. Routing a tool-using subtask to a model with ``supports_tools: false``
would trade a cost saving for a failed turn, which is not a trade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Rough characters-per-token used to size a prompt without tokenizing it. Only
# ever compared against an operator-set `max_context` threshold, so the error
# bar is far below the granularity of the decision it feeds.
_CHARS_PER_TOKEN = 4

# Headroom for what a subagent carries besides the prompt: system prompt, tool
# schemas, skill index, and the answer it has to produce.
_CONTEXT_OVERHEAD_TOKENS = 8000


@dataclass(frozen=True)
class TaskRequirements:
    """What a delegated subtask actually needs, derived without asking a model."""

    needs_tools: bool
    needs_vision: bool
    needs_thinking: bool
    estimated_context: int

    @classmethod
    def from_task(
        cls,
        *,
        tool_names: list[str] | None = None,
        prompt: str = "",
        description: str = "",
        needs_thinking: bool = False,
    ) -> TaskRequirements:
        names = set(tool_names or [])
        # `view_image` is only bound when the resolved model supports vision, so
        # its presence is a real capability requirement rather than a guess.
        vision_tools = {"view_image"}
        business_tools = names - vision_tools
        estimated = (len(prompt) + len(description)) // _CHARS_PER_TOKEN + _CONTEXT_OVERHEAD_TOKENS
        return cls(
            needs_tools=bool(business_tools),
            needs_vision=bool(names & vision_tools),
            needs_thinking=needs_thinking,
            estimated_context=estimated,
        )


@dataclass(frozen=True)
class RoutingDecision:
    """The outcome, in a shape that can be shown on the subagent card."""

    model_name: str | None
    rule: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "rule": self.rule, "reason": self.reason}


def _model_supports(model: Any, requirements: TaskRequirements) -> tuple[bool, str]:
    """Can *model* serve a subtask with these requirements?"""
    if requirements.needs_tools and getattr(model, "supports_tools", True) is False:
        return False, "no tool support"
    if requirements.needs_vision and not getattr(model, "supports_vision", False):
        return False, "no vision support"
    if requirements.needs_thinking and not getattr(model, "supports_thinking", False):
        return False, "no thinking support"
    context_window = getattr(model, "context_window", None)
    if context_window and requirements.estimated_context > context_window:
        return False, f"context window {context_window} < estimated {requirements.estimated_context}"
    return True, ""


def _rule_matches(rule: Any, requirements: TaskRequirements) -> bool:
    """Every condition a rule declares must hold; unset conditions are wildcards."""
    when = rule.when
    if when.needs_tools is not None and when.needs_tools != requirements.needs_tools:
        return False
    if when.needs_vision is not None and when.needs_vision != requirements.needs_vision:
        return False
    if when.needs_thinking is not None and when.needs_thinking != requirements.needs_thinking:
        return False
    if when.max_context is not None and requirements.estimated_context > when.max_context:
        return False
    if when.min_context is not None and requirements.estimated_context < when.min_context:
        return False
    return True


def resolve_routed_model(
    requirements: TaskRequirements,
    policy: Any,
    models: list[Any],
    *,
    fallback_model: str | None = None,
) -> RoutingDecision:
    """Pick the cheapest capable model the policy prefers, or leave the default.

    Returns a decision whose ``model_name`` is ``None`` when the policy does not
    apply — the caller then keeps whatever it already resolved. A decision is
    always returned (never ``None``) so the reason can be surfaced on the card
    even when nothing was routed; "why did this NOT route?" is the question an
    operator asks first.
    """
    if policy is None or not getattr(policy, "enabled", False):
        return RoutingDecision(None, None, "routing policy disabled")

    by_name = {model.name: model for model in models}

    for rule in getattr(policy, "rules", []) or []:
        if not _rule_matches(rule, requirements):
            continue
        skipped: list[str] = []
        for candidate in rule.prefer:
            model = by_name.get(candidate)
            if model is None:
                skipped.append(f"{candidate} (not configured)")
                continue
            if candidate == fallback_model:
                # Already the default; routing to it is a no-op worth reporting
                # as "matched but unchanged" rather than as a route.
                return RoutingDecision(None, rule.name, f"rule '{rule.name}' matched; {candidate} is already the default")
            ok, why = _model_supports(model, requirements)
            if not ok:
                skipped.append(f"{candidate} ({why})")
                continue
            reason = f"rule '{rule.name}' matched"
            if skipped:
                reason += f"; skipped {', '.join(skipped)}"
            return RoutingDecision(candidate, rule.name, reason)

        # A rule matched but nothing in it can serve the task. Fall through to
        # the next rule rather than failing the delegation: the policy is an
        # optimization, and an unroutable subtask still has a working default.
        logger.info("model routing: rule %r matched but no candidate is capable (%s)", rule.name, "; ".join(skipped) or "empty prefer list")

    return RoutingDecision(None, None, "no rule matched")
