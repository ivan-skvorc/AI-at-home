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


def test_the_unpack_follows_the_install_that_brings_libx11():
    # libX11 is the kernel's other system library; it arrives with libgtk-3-0.
    stage = _runtime_stage()
    assert stage.index("libgtk-3-0") < stage.index("dpkg-deb -x")
