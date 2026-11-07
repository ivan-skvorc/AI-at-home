"""Shared interaction policy for lead-agent tools and prompt guidance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

ASK_CLARIFICATION_TOOL_NAME = "ask_clarification"


class RunInteractionMode(StrEnum):
    """Interaction modes that can be selected by a trusted run entry point."""

    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"
    WEBHOOK = "webhook"
    SCHEDULED = "scheduled"


_INTERACTIVE_CLARIFICATION_SYSTEM = """<clarification_system>
**Clarify, then plan, then act.** In your thinking, check whether anything the result depends on is missing,
ambiguous or risky. If it is, you MUST call ask_clarification before doing any work: never start and then ask
mid-task, and never guess at something only the user knows.

Ask (`clarification_type`) when:
- `missing_info`: a required detail is absent, e.g. which site to scrape or which environment to deploy to.
- `ambiguous_requirement`: the request has several reasonable readings, e.g. "optimize it": speed, memory or readability?
- `approach_choice`: several valid approaches exist and the choice is the user's, e.g. JWT, OAuth or sessions.
- `risk_confirmation`: the action is destructive or hard to undo, e.g. deleting files, changing production config, overwriting data.
- `suggestion`: you want approval for something beyond what was asked.

How:
- One clarification at a time: a specific question, with `options` when the choices are clear (one `fields` form counts as one).
- Call no other tool in the same turn: sibling calls are dropped, and the run pauses until the user answers.
- Do not ask about details with an obvious default that do not change the result.
</clarification_system>"""

_AUTONOMOUS_CLARIFICATION_SYSTEM = """<clarification_system>
**WORKFLOW PRIORITY: ASSESS -> CHOOSE THE LOWEST-RISK PATH -> ACT**

There is no human available to answer a synchronous question during this run.
Do not wait for clarification or approval. Resolve ambiguity from the request,
{context_sources}.

- For low-risk and reversible work, make the smallest reasonable assumption and continue.
- State every material assumption in the final result, one line each: what was unclear, what you chose, and why.
- For high-risk or irreversible work without sufficient authorization, do not guess:
  stop with a concise structured `BLOCKED` result that names the missing decision.
- Prefer inspection and read-only checks before changing state.
</clarification_system>"""

_AUTONOMOUS_CONTEXT_SOURCES = "the available run context and existing configuration"
_WEBHOOK_CONTEXT_SOURCES = "the issue, pull request, repository, event context, and existing configuration"


@dataclass(frozen=True, slots=True)
class RunInteractionPolicy:
    """The single source for interaction-sensitive tools and prompt guidance."""

    mode: RunInteractionMode

    @property
    def allows_clarification(self) -> bool:
        return self.mode is RunInteractionMode.INTERACTIVE

    @property
    def disabled_tool_names(self) -> frozenset[str]:
        if self.allows_clarification:
            return frozenset()
        return frozenset({ASK_CLARIFICATION_TOOL_NAME})

    @property
    def thinking_guidance(self) -> str:
        if self.allows_clarification:
            return "- **PRIORITY CHECK: If anything is unclear, missing, or has multiple interpretations, you MUST ask for clarification FIRST - do NOT proceed with work**"
        return "- **INTERACTION CHECK: This run has no synchronous human. Resolve ambiguity with the run context, choose the lowest-risk reversible path, and record material assumptions.**"

    @property
    def clarification_system(self) -> str:
        if self.allows_clarification:
            return _INTERACTIVE_CLARIFICATION_SYSTEM
        context_sources = _WEBHOOK_CONTEXT_SOURCES if self.mode is RunInteractionMode.WEBHOOK else _AUTONOMOUS_CONTEXT_SOURCES
        return _AUTONOMOUS_CLARIFICATION_SYSTEM.format(context_sources=context_sources)

    @property
    def clarification_reminder(self) -> str:
        if self.allows_clarification:
            return "- **Clarification First**: Clarify what is unclear, missing or ambiguous BEFORE starting work; never guess at what only the user knows"
        return "- **Autonomous Interaction**: Do not wait for a human response; make minimal reversible assumptions, list them, or return a structured `BLOCKED` result for high-risk ambiguity"

    @classmethod
    def interactive(cls) -> RunInteractionPolicy:
        return cls(RunInteractionMode.INTERACTIVE)


def resolve_run_interaction_policy(config: Mapping[str, Any] | None) -> RunInteractionPolicy:
    """Resolve one policy from legacy runtime flags and channel context.

    ``non_interactive`` is the scheduler's trusted legacy flag. GitHub and
    other webhook channels currently use ``disable_clarification`` and/or
    ``channel_name``; both remain supported while callers migrate to an
    explicit mode.
    """

    merged: dict[str, Any] = {}
    if config:
        configurable = config.get("configurable")
        context = config.get("context")
        if isinstance(configurable, Mapping):
            merged.update(configurable)
        if isinstance(context, Mapping):
            merged.update(context)

    raw_mode = merged.get("interaction_mode")
    if raw_mode is not None:
        try:
            return RunInteractionPolicy(RunInteractionMode(str(raw_mode)))
        except ValueError as exc:
            valid_modes = ", ".join(mode.value for mode in RunInteractionMode)
            raise ValueError(f"Invalid interaction_mode {raw_mode!r}; expected one of: {valid_modes}") from exc

    if merged.get("non_interactive"):
        return RunInteractionPolicy(RunInteractionMode.SCHEDULED)
    if merged.get("channel_name") == "github":
        return RunInteractionPolicy(RunInteractionMode.WEBHOOK)
    if merged.get("disable_clarification"):
        return RunInteractionPolicy(RunInteractionMode.AUTONOMOUS)
    return RunInteractionPolicy.interactive()
