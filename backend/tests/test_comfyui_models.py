"""Installing model files into whichever ComfyUI is in use (fork feature).

The media tools ship enabled and a launch provisions the service, so the one
thing a fresh install still lacks is a checkpoint. That makes this script the
last mile of "ask for a picture and get one" — and its failure modes are all
quiet:

* **Into the wrong ComfyUI.** A perfectly successful 6 GB download into the
  bundled container's directory is useless when the Gateway is talking to the
  instance you already run. Resolution order is therefore explicit, reported,
  and refuses to guess when it cannot tell.
* **A half-written file that looks installed.** ComfyUI lists whatever is in the
  folder, so a truncated checkpoint fails *inside* a generation, where it reads
  as a broken workflow rather than a broken file. Downloads land on `.part` and
  are renamed only once complete and verified.
* **A name that is really a path.** The name reaches the filesystem, and the
  source of it is a URL.

Run from repo root:
    cd backend && uv run pytest tests/test_comfyui_models.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import comfyui_models
import pytest
from comfyui_models import (
    BUNDLED_MODELS_DEFAULT,
    BUNDLED_MODELS_ENV,
    EXTERNAL_MODELS_ENV,
    ModelError,
    container_models_source,
    install_model,
    installed_models,
    normalize_model_type,
    resolve_models_dir,
    safe_filename,
)


def _docker(responses: dict[str, str | None] | None = None):
    responses = responses or {}

    def run(args: list[str]) -> str | None:
        return responses.get(args[0])

    return run


def _probe(reachable: set[str]):
    return lambda url: url.rstrip("/") in {item.rstrip("/") for item in reachable}


class TestModelType:
    def test_the_spellings_people_type_map_onto_comfyuis_folder_names(self):
        assert normalize_model_type("checkpoint") == "checkpoints"
        assert normalize_model_type("LoRA") == "loras"
        assert normalize_model_type("diffusion-model") == "diffusion_models"

    def test_an_unknown_type_names_the_ones_that_exist(self):
        with pytest.raises(ModelError) as excinfo:
            normalize_model_type("weights")
        # A wrong folder is the silent case (the file installs, no loader lists
        # it), so the error has to be a menu rather than a rejection.
        assert "checkpoints" in str(excinfo.value)


class TestFileName:
    def test_a_name_is_derived_from_the_url_without_its_query(self):
        assert safe_filename("https://host/models/sdxl.safetensors?download=true") == "sdxl.safetensors"

    def test_an_explicit_name_wins(self):
        assert safe_filename("https://host/x", "sdxl.safetensors") == "sdxl.safetensors"

    @pytest.mark.parametrize("hostile", ["../../etc/passwd", "sub/dir.safetensors", "..", ".hidden", "   "])
    def test_a_name_that_is_a_path_is_refused_rather_than_sanitized(self, hostile):
        with pytest.raises(ModelError):
            safe_filename("https://host/model.safetensors", hostile)

    def test_a_url_whose_path_carries_a_traversal_is_refused_too(self):
        # The name comes from a URL, so the traversal need not be typed by hand.
        with pytest.raises(ModelError):
            safe_filename("https://host/models/../../..")


class TestModelsDirResolution:
    def test_bundled_defaults_to_the_containers_bind_mount(self):
        path, target, _how = resolve_models_dir(target="bundled", env={}, docker=_docker(), probe=_probe(set()))
        assert (path, target) == (BUNDLED_MODELS_DEFAULT, "bundled")

    def test_the_bundled_mount_can_be_repointed(self, tmp_path):
        path, _target, how = resolve_models_dir(target="bundled", env={BUNDLED_MODELS_ENV: str(tmp_path)}, docker=_docker(), probe=_probe(set()))
        assert path == tmp_path
        assert BUNDLED_MODELS_ENV in how

    def test_an_external_instance_uses_the_directory_you_named(self, tmp_path):
        path, target, how = resolve_models_dir(target="external", env={EXTERNAL_MODELS_ENV: str(tmp_path)}, docker=_docker(), probe=_probe(set()))
        assert (path, target) == (tmp_path, "external")
        assert EXTERNAL_MODELS_ENV in how

    def test_a_containerized_external_instance_is_read_from_its_own_mount(self):
        """`/root/ComfyUI/models` means nothing on the host until it is mapped back."""
        inspect = json.dumps([{"Mounts": [{"Destination": "/root/ComfyUI/output", "Source": "/srv/out"}, {"Destination": "/root/ComfyUI/models", "Source": "/srv/models"}]}])
        docker = _docker({"ps": "someones-comfyui\n", "inspect": inspect})
        path, _target, how = resolve_models_dir(target="external", env={}, docker=docker, probe=_probe(set()))
        assert path == Path("/srv/models")
        assert "someones-comfyui" in how

    def test_a_well_known_install_path_is_used_when_it_looks_like_one(self, tmp_path):
        models = tmp_path / "ComfyUI" / "models"
        (models / "checkpoints").mkdir(parents=True)
        path, _target, how = resolve_models_dir(target="external", env={}, docker=_docker(), probe=_probe(set()), home=tmp_path)
        assert path == models
        assert "well-known" in how

    def test_an_empty_lookalike_directory_is_not_accepted(self, tmp_path):
        (tmp_path / "ComfyUI" / "models").mkdir(parents=True)
        with pytest.raises(ModelError):
            resolve_models_dir(target="external", env={}, docker=_docker(), probe=_probe(set()), home=tmp_path)

    def test_an_unresolvable_external_instance_refuses_instead_of_guessing(self, tmp_path):
        with pytest.raises(ModelError) as excinfo:
            resolve_models_dir(target="external", env={}, docker=_docker(), probe=_probe(set()), home=tmp_path)
        # Silently writing into the bundled directory is the failure this exists
        # to prevent: it looks like success and the model never loads.
        assert EXTERNAL_MODELS_ENV in str(excinfo.value)

    def test_auto_follows_the_same_reuse_rule_the_gateway_does(self, tmp_path):
        """Whatever the Gateway talks to is what a model must be installed into."""
        ours = _docker({"ps": "deer-flow-comfyui\n"})
        _path, target, _how = resolve_models_dir(target="auto", env={}, docker=ours, probe=_probe({"http://localhost:8188"}))
        assert target == "bundled"

        theirs = _docker({"ps": ""})
        _path, target, _how = resolve_models_dir(
            target="auto",
            env={EXTERNAL_MODELS_ENV: str(tmp_path)},
            docker=theirs,
            probe=_probe({"http://localhost:8188"}),
        )
        assert target == "external"

    def test_nothing_running_at_all_means_the_bundled_one_a_launch_will_start(self):
        _path, target, _how = resolve_models_dir(target="auto", env={}, docker=_docker(), probe=_probe(set()))
        assert target == "bundled"

    def test_an_explicit_directory_bypasses_detection_entirely(self, tmp_path):
        path, _target, how = resolve_models_dir(target="auto", env={}, explicit=str(tmp_path), docker=_docker(), probe=_probe(set()))
        assert path == tmp_path
        assert how == "--models-dir"


class TestContainerMounts:
    def test_a_docker_inspect_payload_without_a_models_mount_is_none(self):
        assert container_models_source(json.dumps([{"Mounts": [{"Destination": "/data", "Source": "/srv/data"}]}])) is None

    def test_junk_is_none_rather_than_an_exception(self):
        assert container_models_source("not json") is None
        assert container_models_source(None) is None


class TestInstall:
    def _fetch(self, payload: bytes):
        def fetch(_source: str, destination: Path) -> None:
            destination.write_bytes(payload)

        return fetch

    def test_a_model_lands_in_its_folder(self, tmp_path):
        written = install_model(source="https://host/m.safetensors", models_dir=tmp_path, model_type="checkpoints", name="m.safetensors", fetch=self._fetch(b"weights"))
        assert written == tmp_path / "checkpoints" / "m.safetensors"
        assert written.read_bytes() == b"weights"

    def test_no_partial_file_survives_a_failed_download(self, tmp_path):
        def boom(_source: str, destination: Path) -> None:
            destination.write_bytes(b"half")
            raise ModelError("connection reset")

        with pytest.raises(ModelError):
            install_model(source="https://host/m.safetensors", models_dir=tmp_path, model_type="checkpoints", name="m.safetensors", fetch=boom)
        # ComfyUI lists whatever is in the folder: a truncated checkpoint left
        # behind would fail inside a generation, looking like a broken workflow.
        assert list((tmp_path / "checkpoints").iterdir()) == []

    def test_a_checksum_mismatch_discards_the_file(self, tmp_path):
        with pytest.raises(ModelError, match="checksum mismatch"):
            install_model(
                source="https://host/m.safetensors",
                models_dir=tmp_path,
                model_type="checkpoints",
                name="m.safetensors",
                sha256="00" * 32,
                fetch=self._fetch(b"weights"),
            )
        assert list((tmp_path / "checkpoints").iterdir()) == []

    def test_a_matching_checksum_installs(self, tmp_path):
        import hashlib

        digest = hashlib.sha256(b"weights").hexdigest()
        written = install_model(
            source="https://host/m.safetensors",
            models_dir=tmp_path,
            model_type="checkpoints",
            name="m.safetensors",
            sha256=digest.upper(),
            fetch=self._fetch(b"weights"),
        )
        assert written.exists()

    def test_an_existing_model_is_not_silently_replaced(self, tmp_path):
        install_model(source="s", models_dir=tmp_path, model_type="loras", name="l.safetensors", fetch=self._fetch(b"one"))
        with pytest.raises(ModelError, match="already exists"):
            install_model(source="s", models_dir=tmp_path, model_type="loras", name="l.safetensors", fetch=self._fetch(b"two"))
        assert (tmp_path / "loras" / "l.safetensors").read_bytes() == b"one"

        install_model(source="s", models_dir=tmp_path, model_type="loras", name="l.safetensors", force=True, fetch=self._fetch(b"two"))
        assert (tmp_path / "loras" / "l.safetensors").read_bytes() == b"two"

    def test_a_local_file_is_copied_rather_than_downloaded(self, tmp_path):
        source = tmp_path / "source.safetensors"
        source.write_bytes(b"local weights")
        written = install_model(source=str(source), models_dir=tmp_path / "models", model_type="vae", name="v.safetensors")
        assert written.read_bytes() == b"local weights"

    def test_a_missing_local_file_is_a_message_not_a_traceback(self, tmp_path):
        with pytest.raises(ModelError, match="no such file"):
            install_model(source=str(tmp_path / "nope.safetensors"), models_dir=tmp_path / "models", model_type="vae", name="v.safetensors")


class TestReadingWhatIsInstalled:
    OBJECT_INFO = {
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sdxl_base.safetensors", "dreamshaper_8.safetensors"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [["sdxl_vae.safetensors"]]}}},
        "LoraLoader": {"input": {"required": {"lora_name": [[]]}}},
    }

    def test_installed_models_are_read_from_the_builds_own_enums(self):
        found = installed_models(self.OBJECT_INFO)
        assert found["checkpoints"] == ["sdxl_base.safetensors", "dreamshaper_8.safetensors"]
        assert found["vae"] == ["sdxl_vae.safetensors"]

    def test_a_loader_with_nothing_installed_is_omitted_rather_than_empty(self):
        assert "loras" not in installed_models(self.OBJECT_INFO)

    def test_a_build_without_a_loader_node_does_not_raise(self):
        assert installed_models({}) == {}


class TestCLI:
    def test_a_dry_run_reports_the_destination_without_writing(self, tmp_path, capsys):
        code = comfyui_models.main(["add", "https://host/m.safetensors", "--type", "checkpoint", "--models-dir", str(tmp_path), "--dry-run"])
        assert code == 0
        assert str(tmp_path / "checkpoints" / "m.safetensors") in capsys.readouterr().out
        assert not (tmp_path / "checkpoints").exists()

    def test_a_bad_type_exits_nonzero_with_a_message(self, tmp_path, capsys):
        assert comfyui_models.main(["add", "https://host/m.safetensors", "--type", "weights", "--models-dir", str(tmp_path)]) == 1
        assert "unknown model type" in capsys.readouterr().err
