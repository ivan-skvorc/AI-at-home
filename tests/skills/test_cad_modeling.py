"""The cad-modeling skill says what cadkit.py does, no more and no less.

The skill is prose a model follows; scripts/cadkit.py is the code it runs in the
CAD sandbox image (docker/sandbox-cad). Each can change without the other, and a
page that quotes a flag cadkit dropped costs every CAD conversation a failed
command. These tests read both and fail when they part. They run offline in the
backend environment: cadkit's heavy imports are lazy, so loading it needs neither
trimesh nor openscad. That the image holds every program and library cadkit uses
is backend/tests/test_sandbox_cad_image.py's to check.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shlex
import sys
import types
from pathlib import Path
from unittest import mock

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "public" / "cad-modeling"
CADKIT = SKILL / "scripts" / "cadkit.py"
PAGES = ["SKILL.md", "references/checks.md", "references/fdm.md", "references/openscad.md", "references/strength.md"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _load():
    spec = importlib.util.spec_from_file_location("cadkit_for_skill_test", CADKIT)
    module = importlib.util.module_from_spec(spec)
    # A scripts/__pycache__ would land in the committed skill tree, which the skill review scans.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


cadkit = _load()


class _Captured(Exception):
    """Carries cadkit's parser out of main() before it parses anything."""


def _cli() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """cadkit's own argparse tree: main() builds it inline, so it is caught at parse_args."""

    def capture(self, *args, **kwargs):
        raise _Captured(self)

    with mock.patch.object(argparse.ArgumentParser, "parse_args", capture):
        try:
            cadkit.main([])
        except _Captured as caught:
            parser = caught.args[0]
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    return parser, dict(commands.choices)


PARSER, COMMANDS = _cli()
FLAGS = {name: {flag for action in command._actions for flag in action.option_strings} for name, command in COMMANDS.items()}


@pytest.fixture
def numpy_only(monkeypatch):
    """cadkit's lazy import asks for numpy and trimesh; the helpers used here need numpy alone."""
    pytest.importorskip("numpy")
    monkeypatch.setitem(sys.modules, "trimesh", types.ModuleType("trimesh"))


# ---------------------------------------------------------------- the skill's shape


def test_the_skill_is_named_after_its_directory_and_says_it_needs_the_container():
    text = _read(SKILL / "SKILL.md")
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n", 2)[1])
    assert front["name"] == SKILL.name == "cad-modeling"
    description = front["description"]
    assert len(description) <= 1024 and "container" in description and "openscad" in description


def test_the_skill_holds_its_pages_and_one_script():
    assert sorted(path.relative_to(SKILL).as_posix() for path in SKILL.rglob("*") if path.is_file()) == [
        "SKILL.md",
        "references/checks.md",
        "references/fdm.md",
        "references/openscad.md",
        "references/strength.md",
        "scripts/cadkit.py",
    ]


def test_nothing_in_the_skill_names_the_retired_cad_module():
    # cad_build and its allow-list were removed with the module (FORK.md §51); scad_draft with the old design page.
    for path in sorted(p for p in SKILL.rglob("*") if p.is_file()):
        text = _read(path).lower()
        for retired in ("cad_build", "allow-list", "allowlist", "operations.md", "scad_draft"):
            assert retired not in text, f"{path.relative_to(SKILL)} names {retired}"


def test_the_skill_links_every_reference_and_stays_small():
    # The body is read whole on every CAD conversation; the references load on demand.
    skill = _read(SKILL / "SKILL.md")
    for reference in sorted((SKILL / "references").iterdir()):
        assert f"references/{reference.name}" in skill, reference.name
    assert "scripts/cadkit.py" in skill
    assert (SKILL / "SKILL.md").stat().st_size <= 10 * 1024
    assert (SKILL / "references" / "fdm.md").stat().st_size <= 7 * 1024


