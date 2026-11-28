"""Offline checks of the CAD sandbox image (docker/sandbox-cad, FORK.md §58).

The image is built locally (`make sandbox-cad-image`) and selected with
`make sandbox-enable MODE=container IMAGE=cad`; nothing here builds it. The
sandbox-cad-image workflow builds it and runs docker/sandbox-cad/smoke.sh. These
tests catch, without Docker, the drifts that only show once a conversation's
container starts: a base tag that no longer matches the pinned AIO image, a
layer that breaks the image's root entrypoint, and a tool or module that
cadkit.py needs but the image does not have.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = REPO_ROOT / "docker" / "sandbox-cad"
DOCKERFILE = IMAGE_DIR / "Dockerfile"
REQUIREMENTS = IMAGE_DIR / "requirements.txt"
CADKIT = REPO_ROOT / "skills" / "public" / "cad-modeling" / "scripts" / "cadkit.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sandbox-cad-image.yml"

# Import names of the distributions requirements.txt pins, where they differ.
IMPORT_NAME = {"cadquery-ocp": "OCP"}

# Modules trimesh loads lazily for the calls cadkit makes, found by running the
# whole loop in the image: ray casts for wall thickness (rtree), even surface
# sampling (scipy), sections (networkx, shapely), booleans (manifold3d) and the
# 3MF writer (lxml). cadkit never imports them itself, so an AST scan misses them.
TRIMESH_EXTRAS = {"rtree", "scipy", "networkx", "shapely", "manifold3d", "lxml"}

# Modules that ship inside another distribution.
SHIPPED_WITH = {"mpl_toolkits": "matplotlib"}


def _load_toggle():
    spec = importlib.util.spec_from_file_location("sandbox_toggle", REPO_ROOT / "scripts" / "sandbox_toggle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instructions() -> list[tuple[str, str]]:
    """The Dockerfile as (INSTRUCTION, arguments), continuation lines joined."""
    joined = re.sub(r"\\\n", " ", DOCKERFILE.read_text(encoding="utf-8"))
    result = []
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        keyword, _, rest = stripped.partition(" ")
        result.append((keyword.upper(), rest.strip()))
    return result


def _apt_packages() -> set[str]:
    packages: set[str] = set()
    for keyword, rest in _instructions():
        if keyword == "RUN" and "apt-get install" in rest:
            after = rest.split("apt-get install", 1)[1].split("&&", 1)[0]
            packages |= {word for word in after.split() if not word.startswith("-")}
    return packages


def _pins() -> dict[str, str]:
    pins = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, version = line.partition("==")
            pins[name.lower()] = version
    return pins


def _requirement_comments() -> str:
    return "\n".join(line for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines() if line.lstrip().startswith("#"))


def _import_check_modules() -> set[str]:
    """Top-level modules the build's `python3 -c "import ..."` line imports."""
    modules: set[str] = set()
    for keyword, rest in _instructions():
        if keyword == "RUN":
            for statement in re.findall(r'python3 -c "([^"]*)"', rest):
                for part in statement.split(";"):
                    part = part.strip()
                    if part.startswith("import "):
                        modules |= {name.strip().split(".")[0] for name in part[len("import ") :].split(",")}
    return modules


