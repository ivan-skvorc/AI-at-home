"""Unit tests for scripts/detect_comfyui.py.

The property worth pinning: an instance you already run is **reused**, never
duplicated. A second ComfyUI is not a second lightweight web service, it is a
second process putting model weights on the same card.

Run from repo root:
    cd backend && uv run pytest tests/test_detect_comfyui.py -v
"""

from __future__ import annotations

from pathlib import Path

import detect_comfyui
from detect_comfyui import (
    AUTOSTART_ENV,
    ENV_VAR,
    IN_NETWORK_URL,
    autostart_decision,
    config_uses_comfyui,
    resolve,
    translate_for_docker,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

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


class TestAutostartDecision:
    """Whether a launch may PROVISION ComfyUI, which is not the same question
    as which endpoint to use.

    The tools ship enabled, so this gate is what stands between "a picture just
    works" and "`make dev` pulls gigabytes and fails at `compose up`" on a
    laptop with no GPU. Both wrong answers are quiet: provisioning where it
    cannot work produces a confusing compose error during an unrelated command,
    and refusing where it *would* work leaves the user with tool errors and no
    hint that one command fixes them. Every branch therefore carries a reason,
    and the reason is asserted.
    """

    _DOCKER_UP = {"info": "27.0.1\n"}

    def test_docker_and_a_gpu_start_the_bundled_service(self):
        start, reason = autostart_decision(env={}, docker=_docker(self._DOCKER_UP), gpu=lambda: True)
        assert start is True
        assert "GPU" in reason

    def test_no_gpu_holds_and_names_the_override(self):
        start, reason = autostart_decision(env={}, docker=_docker(self._DOCKER_UP), gpu=lambda: False)
        assert start is False
        # The detector cannot see every passthrough (WSL, a rented box), so the
        # message has to say how to overrule it rather than just declining.
        assert AUTOSTART_ENV in reason

    def test_no_docker_holds_even_when_forced(self):
        start, reason = autostart_decision(env={AUTOSTART_ENV: "1"}, docker=_docker(), gpu=lambda: True)
        assert start is False
        assert "Docker" in reason

    def test_the_opt_out_is_honoured_on_a_machine_that_could_run_it(self):
        start, reason = autostart_decision(env={AUTOSTART_ENV: "0"}, docker=_docker(self._DOCKER_UP), gpu=lambda: True)
        assert start is False
        assert "switched off" in reason

    def test_forcing_starts_it_without_a_detected_gpu(self):
        start, _ = autostart_decision(env={AUTOSTART_ENV: "true"}, docker=_docker(self._DOCKER_UP), gpu=lambda: False)
        assert start is True

    def test_a_gpu_detector_that_raises_is_no_gpu_rather_than_a_crash(self):
        def boom() -> bool:
            raise RuntimeError("nvidia-smi exploded")

        assert detect_comfyui.gpu_present(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) is False
        start, _ = autostart_decision(env={}, docker=_docker(self._DOCKER_UP), gpu=lambda: detect_comfyui.gpu_present(boom))
        assert start is False


class TestCLIOutput:
    """The launch scripts branch on these exact words."""

    def _run(self, capsys, monkeypatch, *, resolution, start):
        monkeypatch.setattr(detect_comfyui, "resolve", lambda **_kwargs: resolution)
        monkeypatch.setattr(detect_comfyui, "autostart_decision", lambda **_kwargs: (start, "because"))
        assert detect_comfyui.main(["--context", "host"]) == 0
        return capsys.readouterr().out.strip()

    def test_a_provisionable_machine_prints_bundled_start(self, capsys, monkeypatch):
        assert self._run(capsys, monkeypatch, resolution=("bundled", None), start=True) == "bundled start"

    def test_a_machine_that_cannot_run_it_prints_bundled_hold(self, capsys, monkeypatch):
        assert self._run(capsys, monkeypatch, resolution=("bundled", None), start=False) == "bundled hold"

    def test_an_existing_instance_is_never_provisioned_over(self, capsys, monkeypatch):
        out = self._run(capsys, monkeypatch, resolution=("external", "http://127.0.0.1:8188"), start=True)
        assert out == "external http://127.0.0.1:8188"

    def test_the_in_network_url_is_the_container_name_the_stack_attaches(self):
        # The bundled ComfyUI is its own compose project, so the gateway resolves
        # it by container name on the attached network — not by a service alias
        # that no compose file defines. deploy.sh / docker.sh export this exact
        # value, and `resolve` must keep treating it as "no override".
        assert IN_NETWORK_URL == "http://deer-flow-comfyui:8188"


class TestLaunchScriptWiring:
    """The detector's words and the launch scripts' branches are one contract.

    This is a text test on purpose. The failure it catches is invisible in unit
    tests and in review: the detector prints `bundled start`, a script still
    matches the old bare `bundled)`, and the branch simply never runs — no
    error, no message, image generation quietly unavailable on every fresh
    machine. Nothing else asserts the two halves agree.
    """

    SCRIPTS = ("serve.sh", "docker.sh", "deploy.sh")

    def _script(self, name: str) -> str:
        return (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")

    def test_every_launch_script_handles_both_bundled_answers(self):
        for name in self.SCRIPTS:
            body = self._script(name)
            assert '"bundled start")' in body, f"{name} does not branch on `bundled start`"
            assert '"bundled hold")' in body, f"{name} does not branch on `bundled hold`"

    def test_no_script_still_matches_the_retired_bare_word(self):
        for name in self.SCRIPTS:
            for line in self._script(name).splitlines():
                stripped = line.strip()
                assert stripped != "bundled)", f"{name} still has a bare `bundled)` case, which the detector never prints"

    def test_the_bundled_container_is_started_through_the_shared_script(self):
        """One implementation for the automatic door and `make comfy-up`."""
        for name in self.SCRIPTS:
            assert "scripts/comfyui.sh" in self._script(name), f"{name} does not start the bundled container"
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "./scripts/comfyui.sh up" in makefile

    def test_the_docker_paths_export_the_url_they_attach_the_container_for(self):
        """The gateway container resolves it by container name, on the network we attach."""
        for name in ("docker.sh", "deploy.sh"):
            body = self._script(name)
            assert IN_NETWORK_URL in body, f"{name} does not export {IN_NETWORK_URL}"
            assert "attach" in body, f"{name} exports the in-network URL but never attaches the container to the stack network"
