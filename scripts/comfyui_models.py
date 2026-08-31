#!/usr/bin/env python3
"""Install and list ComfyUI model files, for whichever ComfyUI is in use.

The media tools ship on by default, but the *weights* never can: checkpoints
are gigabytes and their licences are the user's to accept. So the one thing a
fresh install still needs is a model, and this is the supported way to put one
there — for **both** shapes of the integration, which is the whole point:

* **bundled** — the container `make comfy-up` (or a launch path) starts. Its
  models directory is a host bind mount, so a file written there is visible to
  the container immediately, with no copy into the image and no restart.
* **external** — a ComfyUI you already run, which the detector prefers over
  starting a second one. Its models directory is wherever *you* installed it,
  so it is resolved in this order: ``--models-dir``, then
  ``DEER_FLOW_COMFYUI_EXTERNAL_MODELS``, then — when it is itself a container —
  the host side of whatever it has mounted at ``…/models``, then the well-known
  install paths. Every step is reported, because "it downloaded 6 GB into the
  wrong ComfyUI" is a failure that looks exactly like success.

Both paths write a real file into a real directory. There is deliberately no
"upload a model through the API" path: core ComfyUI has no such endpoint, and
the ones that exist in custom nodes are an unauthenticated write primitive on
the machine holding the GPU.

Usage:
    python3 scripts/comfyui_models.py list [--base-url URL] [--json]
    python3 scripts/comfyui_models.py where [--target auto|bundled|external]
    python3 scripts/comfyui_models.py add <url|path> --type checkpoints \\
        [--name NAME] [--target auto|bundled|external] [--models-dir DIR] \\
        [--sha256 HEX] [--force] [--dry-run]

Stdlib only: it runs under the system interpreter from the root Makefile
(`make comfy-models`, `make comfy-model-add`), not inside the backend venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect_comfyui import (  # noqa: E402 - path bootstrap above
    BUNDLED_CONTAINER,
    ENV_VAR,
    bundled_container_publishes,
    probe_comfyui,
)
from detect_searxng import parse_env_file, run_docker  # noqa: E402 - path bootstrap above

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://localhost:8188"
BUNDLED_MODELS_ENV = "DEER_FLOW_COMFYUI_MODELS"
EXTERNAL_MODELS_ENV = "DEER_FLOW_COMFYUI_EXTERNAL_MODELS"
# Matches docker-compose.comfyui.yml's default, which is relative to docker/.
BUNDLED_MODELS_DEFAULT = REPO_ROOT / ".deer-flow" / "comfyui" / "models"
DOWNLOAD_TIMEOUT = 60.0
DOWNLOAD_CHUNK = 1024 * 1024

# ComfyUI's own folder names, with the loader enum each one feeds. The enum is
# what `add` re-reads afterwards: a file on disk that no loader lists is the
# quiet failure mode (wrong folder, wrong extension), and it should be reported
# as one rather than as a successful install.
MODEL_TYPES: dict[str, tuple[str, str] | None] = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "diffusion_models": ("UNETLoader", "unet_name"),
    "unet": ("UNETLoader", "unet_name"),
    "clip": ("CLIPLoader", "clip_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "clip_vision": ("CLIPVisionLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
    "loras": ("LoraLoader", "lora_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "upscale_models": ("UpscaleModelLoader", "model_name"),
    "embeddings": None,
    "style_models": ("StyleModelLoader", "style_model_name"),
    "hypernetworks": ("HypernetworkLoader", "hypernetwork_name"),
}
# Spellings people actually type, mapped onto the folder ComfyUI reads.
TYPE_ALIASES = {
    "checkpoint": "checkpoints",
    "ckpt": "checkpoints",
    "model": "checkpoints",
    "lora": "loras",
    "diffusion_model": "diffusion_models",
    "text_encoder": "text_encoders",
    "vaes": "vae",
    "clips": "clip",
    "controlnets": "controlnet",
    "upscale": "upscale_models",
    "upscaler": "upscale_models",
    "embedding": "embeddings",
}
# Where a hand-installed ComfyUI usually keeps its models. Probed only after
# the explicit sources, and only accepted when the directory looks like one.
WELL_KNOWN_EXTERNAL = (
    "~/ComfyUI/models",
    "~/comfy/ComfyUI/models",
    "~/comfyui/models",
    "/opt/ComfyUI/models",
    "/usr/share/ComfyUI/models",
)

_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ModelError(RuntimeError):
    """A user-facing failure: printed as a message, never a traceback."""


def log(message: str) -> None:
    print(f"[comfyui_models] {message}", file=sys.stderr)


# ── environment ──────────────────────────────────────────────────────────────


def load_env(env_file: Path | None = None) -> dict[str, str]:
    """Repo `.env` values, overridden by the process environment."""
    values: dict[str, str] = {}
    path = env_file if env_file is not None else REPO_ROOT / ".env"
    if path.exists():
        values.update(parse_env_file(path))
    for key in (ENV_VAR, BUNDLED_MODELS_ENV, EXTERNAL_MODELS_ENV):
        if os.environ.get(key, "").strip():
            values[key] = os.environ[key].strip()
    return values


# ── model type and file name ─────────────────────────────────────────────────


def normalize_model_type(raw: str) -> str:
    """Map a user-typed type onto a ComfyUI folder name, or refuse it."""
    value = (raw or "").strip().lower().replace("-", "_")
    value = TYPE_ALIASES.get(value, value)
    if value not in MODEL_TYPES:
        known = ", ".join(sorted(MODEL_TYPES))
        raise ModelError(f"unknown model type {raw!r}; use one of: {known}")
    return value


def safe_filename(source: str, explicit: str | None = None) -> str:
    """The file name to write, derived from --name or the source.

    A model name reaches the filesystem, so it is a name and never a path:
    anything carrying a separator or a parent reference is refused outright
    rather than sanitized into something the caller did not ask for.
    """
    if explicit:
        candidate = explicit.strip()
    else:
        parsed = urllib.parse.urlparse(source)
        candidate = Path(urllib.parse.unquote(parsed.path if parsed.scheme in {"http", "https"} else source)).name
    candidate = candidate.strip()
    if not candidate:
        raise ModelError(f"could not derive a file name from {source!r}; pass --name")
    if candidate in {".", ".."} or "/" in candidate or "\\" in candidate or candidate.startswith("."):
        raise ModelError(f"refusing the file name {candidate!r}: it must be a plain file name, not a path")
    return candidate


# ── where the models live ────────────────────────────────────────────────────


def container_models_source(inspect_payload: str | None) -> str | None:
    """Host path a container has mounted at ComfyUI's models directory.

    `docker inspect` output is the only place this is written down: an external
    ComfyUI in a container knows its models as `/root/ComfyUI/models`, which is
    meaningless on the host until it is mapped back through its own mount.
    """
    if not inspect_payload:
        return None
    try:
        parsed = json.loads(inspect_payload)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        for mount in entry.get("Mounts") or []:
            if not isinstance(mount, Mapping):
                continue
            destination = str(mount.get("Destination") or "").rstrip("/")
            source = str(mount.get("Source") or "")
            if destination.endswith("/models") and source:
                return source
    return None


def looks_like_models_dir(path: Path) -> bool:
    """True when a directory is plausibly ComfyUI's models root."""
    if not path.is_dir():
        return False
    return any((path / name).is_dir() for name in MODEL_TYPES)


