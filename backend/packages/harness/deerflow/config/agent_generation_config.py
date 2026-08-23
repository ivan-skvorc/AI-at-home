"""Configuration for automatic custom-agent generation.

The generator reads a user's own past conversations and scheduled tasks, asks
one model whether the existing custom agents already cover that work, and — only
when they do not — drafts a new agent for the user to review. Every limit here
exists to bound the single LLM request: transcripts in this product routinely run
to hundreds of turns with large tool payloads, so sources are digested and capped
before they are concatenated rather than sent whole.
"""

from pydantic import BaseModel, Field

# Hard ceiling on how many conversations/tasks one analysis may span. This is a
# schema bound rather than a mere default: the analyze route builds a single
# prompt from every selected source, so an unbounded list is an unbounded
# request. Operators may lower ``max_sources`` but not raise it past this.
MAX_SOURCES_LIMIT = 25


class AgentGenerationConfig(BaseModel):
    """Configuration for the analyze-conversations -> propose-an-agent flow."""

    enabled: bool = Field(
        default=False,
        description=("Whether the agent-generation API and its UI entry point are available. Off by default: the flow reads conversation transcripts and drafts agents, so it is opt-in."),
    )
    model_name: str | None = Field(
        default=None,
        description="Default model used for the analysis when the request does not pick one. Leave null to use the primary chat model.",
    )
    max_sources: int = Field(
        default=10,
        ge=1,
        le=MAX_SOURCES_LIMIT,
        description=f"Maximum conversations/tasks a single analysis may read (1-{MAX_SOURCES_LIMIT}).",
    )
    max_messages_per_source: int = Field(
        default=40,
        ge=1,
        le=200,
        description="Maximum messages read from each selected conversation. The most recent messages are kept.",
    )
    max_chars_per_message: int = Field(
        default=1500,
        ge=100,
        le=20000,
        description="Per-message character cap applied before messages are concatenated into a transcript.",
    )
    max_chars_per_source: int = Field(
        default=8000,
        ge=500,
        le=100000,
        description="Per-source character cap applied to the finished transcript, after the per-message cap.",
    )
    max_runs_per_task: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum recent runs summarized for each selected scheduled task.",
    )
