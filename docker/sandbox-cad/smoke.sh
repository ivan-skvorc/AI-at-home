#!/usr/bin/env bash
# Smoke test of the CAD sandbox image (FORK.md §58).
#
# Runs the cad-modeling skill's cadkit.py through its whole loop (render, check,
# views, print --slice, export --step --3mf) on a small two-body model inside
# the image, the way the agent runs it in a per-thread container: the repo's
# skills mounted read-only at /mnt/skills, a scratch directory at
# /mnt/user-data, the shell as uid 1000 without capabilities, and the default
# sandbox memory cap. It fails on any exit status the step does not expect, and
# on a missing output file.
#
# Usage: docker/sandbox-cad/smoke.sh [IMAGE] [REPO_ROOT]
#   IMAGE      default deerflow-sandbox-cad:local (make sandbox-cad-image)
#   REPO_ROOT  default the checkout this script lives in
#
# --entrypoint bypasses the image's run.sh, so the AIO services (browser, VNC,
# Jupyter) do not start and the run needs no published port. --network none
# shows the loop needs nothing from the network once the image is built.
set -euo pipefail

image="${1:-deerflow-sandbox-cad:local}"
repo_root="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
skills="$repo_root/skills"
cadkit=/mnt/skills/public/cad-modeling/scripts/cadkit.py

if [[ ! -f "$skills/public/cad-modeling/scripts/cadkit.py" ]]; then
  echo "ERROR: $skills/public/cad-modeling/scripts/cadkit.py not found; pass the repository root as the second argument." >&2
  exit 2
fi
if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "ERROR: image $image not found; build it with make sandbox-cad-image." >&2
  exit 2
fi

work="$(mktemp -d)"
# The thread directories are world-writable in the real sandbox
# (Paths.ensure_thread_dirs), because the container's shell is not the host user.
chmod 0777 "$work"
mkdir -m 0777 "$work/workspace" "$work/outputs"

cleanup() {
  # Files written by uid 1000 may not be removable by the host user (a CI
  # runner is uid 1001), so a container of the same uid removes them first.
  docker run --rm --network none --user 1000:1000 --entrypoint bash \
    -v "$work:/mnt/user-data" "$image" -c 'rm -rf /mnt/user-data/outputs/* /mnt/user-data/workspace/*' >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

# A plate with a through hole and a headed pin that sits in it with 0.5 mm of
# radial and vertical clearance. The print layout lays the pin head-down beside
# the plate, so both bodies print flat without supports.
cat > "$work/workspace/model.scad" <<'SCAD'
// Smoke pin and plate, v1: first draft
part = "all";
layout = "assembled";
BODIES = ["plate", "pin"];
$fn = 48;

plate_l = 40; plate_w = 30; plate_t = 5;
pin_d = 6; head_d = 10; head_t = 2;
gap = 0.5;  // radial and vertical clearance of the pin

module plate() difference() {
  cube([plate_l, plate_w, plate_t]);
  translate([20, 15, -1]) cylinder(d = pin_d + 2 * gap, h = plate_t + 2);
}

// Seated: the head floats `gap` above the plate.
module pin() translate([20, 15, gap]) {
  cylinder(d = pin_d, h = plate_t);
  translate([0, 0, plate_t]) cylinder(d = head_d, h = head_t);
}

module place(name) {
  if (layout != "print") children();
  else if (name == "pin") translate([40, 30, plate_t + head_t + gap]) rotate([180, 0, 0]) children();
  else children();
}

if (part == "plate" || part == "all") place("plate") plate();
if (part == "pin"   || part == "all") place("pin")   pin();
SCAD

# "lifted out" slides the pin up and clear; "pushed through" drives the head
# into the plate on purpose, so check must find a clash and exit 1.
cat > "$work/workspace/poses.json" <<'JSON'
{
  "poses": [
    {"name": "seated"},
    {"name": "lifted out", "sweep": {"body": "pin", "direction": [0, 0, 1], "from": 0, "to": 12, "steps": 5}}
  ],
  "ignore": [],
  "tolerance_mm3": 0.01
}
JSON
cat > "$work/workspace/clash.json" <<'JSON'
{"poses": [{"name": "pushed through", "place": {"pin": [{"translate": [0, 0, -2]}]}}], "ignore": [], "tolerance_mm3": 0.01}
JSON
chmod 0666 "$work"/workspace/*

failures=0

# run_step <expected exit> <label> <cadkit arguments...>
run_step() {
  local expected="$1" label="$2"
  shift 2
  local status=0
  echo "== $label (expect exit $expected)"
  docker run --rm --network none \
    --user 1000:1000 --cap-drop=ALL --security-opt no-new-privileges \
    --memory 2g --pids-limit 512 \
    -e HOME=/tmp -e MPLBACKEND=Agg \
    -v "$skills:/mnt/skills:ro" -v "$work:/mnt/user-data" \
    -w /mnt/user-data/workspace \
    --entrypoint python3 "$image" "$cadkit" "$@" || status=$?
  if [[ "$status" != "$expected" ]]; then
    echo "FAIL: $label exited $status, expected $expected" >&2
    failures=$((failures + 1))
  fi
}

design=/mnt/user-data/outputs/design
run_step 0 "render" render model.scad --design "$design" --print-layout
run_step 0 "check poses" check "$design" --poses poses.json --clearance 0.3
run_step 1 "check a pose that clashes" check "$design" --poses clash.json
run_step 0 "views" views "$design" --sections z=2.5,x=20
run_step 0 "print --slice" print "$design" --slice
run_step 0 "export --step --3mf" export "$design" --step --3mf
run_step 2 "render a missing file" render missing.scad --design "$design"

version="$work/outputs/design/v1"
for file in model.scad plate.stl pin.stl assembly.glb report.json check.json \
  views/shaded.png views/sections.png plate.step pin.step bodies.3mf \
  print/plate.stl print/pin.stl print/report.json print/print.json print/print.gcode; do
  if [[ ! -s "$version/$file" ]]; then
    echo "FAIL: v1/$file is missing or empty" >&2
    failures=$((failures + 1))
  fi
done
if [[ -e "$work/outputs/design/v2" ]]; then
  echo "FAIL: a failed render made a version folder (v2)" >&2
  failures=$((failures + 1))
fi

if [[ "$failures" -gt 0 ]]; then
  echo "CAD image smoke test: $failures failure(s) on $image" >&2
  exit 1
fi
echo "CAD image smoke test passed on $image"