def container_publishing_port(port: int, docker: Callable[[list[str]], str | None]) -> str | None:
    """Name of the container publishing `port`, if any."""
    out = docker(["ps", "--filter", f"publish={port}", "--format", "{{.Names}}"])
    if not out:
        return None
    names = [name for name in out.split() if name]
    return names[0] if names else None


def resolve_target(
    *,
    requested: str,
    base_url: str,
    docker: Callable[[list[str]], str | None],
    probe: Callable[[str], bool],
) -> str:
    """Decide whether models belong to the bundled container or an external one.

    Mirrors the endpoint decision the launch scripts make, so `add` writes into
    the same ComfyUI the Gateway will be talking to.
    """
    if requested in {"bundled", "external"}:
        return requested
    port = urllib.parse.urlparse(base_url).port or 8188
    if bundled_container_publishes(port, docker):
        return "bundled"
    if probe(base_url):
        return "external"
    # Nothing is running: the bundled container is what a launch will start.
    return "bundled"


def resolve_models_dir(
    *,
    target: str,
    env: Mapping[str, str],
    base_url: str = DEFAULT_BASE_URL,
    explicit: str | None = None,
    docker: Callable[[list[str]], str | None] | None = None,
    probe: Callable[[str], bool] | None = None,
    home: Path | None = None,
) -> tuple[Path, str, str]:
    """Return (models_dir, resolved_target, how_it_was_found)."""
    if docker is None:
        docker = run_docker
    if probe is None:
        probe = probe_comfyui

    if explicit:
        return (Path(explicit).expanduser(), target if target != "auto" else "explicit", "--models-dir")

    resolved = resolve_target(requested=target, base_url=base_url, docker=docker, probe=probe)

    if resolved == "bundled":
        configured = (env.get(BUNDLED_MODELS_ENV) or "").strip()
        if configured:
            return (Path(configured).expanduser(), resolved, f"{BUNDLED_MODELS_ENV}")
        return (BUNDLED_MODELS_DEFAULT, resolved, "the bundled container's default bind mount")

    configured = (env.get(EXTERNAL_MODELS_ENV) or "").strip()
    if configured:
        return (Path(configured).expanduser(), resolved, EXTERNAL_MODELS_ENV)

    port = urllib.parse.urlparse(base_url).port or 8188
    name = container_publishing_port(port, docker)
    if name and name != BUNDLED_CONTAINER:
        mounted = container_models_source(docker(["inspect", name]))
        if mounted:
            return (Path(mounted), resolved, f"the models mount of container '{name}'")

    base = home if home is not None else Path.home()
    for candidate in WELL_KNOWN_EXTERNAL:
        path = Path(candidate.replace("~", str(base), 1)) if candidate.startswith("~") else Path(candidate)
        if looks_like_models_dir(path):
            return (path, resolved, f"a well-known install path ({path})")

    raise ModelError(
        "could not find the models directory of the ComfyUI you are running. "
        f"Set {EXTERNAL_MODELS_ENV} in .env (or pass --models-dir) to the `models` "
        "folder of that install — writing into the bundled container's directory "
        "instead would put the file where that ComfyUI never looks."
    )


