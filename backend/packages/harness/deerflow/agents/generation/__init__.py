"""Automatic custom-agent generation from a user's past conversations and tasks."""

from .analysis import (
    VALID_VERDICTS,
    VERDICT_NO_GAP,
    VERDICT_PROPOSE,
    AgentAnalysis,
    AgentAnalysisError,
    AgentProposal,
    build_system_instruction,
    build_user_content,
    normalize_agent_name,
    parse_analysis,
    uniquify_agent_name,
)
from .transcript import (
    BLOCK_TAG_NAMES,
    SourceTranscript,
    escape_block_attribute,
    format_message_rows,
    format_scheduled_task,
    neutralize_block_delimiters,
    truncate,
)

__all__ = [
    "VALID_VERDICTS",
    "VERDICT_NO_GAP",
    "VERDICT_PROPOSE",
    "AgentAnalysis",
    "AgentAnalysisError",
    "AgentProposal",
    "BLOCK_TAG_NAMES",
    "SourceTranscript",
    "build_system_instruction",
    "escape_block_attribute",
    "build_user_content",
    "format_message_rows",
    "format_scheduled_task",
    "neutralize_block_delimiters",
    "normalize_agent_name",
    "parse_analysis",
    "truncate",
    "uniquify_agent_name",
]
