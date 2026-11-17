"""HTTP API for the sidebar's chat clean-up pass (fork feature).

The user picks some conversations (or all of them) and a model; the model
suggests a better title for each, and a folder: one of the folders the user
offered, or a free category that a second call merges into a few folders. Both
routes here are **read-only**. They return suggestions, the client shows them as
a preview, and what the user approves is applied through the ordinary routes:
``PUT /api/settings/chat-folders`` for new folders, ``PATCH /api/threads/{id}``
for placement (which leaves the sidebar's recency order alone) and
``POST /api/threads/{id}/state`` for the rename. Writing here would put the
"409 while a run is in flight" rule and the folder-registry rules in a second
place.

Both calls spend model tokens on the user's behalf, so they pass the same gates
a run does, in this order: the model must be in the operator's catalog (400),
the caller's role must be allowed to use it (403, checked before any
conversation text is read), and the spend cap must not be exhausted (402, the
run-admission check). The model call has a time limit (504) and its usage is
billed to the real conversations under the ``organize`` aux category *before*
the reply is parsed: an unusable reply (502) was paid for too.

The pure parts -- digests, prompts, parsing, the deterministic merge and the
folder cap -- live in ``deerflow.utils.chat_organize``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import _is_internal_caller, authorize_model_use, require_permission
from app.gateway.deps import get_config, get_current_user_from_request, get_thread_store
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.services import build_thread_checkpoint_state_accessor
from app.gateway.spend_budget import exhausted_message, resolve_run_spend_budget
from app.gateway.utils import sanitize_log_param
from deerflow.config.app_config import AppConfig
from deerflow.runtime.aux_usage import AUX_CATEGORY_ORGANIZE, arecord_aux_usage_metadata
from deerflow.runtime.checkpoint_mode import CheckpointModeMismatchError, CheckpointModeReconfigurationError
from deerflow.utils import chat_organize as organize
from deerflow.utils.oneshot_llm import OneshotResult, run_oneshot_llm_with_usage
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat-organize"])

_CHECKPOINT_MODE_ERRORS = (CheckpointModeMismatchError, CheckpointModeReconfigurationError)


class FolderChoiceInput(BaseModel):
    """A folder by its registry id and display name."""

    id: str = Field(..., min_length=1, max_length=128, description="Folder id from GET /api/settings/chat-folders")
    name: str = Field(..., min_length=1, max_length=200, description="Folder display name (normalized to the registry's 80 characters)")


class OrganizeSuggestRequest(BaseModel):
    # Bounded because the name is echoed back in the 400; an unbounded string
    # would let a client choose the size of its own error response.
    model_name: str | None = Field(default=None, max_length=200, description="Model that describes the conversation. None uses config.yaml -> title.model_name, then the default model.")
    rename: bool = Field(default=True, description="Suggest a better title. Forced off when config.yaml -> title.enabled is false.")
    mode: Literal["none", "targets", "auto"] = Field(..., description="none: title only. targets: pick one of `targets`. auto: a free category (merge them with POST /api/chat-organize/consolidate).")
    targets: list[FolderChoiceInput] | None = Field(default=None, max_length=organize.MAX_ORGANIZE_TARGETS, description="Folders to choose from (targets mode).")
    existing: list[FolderChoiceInput] | None = Field(default=None, max_length=organize.MAX_ORGANIZE_TARGETS, description="The user's folders, offered for reuse (auto mode).")


class OrganizeSuggestResponse(BaseModel):
    thread_id: str
    current_title: str | None = Field(default=None, description="The conversation's title when it was read.")
    title: str | None = Field(default=None, description="Suggested title; equals current_title when the model kept it. The caller applies it.")
    title_changed: bool = Field(default=False, description="Whether `title` differs from the current title (ignoring case and spacing).")
    rename_disabled: bool = Field(default=False, description="The operator turned conversation renaming off (title.enabled: false).")
    target_id: str | None = Field(default=None, description="The chosen folder's id (targets mode), or null when none fits.")
    category: str | None = Field(default=None, description="Free category (auto mode).")
    summary: str | None = Field(default=None, description="One-sentence summary (auto mode), for consolidation.")
    model_name: str | None = Field(default=None, description="Model that served the call, as reported by the provider.")


class ConsolidateItemInput(BaseModel):
    thread_id: ThreadId
    category: str = Field(..., max_length=200, description="The category the suggest call returned; empty leaves the conversation unfiled.")
    title: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=1000)


class ConsolidateRequest(BaseModel):
    model_name: str | None = Field(default=None, max_length=200, description="Model that merges the categories. None uses config.yaml -> title.model_name, then the default model.")
    items: list[ConsolidateItemInput] = Field(..., min_length=1, max_length=organize.MAX_CONSOLIDATE_ITEMS)
    existing: list[FolderChoiceInput] = Field(default_factory=list, max_length=organize.MAX_ORGANIZE_TARGETS, description="The user's folders; a category matching one files into it.")
    max_new_folders: int = Field(default=organize.DEFAULT_MAX_NEW_FOLDERS, ge=1, le=organize.MAX_NEW_FOLDERS_LIMIT)
    min_group_size: int = Field(default=organize.DEFAULT_MIN_GROUP_SIZE, ge=1, le=organize.MAX_CONSOLIDATE_ITEMS, description="Conversations a NEW folder needs; smaller groups stay unfiled.")


class PlannedFolderResponse(BaseModel):
    name: str
    existing_folder_id: str | None = Field(default=None, description="Set when the folder already exists; null means create it.")
    thread_ids: list[str]


class ConsolidateResponse(BaseModel):
    folders: list[PlannedFolderResponse]
    unfiled: list[str]
    model_name: str | None = Field(default=None, description="Model that served the merge; null when no model call was needed.")


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _resolve_model_name(config: AppConfig, requested: str | None) -> str | None:
    """The model to call: the caller's pick, checked against the catalog, else the title model.

    The name arrives from a browser and picks what spends money, so an unknown
    one is refused (400) rather than quietly swapped for another model -- the
    same rule as the manual rename (FORK.md §38).
    """
    name = requested.strip() if isinstance(requested, str) else ""
    if name:
        configured = {model_name for model_name in (getattr(model, "name", "") for model in (getattr(config, "models", None) or [])) if model_name}
        if configured and name not in configured:
            raise HTTPException(status_code=400, detail=f"Model {name} is not configured")
        return name
    return config.title.model_name


async def _authorize_model(request: Request, config: AppConfig, model_name: str | None) -> Any:
    """``model:use`` for the effective model, before any conversation text is read."""
    user = await get_current_user_from_request(request)
    await asyncio.to_thread(authorize_model_use, user, model_name, is_internal=_is_internal_caller(request, user), app_config=config)
    return user


async def _require_spend_room(request: Request, config: AppConfig) -> None:
    """The run-admission spend check: one number, one rule (FORK.md §10)."""
    status = await resolve_run_spend_budget(request, owner_user_id=get_trusted_internal_owner_user_id(request), app_config=config)
    exceeded = status.exceeded
    if exceeded is not None:
        raise HTTPException(status_code=402, detail=exhausted_message(exceeded, status.currency))


async def _read_thread_state(request: Request, thread_id: str) -> Any:
    try:
        accessor, state_config = await build_thread_checkpoint_state_accessor(request, thread_id=thread_id)
        snapshot = await accessor.aget(state_config)
    except _CHECKPOINT_MODE_ERRORS as exc:
        if isinstance(exc, CheckpointModeMismatchError):
            raise HTTPException(status_code=409, detail=f"Thread {thread_id}: {exc}") from exc
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        logger.exception("Failed to read state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to read thread state") from None
    if snapshot is None or not (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return snapshot


async def _call_model(*, system: str, user_content: str, run_name: str, config: AppConfig, model_name: str | None, thread_id: str | None) -> OneshotResult:
    try:
        async with asyncio.timeout(organize.ORGANIZE_TIMEOUT_SECONDS):
            return await run_oneshot_llm_with_usage(
                system_instruction=system,
                user_content=user_content,
                run_name=run_name,
                app_config=config,
                model_name=model_name,
                thread_id=thread_id,
            )
    except TimeoutError:
        logger.warning("Chat organize call %s timed out after %ss", run_name, organize.ORGANIZE_TIMEOUT_SECONDS)
        raise _error(504, "timeout", "The model did not answer in time. Try again, or pick a faster model.") from None
    except Exception:
        logger.exception("Chat organize call %s failed", run_name)
        raise _error(502, "model_failed", "The model could not be reached. Try again, or pick a different model.") from None


async def _require_owned_threads(request: Request, user: Any, thread_ids: list[str]) -> None:
    """Every conversation in the body belongs to the caller, or the whole call is a 404.

    ``owner_check`` only sees a ``thread_id`` path parameter, so a list in the
    body is checked here, strictly (``require_existing``): the call is billed to
    these conversations and names them back in its plan.
    """
    thread_store = get_thread_store(request)
    owner_id = get_trusted_internal_owner_user_id(request) or str(getattr(user, "id", "") or "")
    for thread_id in thread_ids:
        if not owner_id or not await thread_store.check_access(thread_id, owner_id, require_existing=True):
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")


@router.post(
    "/threads/{thread_id}/organize/suggest",
    response_model=OrganizeSuggestResponse,
    summary="Suggest A Title And Folder For A Conversation",
    description="Read one conversation and suggest a title and a folder for the chat clean-up pass. Read-only: nothing is written.",
)
# ``runs:create`` like the manual rename: it reads what the caller can already
# read, but spends a model call doing it. ``owner_check`` scopes it to the
# caller's own conversation.
@require_permission("runs", "create", owner_check=True)
async def suggest_thread_organization(
    thread_id: ThreadId,
    body: OrganizeSuggestRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> OrganizeSuggestResponse:
    rename_disabled = not config.title.enabled
    # The operator's switch covers this pass too: title.enabled: false is how an
    # operator stops paying for names. Filing still works without it.
    rename = body.rename and not rename_disabled
    targets = organize.normalize_folder_choices(body.targets or [])
    existing = organize.normalize_folder_choices(body.existing or [])
    if body.mode == "targets" and not targets:
        raise _error(422, "no_targets", "Pick at least one folder to file into.")
    if body.mode == "none" and not rename:
        # Nothing left to ask a model: answer without reading or spending.
        return OrganizeSuggestResponse(thread_id=thread_id, rename_disabled=rename_disabled)

    model_name = _resolve_model_name(config, body.model_name)
    await _authorize_model(request, config, model_name)
    await _require_spend_room(request, config)

    snapshot = await _read_thread_state(request, thread_id)
    values = snapshot.values or {}
    raw_title = values.get("title")
    current_title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None
    summary_text = values.get("summary_text")
    budget = organize.resolve_organize_budget(config, model_name)
    # Off the loop: redaction is a regex pass over every kept message.
    digest = await asyncio.to_thread(
        organize.build_conversation_digest,
        values.get("messages"),
        summary_text=summary_text if isinstance(summary_text, str) else None,
        current_title=current_title,
        pii_redaction=getattr(config, "pii_redaction", None),
        max_chars=organize.digest_char_budget(budget),
    )
    if not digest.has_content:
        raise _error(409, "empty", "This conversation has nothing to organize yet.")

    try:
        system, user_content = organize.build_suggest_messages(
            digest,
            mode=body.mode,
            rename=rename,
            max_words=config.title.max_words,
            targets=targets,
            existing=existing,
            budget=budget,
        )
    except organize.OrganizePromptTooLargeError:
        raise _error(422, "too_many_for_model", "The folder list does not fit this model's context window. Offer fewer folders or pick a larger model.") from None

    result = await _call_model(system=system, user_content=user_content, run_name=organize.SUGGEST_RUN_NAME, config=config, model_name=model_name, thread_id=thread_id)
    # Billed to the conversation it describes, before parsing: an unusable
    # reply was paid for too, and an unbilled call makes the chat header
    # understate what the conversation cost.
    await arecord_aux_usage_metadata(thread_id, AUX_CATEGORY_ORGANIZE, model_name=result.model_name, usage=result.usage)

    try:
        parsed = organize.parse_suggest_reply(result.text, mode=body.mode, rename=rename, targets=targets, max_title_chars=config.title.max_chars)
    except organize.OrganizeReplyError:
        logger.warning("Chat organize: unusable reply for thread %s", sanitize_log_param(thread_id))
        raise _error(502, "unusable_reply", "The model's answer could not be used. Try again, or pick a different model.") from None

    title: str | None = None
    title_changed = False
    if rename and parsed.title:
        if organize.title_is_unchanged(parsed.title, current_title=current_title, prompt_title=digest.prompt_title):
            title = current_title or parsed.title
        else:
            title, title_changed = parsed.title, True

    return OrganizeSuggestResponse(
        thread_id=thread_id,
        current_title=current_title,
        title=title,
        title_changed=title_changed,
        rename_disabled=rename_disabled,
        target_id=targets[parsed.target_index - 1].id if parsed.target_index is not None else None,
        category=parsed.category,
        summary=parsed.summary,
        model_name=result.model_name,
    )


@router.post(
    "/chat-organize/consolidate",
    response_model=ConsolidateResponse,
    summary="Merge Conversation Categories Into Folders",
    description="Merge the free categories the suggest call returned into a few folders, matching the user's existing ones. Read-only: nothing is written.",
)
@require_permission("runs", "create")
async def consolidate_chat_categories(
    body: ConsolidateRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> ConsolidateResponse:
    model_name = _resolve_model_name(config, body.model_name)
    user = await _authorize_model(request, config, model_name)

    items: list[organize.ConsolidationItem] = []
    seen: set[str] = set()
    for item in body.items:
        if item.thread_id in seen:
            continue
        seen.add(item.thread_id)
        items.append(organize.ConsolidationItem(thread_id=item.thread_id, category=item.category, title=item.title, summary=item.summary))
    order = [item.thread_id for item in items]
    await _require_owned_threads(request, user, order)

    existing = organize.normalize_folder_choices(body.existing)
    # The registry's room is counted from every folder the client sent, not the
    # normalized list: a name like "???" normalizes to nothing and drops out of
    # matching, but it still holds one of the registry's slots.
    existing_count = len({choice.id for choice in body.existing})
    groups, unfiled = organize.group_categories(items, existing)
    matched = [group for group in groups if group.existing_id is not None]
    unmatched = [group for group in groups if group.existing_id is None]
    served_by: str | None = None

    # Deterministic first: the same category spelled differently, or equal to
    # an existing folder's name, needs no model. Only labels still apart after
    # that are worth a call.
    if organize.needs_model_merge(groups):
        cap = organize.new_folder_cap(existing_count=existing_count, max_new_folders=body.max_new_folders)
        try:
            prompt = organize.build_consolidate_messages(
                unmatched,
                existing,
                new_folder_cap=cap,
                pii_redaction=getattr(config, "pii_redaction", None),
                budget=organize.resolve_organize_budget(config, model_name),
            )
        except organize.OrganizePromptTooLargeError:
            raise _error(422, "too_many_for_model", "Too many categories for this model's context window. Select fewer conversations or pick a larger model.") from None
        await _require_spend_room(request, config)
        result = await _call_model(system=prompt.system, user_content=prompt.user, run_name=organize.CONSOLIDATE_RUN_NAME, config=config, model_name=model_name, thread_id=None)
        # One call served every conversation whose label it merged: split the
        # bill across them. A synthetic thread id would drop out of the
        # per-user spend cap, which counts only the owner's real threads.
        billed = [thread_id for group in unmatched for thread_id in group.thread_ids]
        try:
            await asyncio.to_thread(organize.record_split_aux_usage, billed, AUX_CATEGORY_ORGANIZE, model_name=result.model_name, usage=result.usage)
        except Exception:  # pragma: no cover - defensive: accounting must not break the feature
            logger.debug("failed to record chat organize consolidation usage", exc_info=True)

        merges = organize.parse_consolidate_reply(result.text, label_count=len(unmatched))
        if not merges:
            # Not an error: the deterministic grouping is still a valid plan.
            logger.info("Chat organize: consolidation reply merged nothing; keeping the deterministic grouping")
        unmatched = organize.apply_model_merges(unmatched, merges, existing, prompt_labels=prompt.prompt_labels)
        served_by = result.model_name

    plan = organize.finalize_plan(
        [*matched, *unmatched],
        unfiled=unfiled,
        existing_count=existing_count,
        max_new_folders=body.max_new_folders,
        min_group_size=body.min_group_size,
        order=order,
    )
    return ConsolidateResponse(
        folders=[PlannedFolderResponse(name=folder.name, existing_folder_id=folder.existing_folder_id, thread_ids=folder.thread_ids) for folder in plan.folders],
        unfiled=plan.unfiled,
        model_name=served_by,
    )
