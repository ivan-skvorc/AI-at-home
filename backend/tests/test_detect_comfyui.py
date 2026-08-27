"""Unit tests for scripts/detect_comfyui.py.

The property worth pinning: an instance you already run is **reused**, never
duplicated. A second ComfyUI is not a second lightweight web service, it is a
second process putting model weights on the same card.

Run from repo root:
    cd backend && uv run pytest tests/test_detect_comfyui.py -v
"""

from __future__ import annotations

from detect_comfyui import (
    ENV_VAR,
    IN_NETWORK_URL,
    config_uses_comfyui,
    resolve,
    translate_for_docker,
)

COMFY_CONFIG = """
tools:
  - name: generate_image
    group: media
    use: deerflow.community.comfyui.tools:generate_image_tool
"""

DISABLED_CONFIG = """
tools:
  # - name: generate_image
  #   use: deerflow.community.comfyui.tools:generate_image_tool
  - name: image_search
    use: deerflow.community.image_search.tools:image_search_tool
"""


def _probe(reachable: set[str]):
    return lambda url: url.rstrip("/") in {item.rstrip("/") for item in reachable}


def _docker(responses: dict[str, str | None] | None = None):
    responses = responses or {}

    def run(args: list[str]) -> str | None:
        key = args[0]
        return responses.get(key)

    return run


class TestConfigDetection:
    def test_an_active_tool_entry_enables_detection(self):
        assert config_uses_comfyui(COMFY_CONFIG) is True

    def test_commented_out_entries_do_not_count(self):
        assert config_uses_comfyui(DISABLED_CONFIG) is False

    def test_a_config_without_the_tools_skips_entirely(self):
        assert resolve(context="host", env={}, config_text=DISABLED_CONFIG) == ("skip", None)


class TestExistingInstanceReuse:
    def test_a_running_local_instance_is_reused_rather_than_duplicated(self):
        mode, url = resolve(context="host", env={}, config_text=COMFY_CONFIG, probe=_probe({"http://127.0.0.1:8188"}), docker=_docker())
        assert (mode, url) == ("external", "http://127.0.0.1:8188")

    def test_nothing_running_resolves_to_the_bundled_service(self):
        assert resolve(context="host", env={}, config_text=COMFY_CONFIG, probe=_probe(set()), docker=_docker()) == ("bundled", None)

    def test_our_own_container_resolves_to_bundled_so_up_stays_idempotent(self):
        docker = _docker({"ps": "deer-flow-comfyui\n"})
        assert resolve(context="docker", env={}, config_text=COMFY_CONFIG, probe=_probe({"http://127.0.0.1:8188"}), docker=docker) == ("bundled", None)

    def test_a_host_instance_is_translated_for_containers_when_reachable(self):
        docker = _docker({"network": "172.17.0.1\n"})
        mode, url = resolve(
            context="docker",
            env={},
            config_text=COMFY_CONFIG,
            probe=_probe({"http://127.0.0.1:8188", "http://172.17.0.1:8188"}),
            docker=docker,
        )
        assert (mode, url) == ("external", "http://host.docker.internal:8188")

    def test_a_loopback_only_instance_falls_back_rather_than_silently_breaking(self):
        docker = _docker({"network": "172.17.0.1\n", "info": "Docker Engine - Community"})
        assert resolve(context="docker", env={}, config_text=COMFY_CONFIG, probe=_probe({"http://127.0.0.1:8188"}), docker=docker) == ("bundled", None)


class TestEnvOverride:
    def test_an_explicit_url_wins_when_it_answers(self):
        env = {ENV_VAR: "http://127.0.0.1:9188"}
        mode, url = resolve(context="host", env=env, config_text=COMFY_CONFIG, probe=_probe({"http://127.0.0.1:9188"}), docker=_docker())
        assert (mode, url) == ("external", "http://127.0.0.1:9188")

    def test_a_dead_explicit_loopback_url_falls_back_to_bundled(self):
        env = {ENV_VAR: "http://127.0.0.1:9188"}
        assert resolve(context="host", env=env, config_text=COMFY_CONFIG, probe=_probe(set()), docker=_docker()) == ("bundled", None)

    def test_a_remote_url_is_respected_even_when_unverifiable_from_here(self):
        env = {ENV_VAR: "http://gpu-box.tailnet:8188"}
        mode, url = resolve(context="host", env=env, config_text=COMFY_CONFIG, probe=_probe(set()), docker=_docker())
        assert (mode, url) == ("external", "http://gpu-box.tailnet:8188")

    def test_the_in_network_default_does_not_count_as_an_override(self):
        env = {ENV_VAR: IN_NETWORK_URL}
        assert resolve(context="docker", env=env, config_text=COMFY_CONFIG, probe=_probe(set()), docker=_docker()) == ("bundled", None)


class TestTranslation:
    def test_loopback_hosts_become_host_docker_internal(self):
        assert translate_for_docker("http://localhost:8188") == "http://host.docker.internal:8188"

    def test_other_hosts_are_left_alone(self):
        assert translate_for_docker("http://gpu-box:8188") == "http://gpu-box:8188"
