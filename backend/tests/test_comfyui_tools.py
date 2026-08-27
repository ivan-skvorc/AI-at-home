"""Local image generation through a ComfyUI service (fork feature, roadmap 12).

These pin the properties that fail *silently* if someone "simplifies" them:

* the model never authors graph JSON — it passes typed parameters, and an
  unbound parameter is an error rather than a silent no-op;
* a stale template fails naming the node that moved, instead of forwarding
  ComfyUI's validation dump;
* the checkpoint comes from ``/object_info``'s own enum, not a hardcoded name;
* the submitted graph is saved beside the image, so a result is reproducible
  by hand;
* the SSRF guard is *used* with its documented opt-out, not bypassed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from _comfyui_helpers import FakeComfyUIClient, image_output, object_info_for, runtime

from deerflow.community.comfyui import service, tools
from deerflow.community.comfyui.client import ComfyUIClient, _collect_outputs, _describe_rejection, _status_error, checkpoints_from_object_info, declared_inputs, enum_values
from deerflow.community.comfyui.templates import TemplateError, load_template, patch_graph, validate_template
from deerflow.config.media_config import GpuArbiterConfig, MediaConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINTS = ["dreamshaper_8.safetensors", "sdxl_base.safetensors"]


def _media_config(**overrides) -> MediaConfig:
    # No GPU tenants: the arbiter still runs its acquire/release lifecycle, so
    # these tests exercise the real path without needing an eviction fake.
    config = MediaConfig(gpu=GpuArbiterConfig(tenants=[]), **overrides)
    return config


def _image_setup(*, enums=None, outputs=None):
    template = load_template("txt2img")
    info = object_info_for(template, enums or {("CheckpointLoaderSimple", "ckpt_name"): CHECKPOINTS})
    client = FakeComfyUIClient(info, outputs=outputs if outputs is not None else [image_output()])
    return template, client


class TestTemplateContract:
    def test_bundled_templates_parse_and_bind_real_nodes(self):
        for name in ("txt2img", "txt2video", "txt2video-gguf"):
            template = load_template(name)
            for param, binding in template.bindings.items():
                assert binding.node in template.graph, f"{name}: '{param}' binds missing node {binding.node}"
                assert binding.input in (template.graph[binding.node].get("inputs") or {}), f"{name}: '{param}' binds unknown input"
            for label, node_id in template.outputs.items():
                assert node_id in template.graph, f"{name}: output '{label}' names missing node {node_id}"

    def test_patch_applies_typed_parameters_by_binding(self):
        template = load_template("txt2img")
        graph = patch_graph(template, {"prompt": "an orange cat", "seed": 42, "checkpoint": "x.safetensors"})
        assert graph["6"]["inputs"]["text"] == "an orange cat"
        assert graph["3"]["inputs"]["seed"] == 42
        assert graph["4"]["inputs"]["ckpt_name"] == "x.safetensors"

    def test_patch_does_not_mutate_the_cached_template(self):
        template = load_template("txt2img")
        patch_graph(template, {"prompt": "first"})
        graph = patch_graph(template, {"seed": 1})
        assert graph["6"]["inputs"]["text"] == "", "a patched graph leaked back into the template"

    def test_unset_parameters_keep_the_template_value(self):
        template = load_template("txt2img")
        graph = patch_graph(template, {"prompt": "a cat", "steps": None})
        assert graph["3"]["inputs"]["steps"] == template.graph["3"]["inputs"]["steps"]

    def test_unbound_parameter_is_refused_rather_than_ignored(self):
        template = load_template("txt2img")
        with pytest.raises(TemplateError, match="does not expose a 'lora' parameter"):
            patch_graph(template, {"lora": "anything"})

    def test_template_name_cannot_traverse_the_templates_directory(self):
        for bad in ("../../etc/passwd", "..", "sub/dir"):
            with pytest.raises(TemplateError):
                load_template(bad)


class TestTemplateValidation:
    def test_matching_build_reports_no_problems(self):
        template, _ = _image_setup()
        assert validate_template(template, object_info_for(template)) == []

    def test_missing_node_class_names_the_node(self):
        template = load_template("txt2img")
        info = object_info_for(template)
        info.pop("VAEDecode")
        problems = validate_template(template, info)
        assert any("node 8 (VAEDecode)" in problem for problem in problems), problems

    def test_renamed_input_names_the_node_and_the_input(self):
        template = load_template("txt2img")
        info = object_info_for(template)
        info["KSampler"]["input"]["required"].pop("cfg")
        problems = validate_template(template, info)
        assert any("node 3 (KSampler)" in problem and "'cfg'" in problem for problem in problems), problems

    @pytest.mark.asyncio
    async def test_generate_refuses_a_stale_template_naming_the_node(self):
        template, client = _image_setup()
        info = await client.object_info()
        info.pop("SaveImage")
        service.reset_validation_cache()
        with patch.object(tools, "media_config", _media_config), patch.object(tools, "build_client", lambda *a, **k: client):
            command = await tools.generate_image_tool.coroutine(runtime=runtime("/tmp/out"), tool_call_id="t1", prompt="a cat")
        message = command.update["messages"][0].content
        assert "node 9 (SaveImage)" in message
        assert not client.submitted, "a stale template must fail before anything is submitted"


class TestObjectInfoReading:
    def test_checkpoints_come_from_the_loader_enum(self):
        template = load_template("txt2img")
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): CHECKPOINTS})
        assert checkpoints_from_object_info(info) == CHECKPOINTS

    def test_non_enum_inputs_report_no_values(self):
        template = load_template("txt2img")
        assert enum_values(object_info_for(template), "CLIPTextEncode", "text") == []

    def test_declared_inputs_cover_required_and_optional(self):
        info = {"Node": {"input": {"required": {"a": ["STRING", {}]}, "optional": {"b": ["INT", {}]}}}}
        assert declared_inputs(info, "Node") == {"a", "b"}


class TestClientPlumbing:
    def test_outputs_are_flattened_with_kinds(self):
        entry = {
            "outputs": {
                "9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
                "12": {"gifs": [{"filename": "b.mp4", "subfolder": "", "type": "output"}]},
            }
        }
        collected = _collect_outputs(entry)
        assert [(output.filename, output.kind) for output in collected] == [("a.png", "image"), ("b.mp4", "animation")]

    def test_preview_outputs_are_not_returned_as_artifacts(self):
        entry = {"outputs": {"9": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]}}}
        assert _collect_outputs(entry) == []

    def test_execution_error_is_reported_as_a_sentence(self):
        entry = {"status": {"status_str": "error", "messages": [["execution_error", {"node_type": "KSampler", "exception_message": "OOM"}]]}}
        assert _status_error(entry) == "ComfyUI execution failed at node KSampler: OOM"

    def test_rejection_dump_is_condensed_to_the_offending_node(self):
        class _Response:
            status_code = 400
            text = "{}"

            @staticmethod
            def json():
                return {"node_errors": {"4": {"class_type": "CheckpointLoaderSimple", "errors": [{"message": "value not in list"}]}}}

        described = _describe_rejection(_Response())
        assert "node 4 (CheckpointLoaderSimple)" in described
        assert "value not in list" in described


class TestUrlGuard:
    def test_loopback_is_allowed_through_the_documented_opt_out(self):
        config = _media_config()
        assert config.comfyui.allow_private_addresses is True
        client = service.build_client(config)
        assert isinstance(client, ComfyUIClient)

    def test_loopback_is_refused_when_the_opt_out_is_turned_off(self):
        config = _media_config()
        config.comfyui.allow_private_addresses = False
        with pytest.raises(service.MediaToolError, match="private"):
            service.build_client(config)

    def test_env_var_overrides_the_configured_base_url(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_COMFYUI_BASE_URL", "http://comfyui:8188")
        assert service.resolve_base_url(_media_config()) == "http://comfyui:8188"


class TestCheckpointResolution:
    def test_request_wins_over_config(self):
        template, client = _image_setup()
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): CHECKPOINTS})
        chosen = service.resolve_enum_choice(template, info, param="checkpoint", requested=CHECKPOINTS[1], configured=CHECKPOINTS[0], label="checkpoint")
        assert chosen == CHECKPOINTS[1]

    def test_installed_list_is_the_fallback_so_a_fresh_install_generates(self):
        template = load_template("txt2img")
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): CHECKPOINTS})
        chosen = service.resolve_enum_choice(template, info, param="checkpoint", requested=None, configured=None, label="checkpoint")
        assert chosen == CHECKPOINTS[0]

    def test_a_checkpoint_that_is_not_installed_names_what_is(self):
        template = load_template("txt2img")
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): CHECKPOINTS})
        with pytest.raises(service.MediaToolError, match="dreamshaper_8"):
            service.resolve_enum_choice(template, info, param="checkpoint", requested="not-installed.safetensors", configured=None, label="checkpoint")

    def test_empty_model_directory_says_so(self):
        template = load_template("txt2img")
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): []})
        with pytest.raises(service.MediaToolError, match="no checkpoint installed"):
            service.resolve_enum_choice(template, info, param="checkpoint", requested=None, configured=None, label="checkpoint")


@pytest.mark.asyncio
class TestGenerateImage:
    async def _generate(self, tmp_path: Path, client, config: MediaConfig | None = None, **kwargs):
        service.reset_validation_cache()
        cfg = config or _media_config()
        with patch.object(tools, "media_config", lambda: cfg), patch.object(tools, "build_client", lambda *a, **k: client):
            return await tools.generate_image_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t1", **kwargs)

    async def test_writes_the_png_and_presents_it_as_an_artifact(self, tmp_path: Path):
        _, client = _image_setup()
        command = await self._generate(tmp_path, client, prompt="an orange cat on a windowsill")
        payload = json.loads(command.update["messages"][0].content)

        image_path = tmp_path / Path(payload["image"]).name
        assert image_path.is_file()
        assert command.update["artifacts"] == [payload["image"]]
        assert payload["image"].startswith("/mnt/user-data/outputs/")

    async def test_saves_the_submitted_graph_beside_the_image(self, tmp_path: Path):
        _, client = _image_setup()
        command = await self._generate(tmp_path, client, prompt="a cat", seed=7)
        payload = json.loads(command.update["messages"][0].content)

        workflow_path = tmp_path / Path(payload["workflow"]).name
        saved = json.loads(workflow_path.read_text())
        assert saved == client.submitted[0], "the saved graph must be the graph that ran"
        assert saved["3"]["inputs"]["seed"] == 7
        assert "bindings" not in saved, "binding metadata must not reach the submitted graph"

    async def test_seed_is_held_when_given_and_reported_when_drawn(self, tmp_path: Path):
        _, client = _image_setup()
        held = json.loads((await self._generate(tmp_path, client, prompt="a cat", seed=123)).update["messages"][0].content)
        assert held["seed"] == 123

        _, client2 = _image_setup()
        drawn = json.loads((await self._generate(tmp_path, client2, prompt="a cat")).update["messages"][0].content)
        assert isinstance(drawn["seed"], int)
        assert client2.submitted[0]["3"]["inputs"]["seed"] == drawn["seed"], "the reported seed must be the one that ran, or iteration is guesswork"

    async def test_configured_default_checkpoint_is_used_without_the_model_naming_one(self, tmp_path: Path):
        _, client = _image_setup()
        config = _media_config(default_checkpoint=CHECKPOINTS[1])
        command = await self._generate(tmp_path, client, config=config, prompt="a cat")
        payload = json.loads(command.update["messages"][0].content)
        assert payload["checkpoint"] == CHECKPOINTS[1]
        assert client.submitted[0]["4"]["inputs"]["ckpt_name"] == CHECKPOINTS[1]

    async def test_image_uses_the_image_timeout_not_the_video_one(self, tmp_path: Path):
        _, client = _image_setup()
        config = _media_config()
        config.comfyui.image_timeout = 42.0
        config.comfyui.video_timeout = 999.0
        await self._generate(tmp_path, client, config=config, prompt="a cat")
        assert client.timeouts == [42.0]

    async def test_a_run_without_outputs_is_an_error_not_a_silent_success(self, tmp_path: Path):
        _, client = _image_setup(outputs=[])
        command = await self._generate(tmp_path, client, prompt="a cat")
        assert "Error" in command.update["messages"][0].content
        assert "artifacts" not in command.update

    async def test_missing_outputs_path_is_reported_rather_than_crashing(self, tmp_path: Path):
        _, client = _image_setup()
        service.reset_validation_cache()
        cfg = _media_config()
        with patch.object(tools, "media_config", lambda: cfg), patch.object(tools, "build_client", lambda *a, **k: client):
            command = await tools.generate_image_tool.coroutine(runtime=runtime(None), tool_call_id="t1", prompt="a cat")
        assert "outputs path" in command.update["messages"][0].content


@pytest.mark.asyncio
class TestListMediaModels:
    async def test_lists_what_the_running_build_has(self):
        template = load_template("txt2img")
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): CHECKPOINTS, ("KSampler", "sampler_name"): ["euler", "dpmpp_2m"]})
        client = FakeComfyUIClient(info)
        cfg = _media_config()
        with patch.object(tools, "media_config", lambda: cfg), patch.object(tools, "build_client", lambda *a, **k: client):
            payload = json.loads(await tools.list_media_models_tool.coroutine())
        assert payload["models"]["checkpoints"] == CHECKPOINTS
        assert payload["models"]["samplers"] == ["euler", "dpmpp_2m"]

    async def test_an_unreachable_service_reports_an_error_instead_of_raising(self):
        def _boom(*args, **kwargs):
            raise service.MediaToolError("ComfyUI at http://localhost:8188 is unreachable")

        with patch.object(tools, "build_client", _boom):
            payload = json.loads(await tools.list_media_models_tool.coroutine())
        assert "unreachable" in payload["error"]


class TestServiceWiring:
    def test_comfyui_compose_publishes_loopback_only(self):
        """The ComfyUI API has no authentication and can read/write host files."""
        compose = yaml.safe_load((REPO_ROOT / "docker" / "docker-compose.comfyui.yml").read_text(encoding="utf-8"))
        ports = compose["services"]["comfyui"]["ports"]
        assert ports == ["${BIND_HOST:-127.0.0.1}:${DEER_FLOW_COMFYUI_PORT:-8188}:8188"], ports

    def test_config_example_ships_the_tools_disabled(self):
        """ComfyUI is not running on a fresh machine; an active entry would fail at chat time."""
        text = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")
        active = [line for line in text.splitlines() if "deerflow.community.comfyui" in line and not line.strip().startswith("#")]
        assert active == [], active

    def test_config_example_documents_the_media_section(self):
        config = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
        media = config["media"]
        assert media["comfyui"]["base_url"] == "http://localhost:8188"
        assert media["gpu"]["policy"] == "auto"
        # The whole point of a separate video budget; a shared timeout would
        # abandon working clips.
        assert media["comfyui"]["video_timeout"] > media["comfyui"]["image_timeout"]

    def test_media_group_is_declared_so_the_tool_entries_resolve(self):
        config = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
        assert {"name": "media"} in config["tool_groups"]


@pytest.mark.asyncio
class TestClientRunLoop:
    """The submit → poll → fetch loop, driven through a mock transport."""

    def _client(self, handler, **kwargs) -> ComfyUIClient:
        import httpx

        return ComfyUIClient("http://comfy.test", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)), poll_interval=0, **kwargs)

    async def test_polls_until_the_history_carries_outputs(self):
        import httpx

        calls = {"history": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "abc"})
            if request.url.path.startswith("/history"):
                calls["history"] += 1
                if calls["history"] < 3:
                    return httpx.Response(200, json={})
                return httpx.Response(200, json={"abc": {"outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}})
            raise AssertionError(request.url.path)

        result = await self._client(handler).run({"9": {}}, timeout=30, sleep=_no_sleep)
        assert [output.filename for output in result.outputs] == ["a.png"]
        assert calls["history"] == 3

    async def test_a_run_past_its_budget_times_out_instead_of_polling_forever(self):
        import httpx

        from deerflow.community.comfyui.client import ComfyUITimeout

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "abc"})
            return httpx.Response(200, json={})

        ticks = iter([0.0, 5.0, 61.0, 62.0, 63.0])
        with pytest.raises(ComfyUITimeout, match="did not finish within 60"):
            await self._client(handler).run({"9": {}}, timeout=60, sleep=_no_sleep, now=lambda: next(ticks))

    async def test_free_treats_an_unreachable_service_as_already_free(self):
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no service", request=request)

        assert await self._client(handler).free() is True


async def _no_sleep(_seconds: float) -> None:
    return None
