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
from .transcript import SourceTranscript, format_message_rows, format_scheduled_task, neutralize_source_delimiters, truncate

__all__ = [
    "VALID_VERDICTS",
    "VERDICT_NO_GAP",
    "VERDICT_PROPOSE",
    "AgentAnalysis",
    "AgentAnalysisError",
    "AgentProposal",
    "SourceTranscript",
    "build_system_instruction",
    "build_user_content",
    "format_message_rows",
    "format_scheduled_task",
    "neutralize_source_delimiters",
    "normalize_agent_name",
    "parse_analysis",
    "truncate",
    "uniquify_agent_name",
]
