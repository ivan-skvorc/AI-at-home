# The CAD sandbox image: the pinned AIO sandbox plus OpenSCAD, a slicer, fonts
# and the Python mesh and CAD libraries that the cad-modeling skill's cadkit.py
# drives (FORK.md §58). Build it with `make sandbox-cad-image` and select it
# with `make sandbox-enable MODE=container IMAGE=cad`.
#
# BASE_IMAGE must stay the tag scripts/sandbox_toggle.py pins (AIO_SANDBOX_IMAGE);
# backend/tests/test_sandbox_cad_image.py fails when the two drift.
ARG BASE_IMAGE=ghcr.io/agent-infra/sandbox:1.11.0
FROM ${BASE_IMAGE}

# The base image's entrypoint starts as root and drops to its own user, so the
# layer installs as root and leaves USER, ENTRYPOINT and CMD as they are.
USER root

# OpenSCAD renders each body, PrusaSlicer slices without supports, and the two
# font families give OpenSCAD's text() something to draw with.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openscad prusa-slicer fonts-dejavu-core fonts-liberation2 \
 && rm -rf /var/lib/apt/lists/*

# Into the image's own Python, so the agent's `python3` has them. Every package
# the image already ships is held at its version by a constraints file, so the
# CAD libraries never move numpy or matplotlib under the image's Jupyter.
COPY requirements.txt /tmp/cad-requirements.txt
RUN python3 -m pip freeze | grep -E '^[A-Za-z0-9_.-]+==' > /tmp/base-constraints.txt \
 && python3 -m pip install --no-cache-dir -c /tmp/base-constraints.txt -r /tmp/cad-requirements.txt \
 && rm /tmp/base-constraints.txt /tmp/cad-requirements.txt

# Fail the build, not the first conversation, when a tool is missing.
RUN openscad --version \
 && prusa-slicer --help > /dev/null \
 && python3 -c "import trimesh, manifold3d, shapely, rtree, matplotlib, lxml, cadquery; print('cad libraries ok')"
