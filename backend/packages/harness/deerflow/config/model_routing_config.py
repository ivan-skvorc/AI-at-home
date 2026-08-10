"""Cost-aware subagent routing policy (fork feature).

Declarative rules mapping *what a subtask needs* to *which models to prefer*.
The requirements are read from the capability flags that already exist on model
entries plus the size of the prompt — never from an extra LLM call, which would
spend money to decide how to save money.

Off by default, consistent with how this fork treats anything that changes agent
behavior. An explicit per-thread subagent selection always wins; the policy only
fills the default.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class RoutingConditions(BaseModel):
    """When a rule applies. Every unset condition is a wildcard."""

    needs_tools: bool | None = Field(default=None, description="Match only subtasks that do (true) or do not (false) require business tools.")
    needs_vision: bool | None = Field(default=None, description="Match only subtasks that do (true) or do not (false) require image understanding.")
    needs_thinking: bool | None = Field(default=None, description="Match only subtasks that do (true) or do not (false) require extended thinking.")
    max_context: int | None = Field(default=None, gt=0, description="Match only when the estimated context (prompt + overhead, in tokens) is at or below this.")
    min_context: int | None = Field(default=None, gt=0, description="Match only when the estimated context is at or above this.")

    @model_validator(mode="after")
    def _validate_context_window(self) -> RoutingConditions:
        if self.min_context is not None and self.max_context is not None and self.min_context > self.max_context:
            raise ValueError(f"min_context ({self.min_context}) is above max_context ({self.max_context}), so this rule can never match")
        return self


class RoutingRule(BaseModel):
    """One rule: conditions plus an ordered model preference."""

    name: str = Field(..., min_length=1, description="Human-readable rule name; shown on the subagent card so the decision is inspectable.")
    when: RoutingConditions = Field(default_factory=RoutingConditions, description="Conditions that must all hold for this rule to apply.")
    prefer: list[str] = Field(default_factory=list, description="Ordered model names to try. The first one that is configured and capable wins; the rest are reported as skipped.")


class ModelRoutingConfig(BaseModel):
    """Config section for cost-aware subagent routing."""

    enabled: bool = Field(default=False, description="Whether the routing policy applies. Off by default. An explicit per-thread subagent model always wins over it.")
    rules: list[RoutingRule] = Field(default_factory=list, description="Rules evaluated in order; the first whose conditions hold and that offers a capable model decides.")

    @model_validator(mode="after")
    def _validate_enabled_has_rules(self) -> ModelRoutingConfig:
        # Enabling the feature and configuring nothing is a mistake, not a
        # preference — the same stance spend_budget takes for a missing limit.
        if self.enabled and not self.rules:
            raise ValueError("model_routing.enabled is true but no rules are configured; add at least one rule or set enabled: false")
        return self
