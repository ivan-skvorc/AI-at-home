"""HTTP API for automatic custom-agent generation.

One route does the work: the caller picks a model and a handful of their own
conversations / scheduled tasks, and the model answers whether those sources
justify a NEW custom agent. Creation is deliberately *not* part of this route —
it returns a draft, and the existing ``POST /api/agents`` route persists it once
the user has read and accepted the proposal. Keeping the analysis read-only means
a hallucinated proposal can never silently become an agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_config,
    get_optional_user_from_request,
    get_run_event_store,
    get_scheduled_task_repo,
    get_scheduled_task_run_repo,
    get_thread_store,
)
from deerflow.agents.generation import (
    AgentAnalysisError,
    AgentProposal,
    SourceTranscript,
    build_system_instruction,
    build_user_content,
    format_message_rows,
    format_scheduled_task,
    parse_analysis,
)
from deerflow.config.agent_generation_config import MAX_SOURCES_LIMIT
from deerflow.config.agents_api_config import get_agents_api_config
from deerflow.config.agents_config import list_custom_agents
from deerflow.config.app_config import AppConfig
from deerflow.runtime.aux_usage import arecord_aux_usage_metadata
from deerflow.utils.oneshot_llm import run_oneshot_llm_with_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-generation", tags=["agent-generation"])

# Aux-usage bucket for this feature. The analysis spans several conversations at
# once, so billing it to any one of them would misattribute the cost; a dedicated
# pseudo-thread keeps it visible on the Spend page under its own row instead.
# A draft comes back from the client with the user's hand edits, so the inbound
# cap is the generator's own SOUL cap plus headroom rather than an exact match.
MAX_SOUL_INPUT_CHARS = 20000

USAGE_THREAD_ID = "agent-generation"
USAGE_CATEGORY = "agent_generation"

SourceKind = Literal["thread", "scheduled_task"]


class GenerationSource(BaseModel):
    """One conversation or scheduled task selected for analysis."""

    kind: SourceKind = Field(..., description="Source type: an existing conversation or a scheduled task")
    id: str = Field(..., min_length=1, max_length=200, description="Thread id or scheduled task id")


class DraftInput(BaseModel):
    """A draft the caller is asking to have revised."""

    name: str = Field(..., min_length=1, max_length=200, description="Current draft agent name")
    description: str = Field(default="", max_length=1000, description="Current draft description")
    soul: str = Field(..., min_length=1, max_length=MAX_SOUL_INPUT_CHARS, description="Current draft SOUL.md, including any hand edits")


class AnalyzeRequest(BaseModel):
    """Request body for an agent-generation analysis."""

    sources: list[GenerationSource] = Field(..., min_length=1, max_length=MAX_SOURCES_LIMIT, description="Conversations / scheduled tasks the new agent should be shaped around")
    model_name: str | None = Field(default=None, description="Model to run the analysis with. Null uses the configured default.")
    goal: str | None = Field(default=None, description="Optional: what the user wants the agent for, or — when revising — what to change about the draft.")
    force_proposal: bool = Field(default=False, description="Draft an agent even if an existing one overlaps. Set after the user has seen a no_gap verdict and asked anyway.")
    revise_from: DraftInput | None = Field(default=None, description="Revise this draft instead of analyzing afresh. Implies force_proposal.")


class ProposalResponse(BaseModel):
    """A drafted agent, shaped for ``POST /api/agents``."""

    name: str = Field(..., description="Suggested agent name (hyphen-case, free for this user)")
    description: str = Field(default="", description="One-line description")
    soul: str = Field(..., description="Generated SOUL.md content")
    skills: list[str] | None = Field(default=None, description="Suggested skill whitelist (null = all enabled skills)")


class AnalyzeResponse(BaseModel):
    """Result of an agent-generation analysis."""

    verdict: Literal["propose", "no_gap"] = Field(..., description="Whether a new agent is warranted")
    rationale: str = Field(default="", description="Why the model reached this verdict")
    covered_by: str | None = Field(default=None, description="Existing agent that already covers this work, when the verdict is no_gap")
    proposal: ProposalResponse | None = Field(default=None, description="The drafted agent, present only when the verdict is propose")
    analyzed_sources: int = Field(..., description="How many sources contributed content to the analysis")
    model_name: str | None = Field(default=None, description="Model that served the analysis")
    forced: bool = Field(default=False, description="True when this draft was produced because the caller overrode a no_gap verdict or revised a draft")


class GenerationConfigResponse(BaseModel):
    """Limits and availability of the agent-generation flow."""

    enabled: bool = Field(..., description="Whether the flow is usable end to end (needs both agent_generation and agents_api enabled)")
    max_sources: int = Field(..., description="Maximum conversations / tasks one analysis may read")
    default_model_name: str | None = Field(default=None, description="Model used when the request does not pick one")
    max_goal_chars: int = Field(..., description="Maximum length of the goal / revision guidance text")


def _require_enabled(config: AppConfig) -> None:
    """Reject the request unless the whole flow is available.

    Both switches matter: ``agent_generation`` gates the analysis itself, and
    ``agents_api`` gates the create route the proposal is destined for.
    Producing a draft the user cannot save would be a dead end, so the second
    switch is checked here rather than at the end of the wizard.
    """
    if not config.agent_generation.enabled:
        raise HTTPException(status_code=404, detail="Agent generation is disabled. Set agent_generation.enabled=true to enable it.")
    if not get_agents_api_config().enabled:
        raise HTTPException(
            status_code=403,
            detail="Agent generation needs the custom-agent management API. Set agents_api.enabled=true to expose agent routes over HTTP.",
        )


def _validate_goal(goal: str | None, *, limit: int) -> str | None:
    """Normalize the caller's goal text, rejecting one that exceeds the cap.

    Enforced here rather than by a Pydantic ``max_length`` so the bound tracks
    ``agent_generation.max_goal_chars`` at request time — an operator raising the
    cap must not need a restart-time schema change — and so an over-long goal
    fails with a message naming the limit instead of a generic 422.
    """
    if goal is None:
        return None
    trimmed = goal.strip()
    if not trimmed:
        return None
    if len(trimmed) > limit:
        raise HTTPException(status_code=422, detail=f"Goal is too long: {len(trimmed)} characters, but at most {limit} are allowed.")
    return trimmed


def _dedupe_sources(sources: list[GenerationSource], *, limit: int) -> list[GenerationSource]:
    """Drop repeated selections and enforce the configured source cap."""
    seen: set[tuple[str, str]] = set()
    unique: list[GenerationSource] = []
    for source in sources:
        key = (source.kind, source.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    if len(unique) > limit:
        raise HTTPException(status_code=422, detail=f"Too many sources: {len(unique)} selected, but at most {limit} may be analyzed at once.")
    return unique


async def _thread_transcript(source: GenerationSource, *, request: Request, user_id: str, config: AppConfig) -> SourceTranscript | None:
    """Digest one conversation the caller owns, or raise 404 if they do not."""
    gen = config.agent_generation
    thread_store = get_thread_store(request)

    # Ownership is checked per source rather than by the route decorator, which
    # can only see a single ``thread_id`` path parameter. ``require_existing``
    # is on for the same reason the destructive thread routes use it: a missing
    # row must not read as "untracked legacy thread, allow" on a route that
    # returns conversation content.
    allowed = await thread_store.check_access(source.id, user_id, require_existing=True)
    if not allowed:
        raise HTTPException(status_code=404, detail=f"Thread {source.id} not found")

    record = await thread_store.get(source.id)
    title = ""
    if isinstance(record, dict):
        title = str(record.get("display_name") or "").strip()

    event_store = get_run_event_store(request)
    rows = await event_store.list_messages(
        source.id,
        # Read more rows than the message cap: tool results and empty turns are
        # dropped during digestion, so a raw limit equal to the cap would leave
        # a long conversation with only a few renderable lines.
        limit=min(gen.max_messages_per_source * 3, 200),
        user_id=user_id,
    )
    body = format_message_rows(
        rows,
        max_messages=gen.max_messages_per_source,
        max_chars_per_message=gen.max_chars_per_message,
        max_chars_per_source=gen.max_chars_per_source,
    )
    if not body:
        return None
    return SourceTranscript(kind="conversation", source_id=source.id, title=title or "Untitled conversation", body=body)


async def _scheduled_task_transcript(source: GenerationSource, *, request: Request, user_id: str, config: AppConfig) -> SourceTranscript | None:
    """Digest one scheduled task the caller owns, or raise 404 if they do not."""
    gen = config.agent_generation
    task_repo = get_scheduled_task_repo(request)
    task = await task_repo.get(source.id, user_id=user_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task {source.id} not found")

    run_repo = get_scheduled_task_run_repo(request)
    runs = await run_repo.list_by_task(source.id, limit=gen.max_runs_per_task, offset=0)

    body = format_scheduled_task(task, runs or [], max_runs=gen.max_runs_per_task, max_chars_per_source=gen.max_chars_per_source)
    if not body:
        return None
    return SourceTranscript(kind="scheduled task", source_id=source.id, title=str(task.get("title") or "").strip() or "Untitled task", body=body)


async def _record_usage(model_name: str | None, usage: dict[str, Any] | None) -> None:
    """Bill the analysis call to the aux-usage counter (best-effort).

    Billed to a synthetic thread id, not a conversation: the analysis reads
    several threads and belongs to none of them, so it appears on the spend
    page's feature table rather than in any chat header.

    The shared helper already swallows a store failure; the guard here is
    deliberately kept on top of it so the property survives a break in *any*
    layer beneath this line. The analysis has already been paid for at the
    provider by the time we get here — a broken counter must never cost the user
    the result they bought.
    """
    try:
        await arecord_aux_usage_metadata(USAGE_THREAD_ID, USAGE_CATEGORY, model_name=model_name, usage=usage)
    except Exception:  # pragma: no cover - defensive: accounting must not break the feature
        logger.debug("failed to record agent-generation aux usage", exc_info=True)


@router.get(
    "/config",
    response_model=GenerationConfigResponse,
    summary="Get Agent Generation Configuration",
    description="Returns whether automatic agent generation is available and the limits that apply to it.",
)
async def get_generation_config(config: AppConfig = Depends(get_config)) -> GenerationConfigResponse:
    gen = config.agent_generation
    return GenerationConfigResponse(
        enabled=gen.enabled and get_agents_api_config().enabled,
        max_sources=gen.max_sources,
        default_model_name=gen.model_name,
        max_goal_chars=gen.max_goal_chars,
    )


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze Past Work For A New Agent",
    description="Read the selected conversations / scheduled tasks and decide whether a new custom agent is warranted. Read-only: nothing is persisted.",
)
@require_permission("threads", "read")
async def analyze_sources(
    body: AnalyzeRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> AnalyzeResponse:
    _require_enabled(config)

    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = str(user.id)

    sources = _dedupe_sources(body.sources, limit=config.agent_generation.max_sources)
    goal = _validate_goal(body.goal, limit=config.agent_generation.max_goal_chars)

    # Revising a draft the user is already looking at means the "should this agent
    # exist" question is settled, so a revision always implies the override.
    revise_from = None
    if body.revise_from is not None:
        revise_from = AgentProposal(
            name=body.revise_from.name,
            description=body.revise_from.description,
            soul=body.revise_from.soul,
        )
        if goal is None:
            raise HTTPException(status_code=422, detail="Revising a draft requires guidance describing what to change.")
    force_proposal = body.force_proposal or revise_from is not None

    transcripts: list[SourceTranscript] = []
    for source in sources:
        if source.kind == "thread":
            transcript = await _thread_transcript(source, request=request, user_id=user_id, config=config)
        else:
            transcript = await _scheduled_task_transcript(source, request=request, user_id=user_id, config=config)
        if transcript is not None:
            transcripts.append(transcript)

    if not transcripts:
        raise HTTPException(status_code=422, detail="The selected sources contain no readable content to analyze.")

    # The agent roster is read through the store (filesystem or DB), so keep it
    # off the event loop like every other caller of list_custom_agents.
    existing = await asyncio.to_thread(list_custom_agents, user_id=user_id)
    existing_agents = [{"name": agent.name, "description": agent.description} for agent in existing]

    model_name = body.model_name or config.agent_generation.model_name

    try:
        result = await run_oneshot_llm_with_usage(
            system_instruction=build_system_instruction(
                existing_agents,
                has_goal=goal is not None,
                force_proposal=force_proposal,
                revising=revise_from is not None,
            ),
            user_content=build_user_content(transcripts, goal=goal, revise_from=revise_from),
            run_name="agent_generation_revision" if revise_from is not None else "agent_generation_analysis",
            app_config=config,
            model_name=model_name,
        )
    except Exception as exc:
        logger.exception("Agent-generation analysis call failed: %s", exc)
        raise HTTPException(status_code=502, detail="The analysis model could not be reached. Try again, or pick a different model.")

    await _record_usage(result.model_name, result.usage)

    try:
        # A revision keeps the draft's own name: it is already in the form the
        # user is editing, and uniquifying it again would rename the agent out
        # from under them on every refine.
        existing_names = [] if revise_from is not None else [agent.name for agent in existing]
        analysis = parse_analysis(result.text, existing_names=existing_names, require_proposal=force_proposal)
    except AgentAnalysisError as exc:
        logger.warning("Agent-generation analysis returned an unusable reply: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    proposal = None
    if analysis.proposes_agent and analysis.proposal is not None:
        proposal = ProposalResponse(
            name=analysis.proposal.name,
            description=analysis.proposal.description,
            soul=analysis.proposal.soul,
            skills=analysis.proposal.skills,
        )

    return AnalyzeResponse(
        verdict=analysis.verdict,
        rationale=analysis.rationale,
        covered_by=analysis.covered_by,
        proposal=proposal,
        analyzed_sources=len(transcripts),
        model_name=result.model_name,
        forced=force_proposal,
    )
