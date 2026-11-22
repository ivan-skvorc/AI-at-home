"""The cad-modeling skill says what the CAD module does, no more and no less.

The skill is prose a model follows; the module is code. Each can change without
the other, and a skill that teaches a construct the reader refuses costs every
conversation a wasted build. These tests read both and fail when they part.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "public" / "cad-modeling"
PACKAGE = REPO_ROOT / "examples" / "deerflow-extension-cad"
SOURCE = PACKAGE / "deerflow_extension_cad"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _allowlist():
    """The table, loaded by path: it imports nothing, so no kernel and no package are needed."""
    spec = importlib.util.spec_from_file_location("cad_allowlist_for_skill_test", SOURCE / "allowlist.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _module_text() -> str:
    return "\n".join(_read(path) for path in sorted(SOURCE.glob("*.py")))


def test_the_operations_page_is_the_allow_list():
    hint = "regenerate it: python examples/deerflow-extension-cad/deerflow_extension_cad/allowlist.py > skills/public/cad-modeling/references/operations.md"
    assert _read(SKILL / "references" / "operations.md") == _allowlist().reference(), hint


def test_the_operations_page_names_every_method_once_with_an_example():
    table = _allowlist()
    page = _read(SKILL / "references" / "operations.md")
    headings = re.findall(r"^## ([A-Za-z0-9.]+)\(", page, flags=re.MULTILINE)
    # The two calls on cq, then every method: cq.Wire.makeHelix is the path of a thread (item 59).
    assert headings == ["cq.Workplane", "cq.Wire.makeHelix", *table.METHODS]
    assert page.count("```python") == len(table.METHODS) + 2


def test_the_skill_is_named_after_its_directory_and_says_when_to_use_it():
    text = _read(SKILL / "SKILL.md")
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n", 2)[1])
    assert front["name"] == SKILL.name == "cad-modeling"
    assert "cad_build" in front["description"] and len(front["description"]) <= 1024
    # No scripts: the procedure needs the tool and the file reader, and nothing a shell would run.
    assert sorted(path.relative_to(SKILL).as_posix() for path in SKILL.rglob("*") if path.is_file()) == [
        "SKILL.md",
        "references/delegation.md",
        "references/failures.md",
        "references/fdm.md",
        "references/operations.md",
    ]


def test_the_skill_links_every_reference_and_stays_small():
    # The skill's body is read whole on every CAD conversation; the references load on demand (item 58).
    skill = SKILL / "SKILL.md"
    for reference in sorted((SKILL / "references").iterdir()):
        assert f"references/{reference.name}" in _read(skill), reference.name
    assert skill.stat().st_size <= 10 * 1024
    assert (SKILL / "references" / "fdm.md").stat().st_size <= 6 * 1024


def test_the_skill_names_the_tools_arguments_and_its_attempt_limit():
    tool = _read(SOURCE / "tool.py")
    skill = _read(SKILL / "SKILL.md")
    properties = re.search(r'"properties": \{(.*?)\n    \},', tool, flags=re.DOTALL).group(1)
    arguments = re.findall(r'^\s+"([a-z0-9_]+)": \{', properties, flags=re.MULTILINE)
    assert arguments == ["name", "script", "bbox_xyz_mm", "volume_min_max_mm3", "hole_diameters_mm", "bodies"]
    for argument in arguments:
        assert f"{argument}=" in skill, argument
    limit = int(re.search(r"^MAX_ATTEMPTS = (\d+)$", tool, flags=re.MULTILINE).group(1))
    assert f"({limit} builds in one run)" in skill
    # What the skill tells the model to read in an answer is what an answer holds.
    for field in ("error", "checks", "holes", "notes", "print", "unchecked", "expected_changed", "attempt", "next"):
        assert f"`{field}`" in skill, field
        assert re.search(rf'answer(\["{field}"\]|\.update\([^)]*\b{field}=)', tool), field


#: Words the pages quote from the module's own answers. A message reworded there is reworded here.
QUOTED = [
    "a script may contain two imports",
    "is not available: write import math",
    "a comprehension has one for and no if",
    "is outside this list",
    "has no answer: the number is outside what",
    "is a name the script is given and cannot be assigned",
    "an outline drawn earlier in the script that ends with lines, arcs",
    "loft needs two or more closed outlines",
    "sweep needs a closed outline drawn before it",
    "the axis must not cross the outline",
    "on cq a script may use cq.Workplane(...) and cq.Wire.makeHelix(...)",
    "lettering is cut into the part unless combine=True",
    "turns (height / pitch)",
    "range() takes whole numbers",
    "this loop would not run once",
    "a loop runs over range(...) or over a list",
    "is not on the allow-list",
    "a script does not export",
    "removed no material",
    "added no material",
    "left no solid",
    "there is no closed outline",
    "Call cad_build again with the same arguments",
    "Do not call cad_build again",
    "builds of this part in this run and the last one did not pass",
    "the cut ran away from the material",
    "not measured",
    "Leave this pass out",
    # A part of several bodies (item 51): the check, the way out NEXT_LOOSE gives, the notes and the fallback.
    "closed solids",
    "call cad_build again with the same name and bodies=",
    "Bodies become one part only where they overlap or share a face",
    "The smallest gap between bodies is",
    "under the printer's minimum clearance",
    "is thinner than one layer",
    "no laid-out 3MF: the bodies could not be written apart; the .3mf holds them as modelled",
    # Holes where they are, and how many edges a fillet or chamfer took (item 57).
    "nearest_at",
    "off_axis_mm",
    "lists every hole with where it is",
    "check that the selection took only the edges meant",
    # The steps after the checks (items 53 and 54), and printability's notes.
    "no picture: the build used most of its time",
    "no print check: the build used most of its time",
    "under two nozzle widths",
    "and needs support",
    "side on the bed it would be",
    "nothing flat rests on the bed: give it a flat face at the lowest z, or it needs a brim or support",
    "larger than the build volume",
    "it fits turned 90° on the bed",
    "the mesh is not watertight",
]


@pytest.mark.parametrize("phrase", QUOTED)
def test_a_message_the_failures_page_quotes_is_one_the_module_gives(phrase):
    assert phrase in _read(SKILL / "references" / "failures.md"), "the page no longer quotes it: drop it from QUOTED"
    assert phrase in _module_text(), "the module no longer says this: reword the page"


def test_the_skill_says_what_next_says_about_the_picture_and_loose_bodies():
    tool = _read(SOURCE / "tool.py")
    skill = _read(SKILL / "SKILL.md")
    # NEXT_PICTURE asks for one look, after a pass; the skill says when (step 5) and how to show it (step 7).
    assert "look at it once" in re.search(r"^NEXT_PICTURE = (.*)$", tool, flags=re.MULTILINE).group(1)
    assert "Look at it once, at review" in skill and "`![name](its path in files)`" in skill
    # NEXT_LOOSE gives bodies=N as the way out for loose bodies; the skill teaches the same argument.
    assert "bodies={solids}" in tool and "bodies=N" in skill


def _fdm_table():
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
    for column in next(iter(rows.values())):
        values = [row[column] for row in rows.values()]
        assert values == sorted(values) and len(set(values)) == len(values), column


@pytest.mark.parametrize("page", ["SKILL.md", "references/failures.md", "references/fdm.md"])
def test_a_page_names_only_methods_on_the_allow_list(page):
    """Every call in inline code, and every camelCase name in backticks, is a method the reader takes."""
    table = _allowlist()
    text = re.sub(r"```.*?```", "", _read(SKILL / page), flags=re.DOTALL)
    spans = re.findall(r"`([^`\n]+)`", text)
    calls = {name for span in spans for name in re.findall(r"(?<![\w.])([a-z]\w*)\(|(?<!math)\.([a-z]\w*)\(", span) for name in name if name}
    named = calls | {span for span in spans if re.fullmatch(r"[a-z]+[A-Z][A-Za-z]*", span)}
    functions = {name for span in spans for name in re.findall(r"\bmath\.([a-z]\w*)\(", span)}
    known = set(table.METHODS) | set(table.BUILTINS) | {"range", "makeHelix"}
    assert named and named <= known, named - known
    assert functions <= set(table.MATH_FUNCTIONS), functions - set(table.MATH_FUNCTIONS)


ALLOWED = {
    "a loop with arithmetic for the choice": "result = cq.Workplane('XY').box(80, 30, 5)\nfor i in range(6):\n    side = (-1) ** i\n    result = result.faces('>Z').workplane().pushPoints([(-30 + i * 12, side * 5)]).hole(3)\n",
    "a sign that alternates over a long loop": "result = cq.Workplane('XY').box(9, 9, 9)\nfor i in range(120):\n    side = (-1) ** i\n",
    "a feature placed from the part's origin": "result = cq.Workplane('XY').box(80, 60, 30)\nresult = result.faces('>X').workplane(origin=(0, 0, 0)).pushPoints([(0, 5)]).slot2D(12, 6).cutBlind(-2)\n",
    "a count worked out with a decimal pitch": "result = cq.Workplane('XY').box(9, 9, 9)\nfor i in range(50 // 3.5):\n    total = i\n",
    "a point taken apart in the loop header": "points = [(-10, 0), (10, 0)]\nresult = cq.Workplane('XY').box(40, 10, 2)\nfor x, y in points:\n    result = result.faces('>Z').workplane().pushPoints([(x, y)]).hole(3)\n",
    "an augmented assignment and a square root": "side = 2 ** 0.5\nside += 9\nside *= 2\nresult = cq.Workplane('XY').box(side, side, side)\n",
    # Habits of ordinary Python the reader computes itself (item 55).
    "a comprehension": "points = [(i * 10, 0) for i in range(3)]\nresult = cq.Workplane('XY').box(40, 10, 2).faces('>Z').workplane().pushPoints(points).hole(3)\n",
    "import math": "import math\nresult = cq.Workplane('XY').box(math.sqrt(2) * 10, 20 * math.sin(math.radians(30)), 2)\n",
    "indexing": "p = (12, 8)\nresult = cq.Workplane('XY').box(p[0], p[-1], 2)\n",
    "a built-in call": "n = int(7 / 2)\nresult = cq.Workplane('XY').box(max(n, 2), min(10, 20), round(2.6))\n",
    "two names in one assignment": "w, d, t = 60, 40, 6\nresult = cq.Workplane('XY').box(w, d, t)\n",
    # Operations that need no new trust (item 56): the path is an outline drawn first.
    "a sweep along a path drawn first": 'path = cq.Workplane("XZ").polyline([(0, 0), (0, 20), (20, 20)])\nresult = cq.Workplane("XY").rect(4, 4).sweep(path)\n',
    "a loft between two workplanes": "result = cq.Workplane('XY').circle(10).workplane(offset=20).circle(5).loft()\n",
    # Lettering and threads (item 59).
    "lettering cut into a face": "result = cq.Workplane('XY').box(40, 15, 3).faces('>Z').workplane().text('HELLO', 8, -0.6)\n",
    "a thread swept along a helix": (
        "helix = cq.Wire.makeHelix(1.25, 10, 3.2)\n"
        "thread = cq.Workplane('XZ').polyline([(3.2, -0.5), (4, -0.08), (4, 0.08), (3.2, 0.5)]).close().sweep(helix, isFrenet=True)\n"
        "result = cq.Workplane('XY').circle(3.25).extrude(10).union(thread)\n"
    ),
    # A part too tall for the bed, cut in two and built as two bodies (items 51 and 54).
    "a part split in two for the bed": "result = cq.Workplane('XY').box(20, 20, 300).faces('>Z').workplane(-150).split(keepTop=True, keepBottom=True)\n",
    "an angled hole from a tilted workplane": "result = cq.Workplane('XY').box(40, 40, 10).faces('>Z').workplane(origin=(0, 0, 0)).transformed(rotate=(30, 0, 0)).hole(5)\n",
}
REFUSED = {
    "an if statement": "x = 1\nif x:\n    y = 2\n",
    "a while loop": "x = 1\nwhile x:\n    x = 0\n",
    "a function": "def link(i):\n    return i\n",
    "a comprehension with an if": "points = [(i, 0) for i in range(3) if i]\n",
    "from math import": "from math import sqrt\n",
    "another import": "import numpy\n",
    "a slice": "p = (1, 2, 3)\nx = p[1:]\n",
    "a conditional expression": "x = 1 if True else 2\n",
    "an f-string": "x = f'{1}'\n",
    "a comparison": "big = 3 > 2\n",
    "a list that grows": "points = [(0, 0)]\npoints += [(1, 1)]\n",
    "a font named by the script": "result = cq.Workplane('XY').box(40, 15, 3).faces('>Z').workplane().text('HI', 8, -0.6, font='Arial')\n",
}


def _reader():
    pytest.importorskip("deerflow_extension_api", reason="the reader is part of the extension package, which needs its API")
    sys.path.insert(0, str(PACKAGE))
    try:
        from deerflow_extension_cad.interpreter import ScriptRefused, compile_script
    finally:
        sys.path.remove(str(PACKAGE))
    return compile_script, ScriptRefused


@pytest.mark.parametrize("script", ALLOWED.values(), ids=ALLOWED.keys())
def test_what_the_skill_teaches_is_what_the_reader_accepts(script):
    compile_script, _ = _reader()
    assert compile_script(script).operations


@pytest.mark.parametrize("script", REFUSED.values(), ids=REFUSED.keys())
def test_what_the_skill_rules_out_is_what_the_reader_refuses(script):
    compile_script, refused = _reader()
    with pytest.raises(refused):
        compile_script(script)
