from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


class SkillEvolutionConfig(BaseModel):
    """Configuration for agent-managed skill evolution."""

    enabled: bool = Field(
        default=False,
        description="Whether the agent can create and modify skills under skills/custom.",
    )
    moderation_model_name: str | None = Field(
        default=None,
        description="Optional model name for skill security moderation. Defaults to the primary chat model.",
    )
    security_fail_closed: bool = Field(
        default=True,
        description=("When the moderation model is unavailable, block skill writes if True (fail-closed). If False, non-executable content is allowed with a warning while executable content is still blocked."),
    )
    nudge_after_tool_calls: int = Field(
        default=8,
        ge=0,
        description=(
            "When a run used at least this many tool calls and never called skill_manage, the lead agent is reminded once, before its final answer, "
            "to save what it learned as a skill (or patch a custom skill it used). 0 turns the reminder off. Only applies when enabled is true."
        ),
    )
    archive_unused_after_days: int = Field(
        default=90,
        ge=0,
        description=(
            "The curator switches off agent-written custom skills that nobody loaded for this many days (nothing is deleted; they are switched "
            "back on in Capability Center → Skills). It curates only for admins and for runs without a role, the owners who can switch a skill "
            "back on. 0 turns the curator off. Only applies when enabled is true."
        ),
    )

    @field_validator("nudge_after_tool_calls", "archive_unused_after_days", mode="before")
    @classmethod
    def _reject_boolean_counts(cls, value: object, info: ValidationInfo) -> object:
        # `archive_unused_after_days: true` would otherwise become a one-day curator.
        return reject_boolean(value, info, kind="an integer")
