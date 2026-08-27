"""Local image and video generation tools, backed by a ComfyUI service.

These run in the **Gateway process** and write straight to the host-side thread
outputs directory. That is deliberate: the agent's own sandbox may be a remote
container, a local container, or the host, and only the Gateway sees the same
filesystem the artifact panel serves. It also keeps the GPU arbiter — which is
process-wide — on the same side of the wall as the code that generates.

Every generation is ``acquire → generate → release`` (see :mod:`.arbiter`).
Even when the policy resolves to ``none`` the lifecycle still runs, so nothing
has to be retrofitted the day the card gains a second tenant.

The loop that makes these results good lives in the ``image-refine`` skill, not
here: the agent generates, looks, judges against criteria frozen up front, and
changes one thing. This module only holds the parts a model cannot be trusted
with — the iteration counter, the wall-clock budget, and the rubric.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.tools.types import Runtime

from .arbiter import GpuArbiter, GpuBusyError
from .client import ComfyUIError
from .frames import build_contact_sheet, select_indices
from .service import (
    MediaToolError,
    available_models,
    build_client,
    media_config,
    resolve_enum_choice,
    timestamped_stem,
    validated_template,
    write_output,
)
from .sessions import (
    RefineError,
    begin_iteration,
    create_session,
    load_session,
    record_generation,
    record_verdict,
    save_session,
    summarize,
)

logger = logging.getLogger(__name__)

_MAX_SEED = 2**32 - 1


def _error(message: str, tool_call_id: str) -> Command:
    return Command(update={"messages": [ToolMessage(f"Error: {message}", tool_call_id=tool_call_id)]})


def _result(payload: dict[str, Any], tool_call_id: str, *, artifacts: list[str] | None = None) -> Command:
    update: dict[str, Any] = {"messages": [ToolMessage(json.dumps(payload, indent=2, ensure_ascii=False), tool_call_id=tool_call_id)]}
    if artifacts:
        update["artifacts"] = artifacts
    return Command(update=update)


def _outputs_dir(runtime: Runtime) -> Path:
    if runtime.state is None:
        raise MediaToolError("Thread runtime state is not available")
    thread_data = runtime.state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        raise MediaToolError("Thread outputs path is not available")
    return Path(outputs_path)


def _seed(requested: int | None) -> int:
    if requested is not None:
        return int(requested) % (_MAX_SEED + 1)
    return random.randint(0, _MAX_SEED)  # noqa: S311 - a generation seed, not a secret


@tool("list_media_models", parse_docstring=True)
async def list_media_models_tool() -> str:
    """List the image/video models this machine's ComfyUI actually has installed.

    Use this before generating when the user names a style or model, or when a
    generation failed because a model was not found. The lists come from the
    running ComfyUI itself, so they are what can actually be loaded right now —
    checkpoints for images, unets/clips/vaes for video, plus the samplers and
    schedulers the build offers.
    """
    try:
        client = build_client()
        object_info = await client.object_info()
    except (MediaToolError, ComfyUIError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    config = media_config()
    payload = {
        "base_url": client.base_url,
        "default_checkpoint": config.default_checkpoint,
        "image_template": config.image.template,
        "video_template": config.video.template,
        "models": available_models(object_info),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


@tool("generate_image", parse_docstring=True)
async def generate_image_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    prompt: str,
    negative_prompt: str | None = None,
    checkpoint: str | None = None,
    seed: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    width: int | None = None,
    height: int | None = None,
    filename: str | None = None,
    session_id: str | None = None,
) -> Command:
    """Generate an image on this machine's GPU with ComfyUI. No API key, nothing leaves the house.

    The PNG is written to `/mnt/user-data/outputs` and opens in the artifact
    panel on its own — there is no need to call present_files for it. The exact
    graph that produced it is saved beside it as `<name>.workflow.json`, so the
    result can be reproduced by hand in ComfyUI.

    Hold the seed when you change wording or weights, so the difference is
    attributable to the change; only draw a new seed when the composition
    itself is unlucky.

    Args:
        prompt: What to draw. Be specific about subject, composition, lighting and style — diffusion models reward detail.
        negative_prompt: What to keep out of the image (artifacts, extra limbs, text). Optional.
        checkpoint: Model file to load. Omit to use the configured default; call list_media_models to see what is installed.
        seed: Sampling seed. Omit for a fresh random draw; pass the previous seed to change one thing at a time.
        steps: Sampler steps. Higher is slower and not always better. Omit for the configured default.
        cfg: Guidance scale — how strictly the model follows the prompt. Omit for the configured default.
        width: Image width in pixels. Omit for the configured default.
        height: Image height in pixels. Omit for the configured default.
        filename: Descriptive base name for the output file. Omit to derive one from the prompt.
        session_id: Refine session from refine_start. Pass it to count this generation against the session's iteration cap.
    """
    try:
        outputs_dir = _outputs_dir(runtime)
        config = media_config()
        client = build_client(config)
        object_info = await client.object_info()
        template = await validated_template(client, config.image.template, object_info)
        resolved_checkpoint = resolve_enum_choice(
            template,
            object_info,
            param="checkpoint",
            requested=checkpoint,
            configured=config.default_checkpoint,
            label="checkpoint",
        )
    except (MediaToolError, ComfyUIError) as exc:
        return _error(str(exc), tool_call_id)

    session = None
    iteration = None
    if session_id:
        try:
            session = load_session(outputs_dir, session_id)
            iteration = begin_iteration(session)
            save_session(outputs_dir, session)
        except RefineError as exc:
            return _error(str(exc), tool_call_id)

    used_seed = _seed(seed)
    stem = timestamped_stem(filename or prompt, fallback="image")
    params = {
        "prompt": prompt,
        "negative_prompt": negative_prompt if negative_prompt is not None else config.image.negative_prompt,
        "checkpoint": resolved_checkpoint,
        "seed": used_seed,
        "steps": steps if steps is not None else config.image.steps,
        "cfg": cfg if cfg is not None else config.image.cfg,
        "sampler": config.image.sampler,
        "scheduler": config.image.scheduler,
        "width": width if width is not None else config.image.width,
        "height": height if height is not None else config.image.height,
        "filename_prefix": stem,
    }

    try:
        graph = _patch(template, params)
        arbiter = GpuArbiter.from_config(config.gpu, comfyui_client=client)
        async with arbiter.acquire("comfyui") as outcome:
            result = await client.run(graph, timeout=config.comfyui.image_timeout)
            images = result.images()
            if not images:
                raise MediaToolError("ComfyUI produced no image; check the template's SaveImage node")
            content = await client.download(images[0])
    except GpuBusyError as exc:
        return _error(str(exc), tool_call_id)
    except (MediaToolError, ComfyUIError) as exc:
        if session is not None and iteration is not None:
            record_generation(session, iteration.index, params=params, seed=used_seed, filename=None)
            save_session(outputs_dir, session)
        return _error(str(exc), tool_call_id)

    suffix = Path(images[0].filename).suffix or ".png"
    written = write_output(outputs_dir, f"{stem}{suffix}", content)
    workflow = write_output(outputs_dir, f"{stem}.workflow.json", json.dumps(graph, indent=2).encode("utf-8"))

    payload: dict[str, Any] = {
        "image": written.virtual_path,
        "workflow": workflow.virtual_path,
        "seed": used_seed,
        "checkpoint": resolved_checkpoint,
        "steps": params["steps"],
        "cfg": params["cfg"],
        "size": f"{params['width']}x{params['height']}",
        "seconds": round(result.duration_seconds, 1),
        "gpu": outcome.summary(),
        "next": "Call view_image on this path to judge it before answering.",
    }
    if session is not None and iteration is not None:
        record_generation(session, iteration.index, params=params, seed=used_seed, filename=written.virtual_path)
        save_session(outputs_dir, session)
        payload["session"] = summarize(session)
    return _result(payload, tool_call_id, artifacts=[written.virtual_path])


@tool("generate_video", parse_docstring=True)
async def generate_video_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    prompt: str,
    negative_prompt: str | None = None,
    seed: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    width: int | None = None,
    height: int | None = None,
    frames: int | None = None,
    fps: int | None = None,
    filename: str | None = None,
    session_id: str | None = None,
) -> Command:
    """Generate a short video clip on this machine's GPU with ComfyUI. Minutes per clip, no API key.

    The clip is written to `/mnt/user-data/outputs` and plays in the artifact
    panel. Because no model can watch an MP4, the tool also writes evenly
    spaced stills and a single **contact sheet** PNG: call view_image on the
    contact sheet to judge motion — flicker, morphing and identity drift read
    far more clearly side by side than frame by frame.

    Expect this to take minutes. Prefer a short clip and iterate on the prompt
    rather than asking for length.

    Args:
        prompt: What should happen in the clip. Describe the subject, the motion, and the camera.
        negative_prompt: What to keep out of the clip. Optional.
        seed: Sampling seed. Hold it across prompt edits so the difference is attributable.
        steps: Sampler steps. Omit for the configured default.
        cfg: Guidance scale. Omit for the configured default.
        width: Clip width in pixels. Omit for the configured default (sized for a consumer GPU).
        height: Clip height in pixels. Omit for the configured default.
        frames: Number of frames to generate. Omit for the configured default; more frames means more minutes and more VRAM.
        fps: Frames per second of the assembled clip. Omit for the configured default.
        filename: Descriptive base name for the output files. Omit to derive one from the prompt.
        session_id: Refine session from refine_start. Pass it to count this generation against the session's iteration cap.
    """
    try:
        outputs_dir = _outputs_dir(runtime)
        config = media_config()
        client = build_client(config)
        object_info = await client.object_info()
        template = await validated_template(client, config.video.template, object_info)
        resolved = {
            "unet": resolve_enum_choice(template, object_info, param="unet", requested=None, configured=config.video.unet, label="video diffusion model"),
            "clip": resolve_enum_choice(template, object_info, param="clip", requested=None, configured=config.video.clip, label="text encoder"),
            "vae": resolve_enum_choice(template, object_info, param="vae", requested=None, configured=config.video.vae, label="VAE"),
        }
    except (MediaToolError, ComfyUIError) as exc:
        return _error(str(exc), tool_call_id)

    session = None
    iteration = None
    if session_id:
        try:
            session = load_session(outputs_dir, session_id)
            iteration = begin_iteration(session)
            save_session(outputs_dir, session)
        except RefineError as exc:
            return _error(str(exc), tool_call_id)

    used_seed = _seed(seed)
    stem = timestamped_stem(filename or prompt, fallback="video")
    params = {
        "prompt": prompt,
        "negative_prompt": negative_prompt if negative_prompt is not None else "",
        "seed": used_seed,
        "steps": steps if steps is not None else config.video.steps,
        "cfg": cfg if cfg is not None else config.video.cfg,
        "width": width if width is not None else config.video.width,
        "height": height if height is not None else config.video.height,
        "frames": frames if frames is not None else config.video.frames,
        "fps": fps if fps is not None else config.video.fps,
        "filename_prefix": stem,
        "frames_filename_prefix": f"{stem}-frame",
        **resolved,
    }

    try:
        graph = _patch(template, params)
        arbiter = GpuArbiter.from_config(config.gpu, comfyui_client=client)
        async with arbiter.acquire("comfyui") as outcome:
            # Its own timeout, not sandbox.bash_command_timeout and not the
            # image budget: a clip is minutes, and inheriting a default here is
            # how a working generation gets abandoned at 60 seconds.
            result = await client.run(graph, timeout=config.comfyui.video_timeout)
            animations = result.animations()
            if not animations:
                raise MediaToolError("ComfyUI produced no video file; check the template's SaveVideo node")
            clip_bytes = await client.download(animations[0])
            still_sources = result.images()
            chosen = select_indices(len(still_sources), config.video.contact_sheet_stills)
            still_bytes = [await client.download(still_sources[index]) for index in chosen]
    except GpuBusyError as exc:
        return _error(str(exc), tool_call_id)
    except (MediaToolError, ComfyUIError) as exc:
        if session is not None and iteration is not None:
            record_generation(session, iteration.index, params=params, seed=used_seed, filename=None)
            save_session(outputs_dir, session)
        return _error(str(exc), tool_call_id)

    suffix = Path(animations[0].filename).suffix or ".mp4"
    clip = write_output(outputs_dir, f"{stem}{suffix}", clip_bytes)
    workflow = write_output(outputs_dir, f"{stem}.workflow.json", json.dumps(graph, indent=2).encode("utf-8"))

    still_paths: list[str] = []
    for position, index in enumerate(chosen, start=1):
        still = write_output(outputs_dir, f"frame-{position:02d}.png", still_bytes[position - 1], subdir=f"{stem}-stills")
        still_paths.append(still.virtual_path)

    payload: dict[str, Any] = {
        "video": clip.virtual_path,
        "workflow": workflow.virtual_path,
        "stills": still_paths,
        "seed": used_seed,
        "frames": params["frames"],
        "fps": params["fps"],
        "size": f"{params['width']}x{params['height']}",
        "seconds": round(result.duration_seconds, 1),
        "gpu": outcome.summary(),
    }

    artifacts = [clip.virtual_path]
    if still_bytes:
        try:
            sheet_bytes = build_contact_sheet(
                still_bytes,
                columns=config.video.contact_sheet_columns,
                tile_width=config.video.contact_sheet_tile_width,
                labels=[f"frame {index + 1}/{len(still_sources)}" for index in chosen],
            )
        except Exception as exc:
            # A corrupt frame, a missing Pillow, an odd colour mode — none of
            # them are worth throwing away a clip that took minutes to render.
            payload["contact_sheet_error"] = f"{type(exc).__name__}: {exc}"
        else:
            sheet = write_output(outputs_dir, f"{stem}.contact-sheet.png", sheet_bytes)
            payload["contact_sheet"] = sheet.virtual_path
            payload["next"] = "Call view_image on the contact sheet (not the mp4 — view_image cannot read video) to judge motion."
            artifacts.append(sheet.virtual_path)

    if session is not None and iteration is not None:
        record_generation(session, iteration.index, params=params, seed=used_seed, filename=clip.virtual_path)
        save_session(outputs_dir, session)
        payload["session"] = summarize(session)
    return _result(payload, tool_call_id, artifacts=artifacts)


@tool("refine_start", parse_docstring=True)
async def refine_start_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    goal: str,
    criteria: list[str],
    kind: str = "image",
    max_iterations: int | None = None,
) -> Command:
    """Freeze the criteria for a generate → judge → adjust loop, before the first attempt.

    Derive 3–6 *checkable* criteria from the request and pass them here. They
    are frozen: every iteration is judged against this exact list, which is
    what makes the loop converge instead of drifting with each look.

    The returned session_id counts iterations on the server. Pass it to
    generate_image / generate_video, and report the verdict of each attempt
    with refine_verdict. When the cap or the time budget is reached the next
    generation is refused — report the best result so far rather than starting
    a second session to get around it.

    Args:
        goal: What a good result would be, in one sentence — the user's request in your own words.
        criteria: 3–6 short, checkable statements ("the cat is orange", "no text anywhere in frame"). Vague ones ("looks nice") cannot be judged.
        kind: "image" or "video".
        max_iterations: Optional lower cap than the configured maximum. Cannot raise it.
    """
    try:
        outputs_dir = _outputs_dir(runtime)
        config = media_config()
        session = create_session(
            outputs_dir,
            goal=goal,
            criteria=list(criteria or []),
            kind="video" if str(kind).lower().startswith("v") else "image",
            config=config.refine,
            max_iterations=max_iterations,
        )
    except (MediaToolError, RefineError) as exc:
        return _error(str(exc), tool_call_id)
    payload = summarize(session)
    payload["budget_seconds"] = session.budget_seconds
    payload["next"] = "Generate with this session_id, view the result, then call refine_verdict with one named change if it is not there yet."
    return _result(payload, tool_call_id)


@tool("refine_verdict", parse_docstring=True)
async def refine_verdict_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    session_id: str,
    iteration: int,
    criteria_results: list[dict],
    overall: str,
    change: str | None = None,
) -> Command:
    """Record a structured judgement of one generated result against the frozen criteria.

    Judge from what you actually looked at (view_image on the image, or on the
    contact sheet for a clip). Every frozen criterion needs a pass/fail and a
    short note. A "retry" must name **exactly one** change to make next — one
    change per iteration is what makes the loop diagnosable.

    Only look at the newest result each round: carry the earlier verdicts
    forward in writing instead of re-viewing every image, which bills full
    vision tokens again on every iteration.

    Args:
        session_id: The refine session from refine_start.
        iteration: Which iteration this verdict is about (the generate tool reports it).
        criteria_results: One entry per frozen criterion: {"criterion": "...", "passed": true/false, "note": "what you saw"}.
        overall: "accept" (good enough), "retry" (change one thing), or "abandon" (this cannot get there — say why in the notes).
        change: For "retry" only: the single change to make next, e.g. "raise cfg to 8" or "add 'studio lighting' to the prompt".
    """
    try:
        outputs_dir = _outputs_dir(runtime)
        session = load_session(outputs_dir, session_id)
        verdict = record_verdict(
            session,
            int(iteration),
            criteria_results=list(criteria_results or []),
            overall=str(overall).strip().lower(),
            change=change,
        )
        save_session(outputs_dir, session)
    except (MediaToolError, RefineError) as exc:
        return _error(str(exc), tool_call_id)
    payload = summarize(session)
    payload["verdict"] = verdict
    if session.closed:
        payload["next"] = "Session closed. Present the accepted result (or explain why it was abandoned)."
    elif session.remaining_iterations:
        payload["next"] = f"Generate again with session_id={session.session_id}, applying exactly the named change. {session.remaining_iterations} iteration(s) left."
    else:
        payload["next"] = "No iterations left. Report the best result so far and what the failing criteria would need."
    return _result(payload, tool_call_id)


def _patch(template: Any, params: dict[str, Any]) -> dict[str, Any]:
    from .templates import TemplateError, patch_graph

    try:
        return patch_graph(template, params)
    except TemplateError as exc:
        raise MediaToolError(str(exc)) from exc
