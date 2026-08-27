"""Local video generation (fork feature, roadmap 15).

Video is not "image, but longer". Two constraints shape the whole feature and
both are pinned here:

* **No model can watch an MP4.** ``view_image`` takes png/jpg/webp/gif only, so
  a clip is judged from stills — and from *one contact sheet* rather than six
  separate images, because that is one vision-token bill instead of six and
  because flicker, morphing and identity drift read far more clearly side by
  side. The sheet must sample the whole clip, endpoints included: a sheet drawn
  from the middle hides exactly the fault the critic is looking for.
* **Minutes per clip.** The video budget is its own config value, not the image
  timeout and not ``sandbox.bash_command_timeout``; inheriting either is how a
  working generation gets abandoned at 60 seconds.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from _comfyui_helpers import PNG_1PX, FakeComfyUIClient, frame_outputs, object_info_for, runtime, video_output

from deerflow.community.comfyui import service, tools
from deerflow.community.comfyui.frames import build_contact_sheet, select_indices
from deerflow.community.comfyui.templates import load_template
from deerflow.config.media_config import GpuArbiterConfig, MediaConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_ENUMS = {
    ("UNETLoader", "unet_name"): ["wan2.2-ti2v-5b.safetensors"],
    ("CLIPLoader", "clip_name"): ["umt5-xxl.safetensors"],
    ("VAELoader", "vae_name"): ["wan2.2-vae.safetensors"],
}


def _media_config(**overrides) -> MediaConfig:
    return MediaConfig(gpu=GpuArbiterConfig(tenants=[]), **overrides)


def _video_client(frames: int = 12, *, animations=True):
    template = load_template("txt2video")
    info = object_info_for(template, VIDEO_ENUMS)
    outputs = frame_outputs(frames) + ([video_output()] if animations else [])
    content = {output.filename: PNG_1PX for output in outputs}
    content["deerflow_00001.mp4"] = b"\x00\x00\x00\x18ftypmp42fake-clip"
    return FakeComfyUIClient(info, outputs=outputs, content=content)


class TestStillSelection:
    def test_indices_span_the_whole_clip_including_both_endpoints(self):
        chosen = select_indices(49, 6)
        assert chosen[0] == 0
        assert chosen[-1] == 48
        assert len(chosen) == 6

    def test_gaps_are_even(self):
        chosen = select_indices(100, 5)
        gaps = {chosen[index + 1] - chosen[index] for index in range(len(chosen) - 1)}
        assert max(gaps) - min(gaps) <= 1, chosen

    def test_a_short_clip_returns_every_frame_rather_than_repeating_one(self):
        assert select_indices(3, 6) == [0, 1, 2]

    def test_no_frames_means_no_stills(self):
        assert select_indices(0, 6) == []


class TestContactSheet:
    def test_the_sheet_is_a_single_png_holding_every_still(self):
        pytest.importorskip("PIL")
        from PIL import Image

        sheet = build_contact_sheet([PNG_1PX] * 6, columns=3, tile_width=40)
        image = Image.open(io.BytesIO(sheet))
        assert image.format == "PNG"
        # 3 columns x 2 rows of 40px tiles, plus padding between and around.
        assert image.width == 3 * 40 + 4 * 8
        assert image.height >= 2

    def test_an_empty_frame_list_is_an_error_not_a_blank_sheet(self):
        with pytest.raises(ValueError, match="No frames"):
            build_contact_sheet([])


@pytest.mark.asyncio
class TestGenerateVideo:
    async def _generate(self, tmp_path: Path, client, config: MediaConfig | None = None, **kwargs):
        service.reset_validation_cache()
        cfg = config or _media_config()
        with patch.object(tools, "media_config", lambda: cfg), patch.object(tools, "build_client", lambda *a, **k: client):
            command = await tools.generate_video_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="v1", prompt="a cat jumping onto a windowsill", **kwargs)
        return command

    async def test_writes_the_clip_the_stills_and_one_contact_sheet(self, tmp_path: Path):
        pytest.importorskip("PIL")
        client = _video_client(frames=12)
        command = await self._generate(tmp_path, client)
        payload = json.loads(command.update["messages"][0].content)

        assert (tmp_path / Path(payload["video"]).name).is_file()
        assert (tmp_path / Path(payload["contact_sheet"]).name).is_file()
        assert len(payload["stills"]) == 6
        for still in payload["stills"]:
            assert (tmp_path / Path(still).parent.name / Path(still).name).is_file()

    async def test_the_clip_and_the_sheet_are_both_artifacts_but_the_sheet_is_what_gets_judged(self, tmp_path: Path):
        pytest.importorskip("PIL")
        client = _video_client()
        command = await self._generate(tmp_path, client)
        payload = json.loads(command.update["messages"][0].content)
        assert command.update["artifacts"] == [payload["video"], payload["contact_sheet"]]
        assert "contact sheet" in payload["next"]
        assert "view_image cannot read video" in payload["next"]

    async def test_the_sheet_samples_the_whole_clip(self, tmp_path: Path):
        pytest.importorskip("PIL")
        client = _video_client(frames=24)
        await self._generate(tmp_path, client)
        downloaded = [output.filename for output in client.downloads if output.kind == "image"]
        assert downloaded[0].endswith("00000_.png")
        assert downloaded[-1].endswith("00023_.png")

    async def test_video_uses_its_own_timeout_not_the_image_one(self, tmp_path: Path):
        client = _video_client()
        config = _media_config()
        config.comfyui.image_timeout = 30.0
        config.comfyui.video_timeout = 2400.0
        await self._generate(tmp_path, client, config=config)
        assert client.timeouts == [2400.0]

    async def test_the_submitted_graph_is_saved_beside_the_clip(self, tmp_path: Path):
        client = _video_client()
        command = await self._generate(tmp_path, client, seed=5)
        payload = json.loads(command.update["messages"][0].content)
        saved = json.loads((tmp_path / Path(payload["workflow"]).name).read_text())
        assert saved == client.submitted[0]
        assert saved["8"]["inputs"]["seed"] == 5

    async def test_frames_and_fps_reach_the_graph(self, tmp_path: Path):
        client = _video_client()
        await self._generate(tmp_path, client, frames=25, fps=12)
        graph = client.submitted[0]
        assert graph["6"]["inputs"]["length"] == 25
        assert graph["11"]["inputs"]["fps"] == 12

    async def test_video_models_resolve_from_object_info_when_config_names_none(self, tmp_path: Path):
        client = _video_client()
        await self._generate(tmp_path, client)
        graph = client.submitted[0]
        assert graph["1"]["inputs"]["unet_name"] == VIDEO_ENUMS[("UNETLoader", "unet_name")][0]
        assert graph["2"]["inputs"]["clip_name"] == VIDEO_ENUMS[("CLIPLoader", "clip_name")][0]
        assert graph["3"]["inputs"]["vae_name"] == VIDEO_ENUMS[("VAELoader", "vae_name")][0]

    async def test_a_run_that_produced_no_clip_is_an_error(self, tmp_path: Path):
        client = _video_client(animations=False)
        command = await self._generate(tmp_path, client)
        assert "no video file" in command.update["messages"][0].content

    async def test_a_missing_contact_sheet_still_delivers_the_clip(self, tmp_path: Path):
        """Pillow is an optional import; losing the sheet must not lose the clip."""
        client = _video_client()
        with patch.object(tools, "build_contact_sheet", side_effect=RuntimeError("Pillow is required")):
            command = await self._generate(tmp_path, client)
        payload = json.loads(command.update["messages"][0].content)
        assert (tmp_path / Path(payload["video"]).name).is_file()
        assert "Pillow" in payload["contact_sheet_error"]
        assert "contact_sheet" not in payload

    async def test_a_refine_session_counts_video_iterations_too(self, tmp_path: Path):
        pytest.importorskip("PIL")
        config = _media_config()
        config.refine.max_iterations = 1
        with patch.object(tools, "media_config", lambda: config):
            started = await tools.refine_start_tool.coroutine(
                runtime=runtime(str(tmp_path)), tool_call_id="t0", goal="a cat jumping", kind="video", criteria=["the cat lands on the sill", "no morphing between frames", "the camera holds still"]
            )
        session_id = json.loads(started.update["messages"][0].content)["session_id"]

        first = await self._generate(tmp_path, _video_client(), config=config, session_id=session_id)
        assert json.loads(first.update["messages"][0].content)["session"]["iterations_used"] == 1

        second = await self._generate(tmp_path, _video_client(), config=config, session_id=session_id)
        assert "used all 1 iterations" in second.update["messages"][0].content


class TestVideoTemplates:
    def test_the_default_template_stays_on_core_nodes(self):
        """A stock ComfyUI must be able to run the shipped default."""
        template = load_template("txt2video")
        classes = {node["class_type"] for node in template.graph.values()}
        assert "UnetLoaderGGUF" not in classes

    def test_the_gguf_variant_is_offered_and_says_what_it_needs(self):
        template = load_template("txt2video-gguf")
        classes = {node["class_type"] for node in template.graph.values()}
        assert "UnetLoaderGGUF" in classes
        assert "ComfyUI-GGUF" in template.description

    def test_the_video_template_saves_both_the_clip_and_the_frames(self):
        """The frames are what the contact sheet is tiled from."""
        for name in ("txt2video", "txt2video-gguf"):
            template = load_template(name)
            assert set(template.outputs) == {"video", "frames"}, name
            assert template.node_class(template.outputs["frames"]) == "SaveImage", name

    def test_the_config_comment_keeps_the_fp8_emulation_note_honest(self):
        text = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")
        assert "no FP8 tensor cores" in text
        assert "emulation" in text