# ── fetching ─────────────────────────────────────────────────────────────────


def _auth_headers(url: str, env: Mapping[str, str]) -> dict[str, str]:
    """Bearer token for hosts that gate downloads behind one (Hugging Face)."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host.endswith("huggingface.co"):
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or env.get("HF_TOKEN", "")
        if token.strip():
            return {"Authorization": f"Bearer {token.strip()}"}
    return {}


def fetch_to(
    source: str,
    destination: Path,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    """Copy a local file or download a URL to `destination`."""
    env = env or {}
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"", "file"}:
        local = Path(parsed.path if parsed.scheme == "file" else source).expanduser()
        if not local.is_file():
            raise ModelError(f"no such file: {local}")
        shutil.copyfile(local, destination)
        return
    if parsed.scheme not in {"http", "https"}:
        raise ModelError(f"unsupported source scheme {parsed.scheme!r}: pass an http(s) URL or a local path")

    request = urllib.request.Request(
        source,
        headers={"User-Agent": "deer-flow-comfyui-models/1.0", **_auth_headers(source, env)},
    )
    open_url = opener if opener is not None else _DIRECT_OPENER.open
    try:
        with open_url(request, timeout=DOWNLOAD_TIMEOUT) as response, destination.open("wb") as handle:  # type: ignore[union-attr]
            total_header = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            total = int(total_header) if total_header and total_header.isdigit() else None
            done = 0
            while True:
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise ModelError(f"download failed: {exc}") from exc


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_model(
    *,
    source: str,
    models_dir: Path,
    model_type: str,
    name: str,
    env: Mapping[str, str] | None = None,
    sha256: str | None = None,
    force: bool = False,
    fetch: Callable[[str, Path], None] | None = None,
) -> Path:
    """Put one model file where ComfyUI reads it, or raise ModelError.

    Downloads land on a `.part` file and are renamed only once complete (and
    once the checksum matches). A half-downloaded checkpoint that ComfyUI lists
    as installed is worse than no checkpoint: it fails inside a generation, in a
    place that reads as a broken template rather than a broken file.
    """
    target_dir = models_dir / model_type
    destination = target_dir / name
    if destination.exists() and not force:
        raise ModelError(f"{destination} already exists; pass --force to replace it")

    target_dir.mkdir(parents=True, exist_ok=True)
    partial = target_dir / f".{name}.part"
    if partial.exists():
        partial.unlink()

    def _progress(done: int, total: int | None) -> None:
        if total:
            print(f"\r  {done / 1024 / 1024:,.0f} / {total / 1024 / 1024:,.0f} MiB", end="", file=sys.stderr, flush=True)

    try:
        if fetch is not None:
            fetch(source, partial)
        else:
            fetch_to(source, partial, env=env, progress=_progress)
        print("", file=sys.stderr)
        if sha256:
            actual = sha256_of(partial)
            if actual.lower() != sha256.strip().lower():
                raise ModelError(f"checksum mismatch: expected {sha256.strip().lower()}, got {actual}")
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination


# ── reading what is installed ────────────────────────────────────────────────


def fetch_object_info(base_url: str, *, opener: Callable[..., object] | None = None) -> dict:
    url = base_url.rstrip("/") + "/object_info"
    request = urllib.request.Request(url, headers={"User-Agent": "deer-flow-comfyui-models/1.0"})
    open_url = opener if opener is not None else _DIRECT_OPENER.open
    try:
        with open_url(request, timeout=30.0) as response:  # type: ignore[union-attr]
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, ValueError, OSError) as exc:
        raise ModelError(f"could not read {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"{url} did not answer with an object_info payload")
    return payload


def enum_values(object_info: Mapping, node: str, field: str) -> list[str]:
    """The installed-file list a loader node reports for one of its inputs."""
    try:
        required = object_info[node]["input"]["required"]
        choices = required[field][0]
    except (KeyError, IndexError, TypeError):
        return []
    if isinstance(choices, list):
        return [str(value) for value in choices]
    return []


def installed_models(object_info: Mapping) -> dict[str, list[str]]:
    """Everything the running build can load, keyed by ComfyUI folder name."""
    found: dict[str, list[str]] = {}
    for folder, binding in MODEL_TYPES.items():
        if binding is None:
            continue
        node, field = binding
        values = enum_values(object_info, node, field)
        if values and folder not in found:
            found[folder] = values
    return found


# ── commands ─────────────────────────────────────────────────────────────────


def _base_url(args: argparse.Namespace, env: Mapping[str, str]) -> str:
    return (args.base_url or env.get(ENV_VAR) or DEFAULT_BASE_URL).strip()


def cmd_list(args: argparse.Namespace) -> int:
    env = load_env()
    base_url = _base_url(args, env)
    object_info = fetch_object_info(base_url)
    models = installed_models(object_info)
    if args.json:
        print(json.dumps({"base_url": base_url, "models": models}, indent=2))
        return 0
    print(f"ComfyUI at {base_url}")
    if not models:
        print("  no model files installed yet — `make comfy-model-add SOURCE=<url> TYPE=checkpoints`")
        return 0
    for folder in sorted(models):
        print(f"  {folder}:")
        for value in models[folder]:
            print(f"    - {value}")
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    env = load_env()
    models_dir, target, how = resolve_models_dir(
        target=args.target,
        env=env,
        base_url=_base_url(args, env),
        explicit=args.models_dir,
    )
    print(f"{models_dir}")
    log(f"target: {target} (resolved via {how})")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    env = load_env()
    base_url = _base_url(args, env)
    model_type = normalize_model_type(args.type)
    name = safe_filename(args.source, args.name)
    models_dir, target, how = resolve_models_dir(
        target=args.target,
        env=env,
        base_url=base_url,
        explicit=args.models_dir,
    )

    destination = models_dir / model_type / name
    log(f"target: {target} ComfyUI (models directory found via {how})")
    if args.dry_run:
        print(f"would install {args.source} -> {destination}")
        return 0

    print(f"Installing {name} into {destination.parent} ...", file=sys.stderr)
    install_model(
        source=args.source,
        models_dir=models_dir,
        model_type=model_type,
        name=name,
        env=env,
        sha256=args.sha256,
        force=args.force,
    )
    print(f"✓ installed {destination}")

    # Reading it back is the only proof that the file landed where THIS ComfyUI
    # looks — the failure mode of the external path is a perfectly good download
    # into a directory nothing reads.
    binding = MODEL_TYPES[model_type]
    if binding is None:
        return 0
    try:
        object_info = fetch_object_info(base_url)
    except ModelError as exc:
        log(f"could not verify against the running ComfyUI ({exc}); start it and run `make comfy-models`")
        return 0
    node, field = binding
    if name in enum_values(object_info, node, field):
        print(f"✓ {base_url} now lists it under {node}.{field}")
    else:
        log(f"the file is written, but {base_url} does not list it under {node}.{field} yet — restart ComfyUI, or check that this is the instance you meant ({how})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=None, help=f"ComfyUI endpoint (default: {ENV_VAR} or {DEFAULT_BASE_URL})")
    common.add_argument("--target", choices=("auto", "bundled", "external"), default="auto", help="which ComfyUI to install into (default: auto-detect)")
    common.add_argument("--models-dir", default=None, help="models directory to use, bypassing detection")

    listing = sub.add_parser("list", parents=[common], help="list the models the running ComfyUI can load")
    listing.add_argument("--json", action="store_true", help="machine-readable output")
    listing.set_defaults(func=cmd_list)

    where = sub.add_parser("where", parents=[common], help="print the models directory that would be written to")
    where.set_defaults(func=cmd_where)

    add = sub.add_parser("add", parents=[common], help="install a model file from a URL or a local path")
    add.add_argument("source", help="https URL or local path of the model file")
    add.add_argument("--type", required=True, help="model type / ComfyUI folder (checkpoints, loras, vae, ...)")
    add.add_argument("--name", default=None, help="file name to write (default: derived from the source)")
    add.add_argument("--sha256", default=None, help="expected SHA-256; the file is discarded when it does not match")
    add.add_argument("--force", action="store_true", help="replace an existing file of that name")
    add.add_argument("--dry-run", action="store_true", help="print what would be installed and stop")
    add.set_defaults(func=cmd_add)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ModelError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