def test_without_the_cad_container_the_skill_says_how_to_get_one_and_stops():
    skill = _read(SKILL / "SKILL.md")
    section = re.search(r"^## Prerequisites\n(.*?)^## ", skill, flags=re.MULTILINE | re.DOTALL).group(1)
    assert "openscad --version" in section and "cadkit.py --help" in section
    assert "`make sandbox-cad-image`" in section and "`make sandbox-enable MODE=container IMAGE=cad`" in section
    assert ", and stop." in section
    # Host bash runs the model's code on the Gateway's machine; the skill may only rule it out, in the same clause.
    flat = " ".join(section.split())
    for match in re.finditer("host bash", flat):
        clause = re.split(r"[,.;:]", flat[: match.start()])[-1]
        assert "never" in clause.lower(), clause
    assert all("allow_host_bash" not in _read(SKILL / page) for page in PAGES)
    makefile = _read(REPO_ROOT / "Makefile")
    assert re.search(r"^sandbox-cad-image:", makefile, flags=re.MULTILINE) and re.search(r"^sandbox-enable:", makefile, flags=re.MULTILINE)


# ---------------------------------------------------------------- the skill and cadkit


def _quoted_commands() -> list[tuple[str, str, str]]:
    """(where, command, rest of the line) for every `cadkit.py <command> ...` in the pages and cadkit itself."""
    found = []
    for where, text in [*((page, _read(SKILL / page)) for page in PAGES), ("cadkit.py", _read(CADKIT))]:
        found += [(where, command, rest) for command, rest in re.findall(r"cadkit\.py[ \t]+([a-z]+)([^\n`\"]*)", text)]
    return found


def _flags(text: str) -> list[str]:
    """Options as a command line writes them: after a space or "[", so translate(-p) is not one."""
    return re.findall(r"(?:^|(?<=[\s\[]))(--[A-Za-z0-9][\w-]*|-[A-Za-z][\w-]*)", text)


def test_every_quoted_command_and_flag_is_one_cadkit_takes():
    quoted = _quoted_commands()
    assert {command for _, command, _ in quoted} == set(COMMANDS) == {"render", "check", "views", "print", "export", "guide", "study", "testpiece", "compare"}
    for where, command, rest in quoted:
        assert command in COMMANDS, f"{where}: cadkit.py {command}"
        for flag in _flags(rest):
            assert flag in FLAGS[command], f"{where}: cadkit.py {command} has no {flag}"


#: Flags the pages name in backticks that belong to another program.
NOT_CADKIT = {"--system-site-packages": "python3 -m venv's, named to say what a virtual environment hides"}


def test_every_flag_in_inline_code_belongs_to_one_cadkit_command():
    for page in PAGES:
        text = re.sub(r"```.*?```", "", _read(SKILL / page), flags=re.DOTALL)
        for span in re.findall(r"`([^`]+)`", text):
            flags = [flag for flag in _flags(span) if flag not in NOT_CADKIT]
            named = re.match(r"(?:cadkit\.py\s+)?([a-z]+)\s", span)
            owners = [named.group(1)] if named and named.group(1) in COMMANDS else list(COMMANDS)
            if flags:
                assert any(set(flags) <= FLAGS[owner] for owner in owners), f"{page}: `{span}`"


def _skill_command_lines() -> list[list[str]]:
    """The arguments of each cadkit command in SKILL.md's code blocks, as written; `<design>` stays a path."""
    blocks = re.findall(r"```bash\n(.*?)```", _read(SKILL / "SKILL.md"), flags=re.DOTALL)
    lines = [line for block in blocks for line in block.splitlines() if re.search(r"cadkit\.py [a-z]", line)]
    return [shlex.split(line.split("cadkit.py", 1)[1]) for line in lines]


def test_the_skill_runs_each_command_on_the_design_folder_and_cadkit_parses_it(numpy_only):
    skill = _read(SKILL / "SKILL.md")
    # The design page lists these folders; a render anywhere else is invisible to it.
    assert "/mnt/user-data/outputs/<design>/v<N>/" in skill and "/mnt/user-data/workspace/<design>/model.scad" in skill
    lines = _skill_command_lines()
    # The guide goes first so the zip that export packs holds it.
    assert [argv[0] for argv in lines] == ["render", "check", "views", "print", "guide", "export"]
    for argv in lines:
        try:
            args = PARSER.parse_args(argv)
        except SystemExit:
            pytest.fail(f"cadkit.py does not parse: {' '.join(argv)}")
        assert (args.design if args.command == "render" else args.path) == "/mnt/user-data/outputs/<design>"
        if getattr(args, "sections", None):
            assert cadkit._parse_sections(args.sections, {})
    export = PARSER.parse_args(lines[-1])
    assert export.step and export.threemf and export.zip


