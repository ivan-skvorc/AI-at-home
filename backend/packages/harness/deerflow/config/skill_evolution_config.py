from pydantic import BaseModel, Field


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
            "The curator switches off agent-written custom skills that nobody loaded for this many days (the user can switch them back on in "
            "Settings → Skills; nothing is deleted). 0 turns the curator off. Only applies when enabled is true."
        ),
    )
