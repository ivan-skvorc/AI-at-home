"""Configuration for HarnessGuard tool-loop interceptor middleware."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HarnessGuardConfig(BaseModel):
    """Configuration for system harness tool-loop interception, optional write-verification,
    and anti-doom-loop mechanisms."""

    enabled: bool = Field(
        default=True,
        description="Whether the HarnessGuard tool-loop interceptor middleware is enabled",
    )
    write_verify_syntax: bool = Field(
        default=False,
        description="Whether to perform pre-execution syntax validation on .py/.pyi (ast.parse), .json (json.loads), .yaml/.yml (yaml.compose_all) and .toml (tomllib) str_replace edits",
    )
    block_on_syntax_error: bool = Field(
        default=True,
        description="Whether to reject the write immediately if a syntax error is detected",
    )
    verify_before_finish: bool = Field(
        default=True,
        description=("Remind the lead agent once, before its final answer, when it edited code files in this run and ran no command afterwards, so it runs the tests or says why it could not. Applies only when the agent has the bash tool."),
    )
    targeted_hints_enabled: bool = Field(
        default=True,
        description="Whether to analyze tool error outputs and append actionable targeted hints",
    )
    max_repeated_error_signatures: int = Field(
        default=2,
        ge=1,
        description="Threshold of consecutive identical error signatures before triggering a critical repetition warning",
    )
    detect_alternating_loops: bool = Field(
        default=True,
        description="Whether to detect A -> B -> A -> B alternating failure patterns between different tools",
    )
    max_loop_history: int = Field(
        default=20,
        ge=5,
        description="Sliding window size of recent tool calls tracked for loop and pattern detection",
    )
    max_tracked_scopes: int = Field(
        default=1000,
        ge=10,
        description="Maximum number of tracked thread/run scopes retained in the bounded LRU history cache",
    )
