"""Read and edit the lead-agent system prompt (fork feature).

Exposes the prompt every run starts from — the built-in template, whatever
override is in force, and the fully rendered result — so **Settings → System
Prompt** can show it and write it back.

Admin-gated on both read and write. Writing rewrites the instructions for every
subsequent run, which is the same blast radius as skill and MCP management, and
reading returns framework-internal context the agent itself is instructed not to
disclose; so both sit behind :func:`require_admin_user`, like those routers.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.deps import require_admin_user
from deerflow.agents.lead_agent.prompt import (
    SYSTEM_PROMPT_PLACEHOLDERS,
    SYSTEM_PROMPT_TEMPLATE,
    apply_prompt_template,
)
from deerflow.agents.lead_agent.system_prompt_store import (
    MAX_TEMPLATE_CHARS,
    SystemPromptTemplateError,
    clear_custom_system_prompt,
    extract_placeholders,
    load_custom_system_prompt,
    save_custom_system_prompt,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system-prompt"])

_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage the system prompt."


class SystemPromptResponse(BaseModel):
    """The system prompt in force, plus what the editor needs to validate edits."""

    content: str = Field(..., description="The template in force — the saved override, or the built-in template when there is none")
    default_content: str = Field(..., description="The built-in template, so the editor can diff against it and offer a reset")
    is_custom: bool = Field(..., description="Whether a saved override is in force")
    placeholders: list[str] = Field(..., description="Placeholder names the template may use, sorted")
    missing_placeholders: list[str] = Field(..., description="Placeholders the built-in template uses that the current one omits — dropped sections, not errors")
    max_length: int = Field(..., description="Maximum accepted template length in characters")


class SystemPromptUpdateRequest(BaseModel):
    """Request body for replacing the system prompt."""

    content: str = Field(..., description="The replacement template. May use any of the reported placeholders; escape a literal brace as `{{`.")


class SystemPromptPreviewResponse(BaseModel):
    """The prompt as the lead agent actually receives it."""

    rendered: str = Field(..., description="The template with every placeholder substituted")
    is_custom: bool = Field(..., description="Whether the render used a saved override")


def _build_response() -> SystemPromptResponse:
    """Assemble the current state of the prompt for the editor."""
    override = load_custom_system_prompt()
    content = override if override is not None else SYSTEM_PROMPT_TEMPLATE
    return SystemPromptResponse(
        content=content,
        default_content=SYSTEM_PROMPT_TEMPLATE,
        is_custom=override is not None,
        placeholders=sorted(SYSTEM_PROMPT_PLACEHOLDERS),
        # An omitted placeholder drops that section from the prompt. That is a
        # legitimate edit, so it is reported for the UI to warn about rather
        # than rejected on save.
        missing_placeholders=sorted(SYSTEM_PROMPT_PLACEHOLDERS - extract_placeholders(content)),
        max_length=MAX_TEMPLATE_CHARS,
    )


@router.get(
    "/system-prompt",
    response_model=SystemPromptResponse,
    summary="Get System Prompt",
    description="Return the lead-agent system prompt template in force, the built-in default, and the placeholders an edit may use.",
)
async def get_system_prompt(request: Request) -> SystemPromptResponse:
    """Return the current system prompt template and its editing contract."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        return await asyncio.to_thread(_build_response)
    except Exception as e:
        logger.error("Failed to read the system prompt: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read the system prompt: {str(e)}")


@router.put(
    "/system-prompt",
    response_model=SystemPromptResponse,
    summary="Update System Prompt",
    description="Replace the lead-agent system prompt template. Takes effect on the next run; no Gateway restart needed.",
)
async def update_system_prompt(body: SystemPromptUpdateRequest, request: Request) -> SystemPromptResponse:
    """Validate and persist a replacement system prompt template."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    def _save() -> SystemPromptResponse:
        # Validation happens inside save_custom_system_prompt, before any write,
        # so a rejected edit leaves the previous prompt untouched.
        save_custom_system_prompt(body.content, allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        return _build_response()

    try:
        return await asyncio.to_thread(_save)
    except SystemPromptTemplateError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Failed to update the system prompt: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update the system prompt: {str(e)}")


@router.delete(
    "/system-prompt",
    response_model=SystemPromptResponse,
    summary="Reset System Prompt",
    description="Discard the saved override and revert to the built-in template. A no-op when no override is saved.",
)
async def reset_system_prompt(request: Request) -> SystemPromptResponse:
    """Remove the override, returning the resulting (built-in) state."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    def _reset() -> SystemPromptResponse:
        clear_custom_system_prompt()
        return _build_response()

    try:
        return await asyncio.to_thread(_reset)
    except Exception as e:
        logger.error("Failed to reset the system prompt: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reset the system prompt: {str(e)}")


@router.get(
    "/system-prompt/preview",
    response_model=SystemPromptPreviewResponse,
    summary="Preview System Prompt",
    description="Render the system prompt with every placeholder substituted — the exact text the lead agent receives.",
)
async def preview_system_prompt(
    request: Request,
    subagent_enabled: bool = Query(default=True, description="Render the subagent block, as Ultra mode does"),
) -> SystemPromptPreviewResponse:
    """Render the prompt exactly as a run would build it.

    Rendered for the default lead agent, so ``{soul}`` and the self-update block
    come out empty — a custom agent's SOUL is edited on that agent's own page.
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    def _render() -> SystemPromptPreviewResponse:
        # apply_prompt_template reads skills and config from disk; keep it off
        # the event loop.
        return SystemPromptPreviewResponse(
            rendered=apply_prompt_template(subagent_enabled=subagent_enabled),
            is_custom=load_custom_system_prompt() is not None,
        )

    try:
        return await asyncio.to_thread(_render)
    except Exception as e:
        logger.error("Failed to render the system prompt preview: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to render the system prompt preview: {str(e)}")
