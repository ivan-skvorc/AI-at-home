"""The gateway image must carry the three system libraries the CAD kernel links.

The CAD module (examples/deerflow-extension-cad, FORK.md §51) ships its kernel
as wheels, and the wheels do not carry ``libGL.so.1``, ``libGLX.so.0`` and
``libGLdispatch.so.0``. Without them the package is present and unable to
build: ``ImportError: libGL.so.1: cannot open shared object file``. That is the
Camoufox lesson again (test_camoufox_runtime_deps.py): presence is not proof.

``make doctor`` cannot see the image (it carries no ``scripts/``), so the image
half is pinned on the Dockerfile text. The build itself is not exercised here.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "backend" / "Dockerfile"
DISPATCH_PACKAGES = ("libglvnd0", "libglx0", "libgl1")


def _runtime_stage() -> str:
    return DOCKERFILE.read_text(encoding="utf-8").split("\nFROM ")[-1]


def _instructions(stage: str) -> list[str]:
    """RUN instructions of the stage, comments dropped and continuations joined."""
    lines = [line for line in stage.splitlines() if not line.lstrip().startswith("#")]
    return [instruction for instruction in re.sub(r"\\\n", " ", "\n".join(lines)).splitlines() if instruction.startswith("RUN ")]


def test_runtime_stage_unpacks_the_three_dispatch_libraries():
    (unpack,) = [instruction for instruction in _instructions(_runtime_stage()) if "dpkg-deb -x" in instruction]
    assert all(package in unpack for package in DISPATCH_PACKAGES)
    assert "apt-get download" in unpack and "ldconfig" in unpack


def test_the_libraries_come_without_mesa_and_llvm():
    # `apt-get install libgl1` satisfies the kernel and pulls Mesa and LLVM behind
    # libglx0, well over a hundred megabytes the kernel never loads.
    for instruction in _instructions(_runtime_stage()):
        installed = re.search(r"apt-get install\b(.*?)(&&|;|$)", instruction)
        assert not installed or not set(DISPATCH_PACKAGES) & set(installed.group(1).split()), instruction


def test_a_failed_unpack_cannot_stop_the_image_everything_else_runs_in():
    (unpack,) = [instruction for instruction in _instructions(_runtime_stage()) if "dpkg-deb -x" in instruction]
    # The module is optional. Its tool and `make doctor` name the missing library instead.
    assert re.search(r"\)\s*\|\|\s*echo \"WARNING", unpack)


def test_the_image_builds_the_test_cube_once_and_cannot_fail_on_it():
    # The step proves the kernel loads in the image and leaves its compiled modules there. It comes
    # after the libraries the kernel links, and the module is optional: the whole step is one
    # parenthesised either-or, so nothing after the warning can fail the build.
    instructions = _instructions(_runtime_stage())
    unpack = next(index for index, instruction in enumerate(instructions) if "dpkg-deb -x" in instruction)
    (warm,) = [index for index, instruction in enumerate(instructions) if "deerflow_extension_cad.selftest" in instruction]
    assert warm > unpack
    assert re.fullmatch(r"RUN cd backend && \(uv run --no-sync python -m deerflow_extension_cad\.selftest\s+\|\| echo \"WARNING[^\"]*\" >&2\)", instructions[warm].strip())
    copied = next(index for index, instruction in enumerate(_runtime_stage().splitlines()) if instruction.startswith("COPY --from=builder /app/backend"))
    assert copied < next(index for index, line in enumerate(_runtime_stage().splitlines()) if "deerflow_extension_cad.selftest" in line)


def test_the_dev_container_gets_the_kernels_libraries_too():
    # The dev stage is the builder, not the runtime stage: it inherits none of the libraries
    # above, and the module is on there as well. What the kernel maps beyond the base image is
    # libX11 (with its own dependencies) and the three dispatch libraries.
    stages = DOCKERFILE.read_text(encoding="utf-8").split("\nFROM ")
    (dev,) = [stage for stage in stages if stage.startswith("builder AS dev")]
    (libraries,) = [instruction for instruction in _instructions(dev) if "dpkg-deb -x" in instruction]
    assert re.search(r"apt-get install -y --no-install-recommends libx11-6\b", libraries)
    assert all(package in libraries for package in DISPATCH_PACKAGES) and "ldconfig" in libraries
    assert not re.search(r"apt-get install\b[^&;]*\blibgl1\b", libraries)
    assert re.search(r"\)\s*\|\|\s*echo \"WARNING", libraries)


def test_the_unpack_follows_the_install_that_brings_libx11():
    # libX11 is the kernel's other system library; it arrives with libgtk-3-0. The
    # instructions are compared, not the text: a comment that names the package is not an install.
    instructions = _instructions(_runtime_stage())
    install = next(index for index, instruction in enumerate(instructions) if re.search(r"apt-get install\b.*\blibgtk-3-0\b", instruction))
    unpack = next(index for index, instruction in enumerate(instructions) if "dpkg-deb -x" in instruction)
    assert install < unpack
