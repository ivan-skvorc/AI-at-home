"""The gateway image must ship Camoufox's shared libraries, not just its binary.

Camoufox is the *default* `web_fetch` backend, and `backend/Dockerfile` copies
the browser into the runtime stage. That stage is `python:3.12-slim-bookworm`,
which has no GTK/X11 stack, so the browser was present and unable to execute:

    XPCOMGlueLoad error for file .../libmozgtk.so:
    libgtk-3.so.0: cannot open shared object file: No such file or directory
    Couldn't load XPCOM.

Every presence-based check passes in that state — the binary really is on disk —
so it surfaced only at agent runtime as a fetch tool that errored on every call,
on every clean build of the default deployment.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"

# The minimum set Firefox/Camoufox dlopen()s at startup in headless mode. The
# font and xvfb packages `playwright install-deps` adds are not needed headless,
# which is why this is a hand-picked list rather than that command.
REQUIRED_LIBRARIES = ("libgtk-3-0", "libasound2", "libdbus-glib-1-2", "libx11-xcb1", "libxtst6")


def _runtime_stage() -> str:
    """The Dockerfile text from the final FROM onwards."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    stages = text.split("\nFROM ")
    return stages[-1]


class TestCamoufoxRuntimeLibraries:
    def test_runtime_stage_installs_every_required_library(self):
        stage = _runtime_stage()
        missing = [lib for lib in REQUIRED_LIBRARIES if lib not in stage]
        assert not missing, f"runtime stage is missing Camoufox shared libraries: {missing}"

    def test_the_libraries_are_installed_beside_the_browser_copy(self):
        # The COPY of the browser and the apt install must live in the same
        # stage: a browser copied into a stage that cannot run it is the bug.
        stage = _runtime_stage()
        assert "/root/.cache/camoufox" in stage
        assert "libgtk-3-0" in stage