def test_the_commands_the_skill_names_in_its_prose_parse_on_the_design_folder(numpy_only):
    """study, testpiece and compare appear in sentences, not code blocks; each still parses as written."""
    flat = " ".join(_read(SKILL / "SKILL.md").split())
    quoted = {match.group(1): match.group(0) for match in re.finditer(r"`cadkit\.py (study|testpiece|compare) ([^`]+)`", flat)}
    assert set(quoted) == {"study", "testpiece", "compare"}
    study = PARSER.parse_args(shlex.split(quoted["study"].strip("`").split("cadkit.py", 1)[1]))
    assert study.design == "/mnt/user-data/outputs/<design>" and cadkit._parse_param(study.param, study.define)[0] == "r"
    testpiece = PARSER.parse_args(shlex.split(quoted["testpiece"].strip("`").split("cadkit.py", 1)[1]))
    assert testpiece.path == "/mnt/user-data/outputs/<design>" and testpiece.box == "x0,y0,z0,x1,y1,z1"
    compare = PARSER.parse_args(shlex.split(quoted["compare"].strip("`").split("cadkit.py", 1)[1]))
    # The editable STEP is named so that export finds its compare result and zips it.
    assert (compare.a, compare.b) == ("<body>.stl", "<body>-cq.step")
    assert "v<N>/<body>-cq.step" in flat and '"<body>-cq.compare.json"' not in flat
    assert 'f"{body}-cq.compare.json"' in _read(CADKIT) and 'f"{b_path.stem}.compare.json"' in _read(CADKIT)


def test_the_skill_states_the_exit_codes_cadkit_returns():
    skill = " ".join(_read(SKILL / "SKILL.md").split())
    assert "Exit 0 is clean, 1 means a check failed, 2 means the command could not run." in skill
    assert "Exit status: 0 pass, 1 a check failed, 2 the command could not run" in " ".join(cadkit.__doc__.split())


def _scad_blocks(page: str) -> list[str]:
    return re.findall(r"```openscad\n(.*?)```", _read(SKILL / page), flags=re.DOTALL)


def test_the_bodies_convention_the_pages_teach_is_the_one_cadkit_reads():
    blocks = _scad_blocks("SKILL.md") + _scad_blocks("references/openscad.md")
    assert len(blocks) == 2
    for block in blocks:
        bodies = cadkit._bodies_of(block, None)
        drawn = set(re.findall(r'part == "([^"]+)"', block)) - {"all"}
        assert bodies and drawn and drawn <= set(bodies), block
        assert re.search(r'^\s*part = "all";', block, flags=re.MULTILINE) and re.search(r'^\s*layout = "assembled";', block, flags=re.MULTILINE)
    template = _scad_blocks("references/openscad.md")[0]
    assert set(re.findall(r'part == "([^"]+)"', template)) - {"all"} == set(cadkit._bodies_of(template, None))
    assert set(re.findall(r'name == "([^"]+)"', template)) <= set(cadkit._bodies_of(template, None))
    # The two variables the pages say cadkit sets are the ones it passes to openscad.
    source = _read(CADKIT)
    assert "f'part=\"{name}\"'" in source and "'layout=\"print\"'" in source


def test_the_poses_example_is_one_cadkit_accepts(tmp_path, numpy_only):
    page = _read(SKILL / "references" / "checks.md")
    example = re.search(r"```json\n(.*?)```", page, flags=re.DOTALL).group(1)
    data = json.loads(example)
    named = {body for pose in data["poses"] for body in pose.get("place", {})}
    named |= {body for pose in data["poses"] if "sweep" in pose for body in pose["sweep"].get("bodies", [pose["sweep"].get("body")])}
    named |= {body for pair in data["ignore"] for body in pair}
    path = tmp_path / "poses.json"
    path.write_text(example)
    bodies = sorted(named)
    for pose in cadkit._read_poses(path, bodies)["poses"]:
        assert len(cadkit._pose_states(pose, bodies)) == pose.get("sweep", {}).get("steps", 1), pose["name"]
    assert f"Up to {cadkit.MAX_SWEEP_STEPS} steps" in page