def _cadkit_imports() -> set[str]:
    tree = ast.parse(CADKIT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return {name for name in names if name not in sys.stdlib_module_names and name != "__future__"}


def _makefile_variable(name: str) -> str:
    match = re.search(rf"^{name}\s*=\s*(\S+)\s*$", (REPO_ROOT / "Makefile").read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"Makefile defines no {name}"
    return match.group(1)


def test_the_base_image_is_the_tag_the_toggle_pins():
    toggle = _load_toggle()
    instructions = _instructions()
    args = [rest for keyword, rest in instructions if keyword == "ARG" and rest.startswith("BASE_IMAGE=")]
    assert args == [f"BASE_IMAGE={toggle.AIO_SANDBOX_IMAGE}"]
    assert [rest for keyword, rest in instructions if keyword == "FROM"] == ["${BASE_IMAGE}"]
    # `make sandbox-cad-image` passes the same tag, and builds the tag IMAGE=cad selects.
    assert _makefile_variable("SANDBOX_AIO_IMAGE") == toggle.AIO_SANDBOX_IMAGE
    assert _makefile_variable("SANDBOX_CAD_IMAGE") == toggle.CAD_SANDBOX_IMAGE == toggle.NAMED_IMAGES["cad"]
    assert f'image="${{1:-{toggle.CAD_SANDBOX_IMAGE}}}"' in (IMAGE_DIR / "smoke.sh").read_text(encoding="utf-8")


def test_the_layer_leaves_the_root_entrypoint_alone():
    """The base entrypoint starts as root, creates the shell user and drops to it."""
    instructions = _instructions()
    users = [rest for keyword, rest in instructions if keyword == "USER"]
    assert not users or users[-1] in {"root", "0", "0:0", "root:root"}, f"the image ends on USER {users[-1]}"
    overrides = [keyword for keyword, _ in instructions if keyword in {"ENTRYPOINT", "CMD"}]
    assert not overrides, f"the layer overrides {overrides}; the AIO services would not start"


def test_the_binaries_cadkit_and_the_skill_run_are_installed():
    source = CADKIT.read_text(encoding="utf-8")
    packages = _apt_packages()
    # One lookup per line; `which("a") or which("b")` names the same tool twice.
    lookups = [re.findall(r'shutil\.which\("([^"]+)"\)', line) for line in source.splitlines()]
    lookups = [names for names in lookups if names]
    assert lookups, "cadkit.py no longer looks up any program; update this test"
    for names in lookups:
        assert any(name.lower() in packages for name in names), f"cadkit.py runs {names}, which the image does not install"
    # references/openscad.md promises text() with these two font families.
    assert {"fonts-dejavu-core", "fonts-liberation2"} <= packages


def test_every_module_cadkit_needs_is_pinned_or_provided_by_the_base():
    pins = _pins()
    pinned_modules = {IMPORT_NAME.get(name, name) for name in pins}
    base_note = _requirement_comments()
    needed = {SHIPPED_WITH.get(name, name) for name in _cadkit_imports() | TRIMESH_EXTRAS}
    missing = []
    for module in sorted(needed):
        if module in pinned_modules:
            continue
        # The base image's own packages are held, not pinned, and the comment
        # in requirements.txt names each one it relies on.
        if re.search(rf"\b{re.escape(module)}\b", base_note):
            continue
        missing.append(module)
    assert not missing, f"cadkit.py needs {missing}, which requirements.txt neither pins nor names as provided by the base image"


def test_the_build_imports_what_it_installs():
    """A wheel that installs but fails to import breaks the build, not a conversation."""
    checked = _import_check_modules()
    pinned_modules = {IMPORT_NAME.get(name, name) for name in _pins()}
    # cadquery imports OCP, so importing cadquery checks both.
    assert pinned_modules - {"OCP"} <= checked, f"the build never imports {sorted(pinned_modules - {'OCP'} - checked)}"
    # The two base packages cadkit imports by name are checked too.
    assert {"matplotlib", "lxml"} <= checked


def test_requirements_are_exact_pins():
    lines = [line.strip() for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert lines
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line), f"not an exact pin: {line!r}"


def test_the_base_packages_are_held_at_their_versions():
    """The CAD wheels must not move numpy or matplotlib under the image's Jupyter."""
    pip_lines = [rest for keyword, rest in _instructions() if keyword == "RUN" and "pip install" in rest]
    assert pip_lines
    for line in pip_lines:
        assert "pip freeze" in line and re.search(r"pip install [^&]*-c \S+", line), line


def test_the_workflow_runs_on_changes_to_the_image_and_the_skill():
    # BaseLoader keeps GitHub Actions' `on` key instead of YAML 1.1's boolean True.
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    for event in ("pull_request", "push"):
        paths = workflow["on"][event]["paths"]
        for path in ("docker/sandbox-cad/**", "skills/public/cad-modeling/**", "scripts/sandbox_toggle.py", ".github/workflows/sandbox-cad-image.yml"):
            assert path in paths, f"{event} does not run on {path}"
    assert workflow["permissions"] == {"contents": "read"}
    steps = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
    assert any("make sandbox-cad-image" in run for run in steps)
    assert any("docker/sandbox-cad/smoke.sh" in run for run in steps)