#: Words the pages quote from cadkit's answers. A message reworded there is reworded on the page.
QUOTED = [
    "CLASH as modelled: ",
    "NOT A CLOSED SOLID",
    "separate shells",
    "top level object is empty",
    "render took longer than",
    "states, worst at [",
    "smallest gap",
    "PROBLEM",
    "held on one side only",
    "thinnest wall",
    "samples thinner than",
    "above the bed",
    "no flat face on the bed",
    "may fuse",
    "slicer:",
    "slicer says:",
    "read back as written",
    "zip not written",
    "left out of the zip",
    "passes:",
    "no value passes",
    "assigns no",
    "left out, the box misses them",
    "holds nothing of",
    "volume differs by",
    "bounding boxes by at most",
    "symmetric difference",
    "largest surface deviation",
]


@pytest.mark.parametrize("phrase", QUOTED)
def test_a_message_the_pages_quote_is_one_cadkit_gives(phrase):
    assert any(phrase in _read(SKILL / page) for page in PAGES), "no page quotes it any more: drop it from QUOTED"
    assert phrase in _read(CADKIT), "cadkit no longer says this: reword the page"


def test_the_print_defaults_fdm_md_states_are_cadkits():
    page = " ".join(_read(SKILL / "references" / "fdm.md").split())
    nozzle, layer, overhang, wall, *bed = re.search(
        r"The defaults of `cadkit.py print` match this page: a ([\d.]+) mm nozzle, ([\d.]+) mm layers, ([\d.]+) degree overhangs, ([\d.]+) mm walls, a (\d+) x (\d+) x (\d+) mm bed\.", page
    ).groups()
    assert COMMANDS["print"].get_default("overhang") == float(overhang)
    assert COMMANDS["print"].get_default("min_wall") == float(wall)
    assert cadkit._parse_bed(COMMANDS["print"].get_default("bed")) == [float(v) for v in bed]
    source = _read(CADKIT)
    assert f'"--nozzle-diameter", "{nozzle}"' in source and f'"--layer-height", "{layer}"' in source


# ---------------------------------------------------------------- fdm.md


def _fdm_table() -> dict[float, dict[str, float]]:
    """The hardware table of fdm.md as {thread size: {column: number}}."""
    page = _read(SKILL / "references" / "fdm.md")
    header = next(line for line in page.splitlines() if line.startswith("| Size |"))
    columns = [cell.strip() for cell in header.strip("|").split("|")]
    rows = {}
    for line in page.splitlines():
        match = re.match(r"^\| M(\d+(?:\.\d+)?) \|", line)
        if match:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            rows[float(match.group(1))] = {name: float(cell.split(" ")[0]) for name, cell in zip(columns[1:], cells[1:])}
    return rows


def test_every_hole_in_the_fdm_table_clears_its_metal_part():
    rows = _fdm_table()
    assert list(rows) == [2, 2.5, 3, 4, 5]
    for size, row in rows.items():
        assert size < row["Clearance, ISO 273 medium"] < row["Model at"], size
        assert row["Nut across flats, ISO 4032"] < row["Nut trap across flats"], size
        assert size < row["Insert hole"], size
        # The page's own rules: model a hole 0.2 mm over its size, a nut trap 0.3 mm over across flats.
        assert row["Model at"] == pytest.approx(row["Clearance, ISO 273 medium"] + 0.2), size
        assert row["Nut trap across flats"] == pytest.approx(row["Nut across flats, ISO 4032"] + 0.3), size
    for column in next(iter(rows.values())):
        values = [row[column] for row in rows.values()]
        assert values == sorted(values) and len(set(values)) == len(values), column
