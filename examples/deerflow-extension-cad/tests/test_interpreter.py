"""The script is read, never run: what the reader accepts and what it refuses.

These tests need no CAD kernel. ``compile_script`` turns text into a list of
allow-listed operations or raises ``ScriptRefused`` with the construct and line.
"""

from __future__ import annotations

import ast
import math
import re
import time
from pathlib import Path

import pytest

from deerflow_extension_cad import allowlist
from deerflow_extension_cad.interpreter import MAX_INDENT, MAX_LOOP_DEPTH, MAX_LOOP_PASSES, MAX_NODES, MAX_OPERATIONS, MAX_SCRIPT_BYTES, MAX_WORK, Ref, ScriptRefused, compile_script

PLATE = """\
import cadquery as cq

# All dimensions in millimetres.
length = 60
width = 40
thickness = 6
hole_d = 4
hole_x = length / 4

result = (
    cq.Workplane("XY")
    .box(length, width, thickness)
    .faces(">Z")
    .workplane()
    .pushPoints([(-hole_x, 0), (hole_x, 0)])
    .hole(hole_d)
)
"""


def test_the_plate_becomes_a_list_of_allow_listed_operations():
    program = compile_script(PLATE)
    assert [op.method for op in program.operations] == ["Workplane", "box", "faces", "workplane", "pushPoints", "hole"]
    assert program.result_name == "result"
    box, points, hole = program.operations[1], program.operations[4], program.operations[5]
    # Arguments are bound to CadQuery's parameter names and evaluated to plain numbers.
    assert box.arguments == (("length", 60), ("width", 40), ("height", 6))
    assert points.arguments == (("pntList", [(-15.0, 0), (15.0, 0)]),)
    assert hole.arguments == (("diameter", 4),)
    # Every operation knows its line, so a kernel error can name it.
    assert (program.operations[0].line, box.line, hole.line) == (11, 12, 16)
    # Each call works on the result of the one before it.
    assert [op.receiver for op in program.operations] == [None, 0, 1, 2, 3, 4]
    assert program.result == 5


@pytest.mark.parametrize(
    "script",
    [
        'result = cq.Workplane("XY").box(10, 10, 10)',  # the import is optional: cq is the only name a script is given
        "import cadquery as cq\nresult = cq.Workplane().box(10, 10, 10)",
        'import cadquery as cq\nresult = cq.Workplane(inPlane="front", origin=(0, 0, 5)).cylinder(height=20, radius=5)',
        'import cadquery as cq\nr = cq.Workplane("XY").box(20, 20, 4, centered=(True, True, False)).edges("|Z").fillet(2)\nshow_object(r)',
        'import cadquery as cq\nbase = cq.Workplane("XY").box(40, 40, 6)\nrib = cq.Workplane("XY").box(6, 40, 20).translate((0, 0, 13))\nresult = base.union(rib)',
        'import cadquery as cq\nn = 3\npitch = 12.5\nresult = cq.Workplane("XY").box(60, 40, 6).faces(">Z").workplane().rarray(pitch, pitch, n, n - 1).hole(3.2, depth=None)',
        'import cadquery as cq\n"""A bracket."""\nt = 2 ** 2 + 10 % 3 - 7 // 2\nresult = cq.Workplane("XY").polyline([(0, 0), (40, 0), (40, t), (t, t), (t, 30), (0, 30)]).close().extrude(20)',
        'import cadquery as cq\nresult = cq.Workplane("XY").box(30, 30, 30).faces(">Z").shell(-2, kind="intersection")\n',
        'import cadquery as cq\r\nresult = cq.Workplane("XY").box(1, 1, 1)  # Ø, ° and other signs are fine in a comment\r\n',
        'import cadquery as cq\nw = 10\nw += 5\nw -= 1\nw *= 2\nw /= 4\nw //= 2\nw **= 2\nw %= 7\nresult = cq.Workplane("XY").box(w, w, w)\n',
        'result = cq.Workplane("XY").box(40, 10, 2)\nfor x, y in [(-10, 0), (10, 0)]:\n    # one hole per point\n    result = (\n        result.faces(">Z")\n        .workplane()\n        .pushPoints([(x, y)])\n        .hole(3)\n    )\n',
        # Item 56: a path to sweep along is an outline drawn earlier, on its own workplane or on a face of a part.
        "path = cq.Workplane('XZ').polyline([(0, 0), (0, 20), (20, 20)])\nresult = cq.Workplane('XY').rect(4, 4).sweep(path, transition='round')\n",
        "ring = cq.Workplane('XZ').circle(20)\nresult = cq.Workplane('XY').center(20, 0).circle(3).sweep(ring)\n",
        "base = cq.Workplane('XY').box(40, 40, 4)\nrail = base.faces('>Z').workplane().spline([(0, 0), (5, 10), (0, 20)])\nresult = cq.Workplane('XY').circle(1).sweep(rail, isFrenet=True)\n",
        "result = cq.Workplane('XY').rect(20, 20).workplane(offset=15).circle(6).loft(ruled=True, combine=True)\n",
        "result = cq.Workplane('XY').box(40, 40, 10).faces('>Z').workplane().transformed(rotate=(30, 0, 0), offset=(5, 0, 0)).hole(5)\n",
    ],
)
def test_ordinary_scripts_are_accepted(script):
    program = compile_script(script)
    assert program.operations and program.operations[program.result].method in allowlist.METHODS


#: Habits models bring from ordinary Python, each beside the same program written out (item 55).
#: The reader computes every number itself, so a habit adds nothing a script could not already say.
HABITS = {
    "names assigned together": ("w, d, t = 60, 40, 6\nresult = cq.Workplane('XY').box(w, d, t)\n", "w = 60\nd = 40\nt = 6\nresult = cq.Workplane('XY').box(w, d, t)\n"),
    "names swapped": ("a, b = 4, 9\na, b = b, a\nresult = cq.Workplane('XY').box(a, b, 1)\n", "result = cq.Workplane('XY').box(9, 4, 1)\n"),
    "a point taken apart": ("p = (30, 20)\nx, y = p\nresult = cq.Workplane('XY').box(x, y, 2)\n", "result = cq.Workplane('XY').box(30, 20, 2)\n"),
    "two parts at once": (
        "a, b = cq.Workplane('XY').box(4, 4, 4), cq.Workplane('XY').sphere(3)\nresult = a.intersect(b)\n",
        "a = cq.Workplane('XY').box(4, 4, 4)\nb = cq.Workplane('XY').sphere(3)\nresult = a.intersect(b)\n",
    ),
    "math functions": (
        "import math\nr = 20\nresult = cq.Workplane('XY').box(r * math.cos(math.radians(60)), math.sqrt(2) * 10, math.hypot(3, 4)).rotate((0, 0, 0), (0, 0, 1), math.degrees(math.atan2(1, 1)))\n",
        f"result = cq.Workplane('XY').box({20 * math.cos(math.radians(60))!r}, {math.sqrt(2) * 10!r}, 5.0).rotate((0, 0, 0), (0, 0, 1), {math.degrees(math.atan2(1, 1))!r})\n",
    ),
    "math constants, floor and ceil": (
        "import math\nresult = cq.Workplane('XY').box(math.floor(math.pi * 10), math.ceil(math.tau), math.asin(1) + math.acos(1) + math.atan(0) + math.tan(0))\n",
        f"result = cq.Workplane('XY').box(31, 7, {math.pi / 2!r})\n",
    ),
    "math without its import": ("result = cq.Workplane('XY').box(math.pi, 1, 1)\n", f"result = cq.Workplane('XY').box({math.pi!r}, 1, 1)\n"),
    "the built-ins on numbers": ("a = 4\nresult = cq.Workplane('XY').box(max(a, 10, 2), min(a, 10), abs(-3) + int(2.9) + float(1) + round(2.4) + round(0.123456, 3))\n", "result = cq.Workplane('XY').box(10, 4, 8.123)\n"),
    "the built-ins on a list": ("sizes = [12, 30, 7.5]\nresult = cq.Workplane('XY').box(max(sizes), min(sizes), len(sizes))\n", "result = cq.Workplane('XY').box(30, 7.5, 3)\n"),
    "an index": ("pts = [(10, 0), (0, 20)]\nresult = cq.Workplane('XY').box(pts[0][0], pts[-1][1], (1, 2, 3)[0])\n", "result = cq.Workplane('XY').box(10, 20, 1)\n"),
    "a comprehension over a range": (
        "result = cq.Workplane('XY').box(60, 60, 4).faces('>Z').workplane().pushPoints([(20 * i - 20, 0) for i in range(3)]).hole(3)\n",
        "result = cq.Workplane('XY').box(60, 60, 4).faces('>Z').workplane().pushPoints([(-20, 0), (0, 0), (20, 0)]).hole(3)\n",
    ),
    "a comprehension over a list, taking points apart": (
        "pts = [(x, y * 2) for x, y in [(5, 1), (-5, 2)]]\nresult = cq.Workplane('XY').box(30, 30, 4).faces('>Z').workplane().pushPoints(pts).hole(2)\n",
        "result = cq.Workplane('XY').box(30, 30, 4).faces('>Z').workplane().pushPoints([(5, 2), (-5, 4)]).hole(2)\n",
    ),
    "a comprehension that leaves its name alone": ("y = 7\nys = [y for y in (1, 2)]\nresult = cq.Workplane('XY').box(y, max(ys), 1)\n", "result = cq.Workplane('XY').box(7, 2, 1)\n"),
}


@pytest.mark.parametrize(("habit", "written_out"), HABITS.values(), ids=HABITS.keys())
def test_a_habit_from_ordinary_python_is_the_same_program_as_its_numbers_written_out(habit, written_out):
    assert _shape(compile_script(habit)) == _shape(compile_script(written_out))


def test_a_sine_is_computed_by_the_reader_to_the_last_digit():
    program = compile_script("import math\nx = 20 * math.sin(math.radians(30))\nresult = cq.Workplane('XY').box(x, 1, 1)\n")
    assert abs(dict(program.operations[1].arguments)["length"] - 10) <= 1e-9


def test_the_numbers_table_is_closed_and_every_name_in_it_is_reserved():
    from deerflow_extension_cad import interpreter

    assert set(allowlist.MATH_CONSTANTS) == {"pi", "tau"}
    assert set(allowlist.MATH_FUNCTIONS) == {"sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sqrt", "hypot", "radians", "degrees", "floor", "ceil"}
    assert set(allowlist.BUILTINS) == {"abs", "min", "max", "round", "int", "float", "len"}
    # What the table names, the reader computes with its own functions: none is looked up on a module.
    assert set(interpreter._MATH) == set(allowlist.MATH_FUNCTIONS) and set(interpreter._BUILTIN) == set(allowlist.BUILTINS)
    assert {"math", *allowlist.BUILTINS} <= set(interpreter._RESERVED)


def test_the_numbers_a_script_starts_with_are_its_parameters():
    """Top-level numbers assigned once before the first operation: what a follow-up edit changes."""
    script = "import math\nw, d, t = 60, 40, 6\nhole = 4.2\nhalf = w / 2\nplane = 'XY'\nflag = True\npitch = 10\npitch += 2\ncount = 3\nresult = cq.Workplane(plane).box(w, d, t)\nlate = 5\nfor count in range(2):\n    inner = count\n"
    assert compile_script(script).parameters == (("w", 60), ("d", 40), ("t", 6), ("hole", 4.2), ("half", 30.0))
    assert compile_script("result = cq.Workplane('XY').box(1, 1, 1)\n").parameters == ()


@pytest.mark.parametrize(
    ("script", "name"),
    [
        ("result = cq.Workplane('XY').box(1, 1, 1).sketch()\n", "sketch"),
        ("for i in range(2):\n    r = cq.Workplane('XY').box(1, 1, 1).sketch()\n", "sketch"),
        ("import os\n", "import os"),
        ("import cadquery as os\n", "import cadquery as os"),
        ("from math import *\n", "from math import *"),
        ("x = open('/etc/passwd')\n", "open"),
        ("x = cq.Assembly()\n", "cq.Assembly"),
        ("x = math.system\n", "math.system"),
        ("r = cq.Workplane('XY').box(1, 1, 1)\nx = r.objects\n", ".objects"),
        ("if True:\n    x = 1\n", "if statement"),
        ("r = cq.Workplane('XY').box(0, 1, 1)\n", "box"),
        ("result = cq.Workplane('XY').box(1, 1, 1)\nresult.export('x.step')\n", "export"),
        ("x = [i for i in range(3) if i]\n", "comprehension"),
        ("math = 3\n", "math"),
        ("x = math.sqrt(-1)\n", "math.sqrt"),
    ],
)
def test_a_refusal_names_what_it_refused(script, name):
    with pytest.raises(ScriptRefused) as refused:
        compile_script(script)
    assert refused.value.name == name


def test_a_refusal_inside_a_comprehension_says_which_item():
    with pytest.raises(ScriptRefused) as refused:
        compile_script("x = [1 / (i - 2) for i in range(4)]\n")
    assert (refused.value.construct, refused.value.line) == ("arithmetic", 1)
    assert refused.value.message == "division by zero (in item 3 of the list on line 1 (i = 2))"


def test_a_comprehension_is_bounded_by_the_work_of_reading_it():
    """A comprehension makes a list and no operations, so loop passes do not bound it: the work does."""
    # Ten passes of a loop over a comprehension of comprehensions: a million items read in all.
    script = "for i in range(10):\n    grid = [[j for j in range(400)] for k in range(250)]\n"
    started = time.perf_counter()
    with pytest.raises(ScriptRefused) as refused:
        compile_script(script)
    assert time.perf_counter() - started < 3
    assert refused.value.construct == "script length" and "more work" in refused.value.message
    # One longer than a list may be is refused before its first item.
    started = time.perf_counter()
    with pytest.raises(ScriptRefused) as refused:
        compile_script("x = [i for i in range(10 ** 6)]\n")
    assert time.perf_counter() - started < 0.1 and "at most 400" in refused.value.message


def test_names_are_data_so_a_script_may_call_its_variables_anything_but_cq():
    # A name is only ever looked up in the script's own table. Nothing a script
    # assigns can shadow a builtin or a method, because neither is ever resolved by name.
    program = compile_script("print = cq.Workplane('XY').box(1, 1, 1)\nunion = print\nopen = 5\nresult = union.union(cq.Workplane('XY').sphere(open))\n")
    assert [op.method for op in program.operations] == ["Workplane", "box", "Workplane", "sphere", "union"]


def test_the_part_is_result_then_the_shown_object_then_the_last_part_assigned():
    two = 'a = cq.Workplane("XY").box(1, 1, 1)\nb = cq.Workplane("XY").box(2, 2, 2)\n'
    assert compile_script(two).result_name == "b"
    assert compile_script(two + "show_object(a)\n").result_name == "a"
    assert compile_script("result = " + two[4:] + "show_object(result)\n").result_name == "result"
    # Two answers to "which is the part" are refused: `result` held the blank, show_object the drilled one.
    with pytest.raises(ScriptRefused) as two_answers:
        compile_script("result = " + two[4:] + "show_object(b)\n")
    assert (two_answers.value.construct, two_answers.value.line) == ("result", 3)


def test_the_part_is_what_was_built_not_what_its_name_holds_later():
    box, sphere = "cq.Workplane('XY').box(1, 1, 1)", "cq.Workplane('XY').sphere(3)"

    def built(script: str) -> str:
        program = compile_script(script)
        return program.operations[program.result].method

    # A name reused for a number does not take the part with it.
    assert built(f"plate = {box}\nplate = 6\n") == "box"
    # show_object shows what the name held when it was called, as it does in Python.
    assert built(f"a = {box}\nshow_object(a)\na = {sphere}\n") == "box"
    assert built(f"a = {box}\nshow_object(a)\na = 5\n") == "box"
    # `result` is the part by name, so it has to end as one.
    for last in ("None", "6", "(1, 2)"):
        with pytest.raises(ScriptRefused) as refused:
            compile_script(f"result = {box}\nresult = {last}\n")
        assert (refused.value.construct, refused.value.line) == ("result", 2)


REFUSED = [
    # (script, construct the refusal names, line)
    ("import os\n", "import", 1),
    ("import cadquery\n", "import", 1),
    ("import cadquery as os\n", "import", 1),
    ("import cadquery as cq, os\n", "import", 1),
    ("from cadquery import *\n", "import", 1),
    ("import cadquery.importers as cq\n", "import", 1),
    ("x = 1\nfrom . import y\n", "import", 2),
    ("x = cq.exporters\n", "attribute", 1),
    ("x = cq.importers.importStep('/etc/passwd')\n", "attribute", 1),
    ("x = cq.Workplane.__init__.__globals__\n", "attribute", 1),
    ("x = cq.Assembly()\n", "call", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1)\nx = r.objects\n", "attribute", 2),
    ("r = cq.Workplane('XY').box(1, 1, 1)\nx = r.val().wrapped\n", "attribute", 2),
    ("r = cq.Workplane('XY').box(1, 1, 1).__class__\n", "attribute", 1),
    ("x = (1).real\n", "attribute", 1),
    ("x = open('/etc/passwd')\n", "call", 1),
    ("x = __import__('os')\n", "call", 1),
    ("x = getattr(cq, 'exporters')\n", "call", 1),
    ("x = eval('1')\n", "call", 1),
    ("print(1)\n", "call", 1),
    ("x = '{0.__class__}'.format(cq)\n", "attribute", 1),
    ("x = ', '.join(['a'])\n", "attribute", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).val()\n", "method", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).exportSvg('/tmp/x.svg')\n", "export", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).export('/tmp/x.step')\n", "export", 1),
    ("r = cq.Workplane('XY').text('hi', 10, 1, fontPath='/etc/passwd')\n", "method", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).each(lambda s: s)\n", "lambda", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).eachpoint(cq.Workplane('XY'))\n", "method", 1),
    ("r = cq.Workplane('XY').sketch()\n", "method", 1),
    ("r = cq.Workplane('XY').box(*[1, 1, 1])\n", "starred argument", 1),
    ("r = cq.Workplane('XY').box(**{'length': 1})\n", "keyword unpacking", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1, obj=1)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1, length=2)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1, True, True, True, 9)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, '1')\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, cq.Workplane('XY'))\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).union(5)\n", "argument", 1),
    ("r = cq.Workplane('/etc/passwd')\n", "argument", 1),
    ("r = cq.Workplane('XY', obj=1)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).faces('>Z; import os')\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).faces('__class__')\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).tag('a b')\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).shell(-1, kind='tangent')\n", "argument", 1),
    ("r = cq.Workplane('XY').box(0, 1, 1)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(-1, 1, 1)\n", "argument", 1),
    ("r = cq.Workplane('XY').polygon(2.5, 10)\n", "argument", 1),
    ("x = lambda: 1\n", "lambda", 1),
    ("x = (i for i in (1, 2))\n", "comprehension", 1),
    ("x = 1 if 2 else 3\n", "conditional expression", 1),
    ("x = (y := 1)\n", "assignment expression", 1),
    ("y = 1\nx = f'{y}'\n", "f-string", 2),
    ("x = '%s' % 1\n", "arithmetic", 1),
    ("x = 'a' + 'b'\n", "arithmetic", 1),
    ("x = 'a' * 3\n", "arithmetic", 1),
    ("x = [0] * 3\n", "arithmetic", 1),
    ("x = 1 < 2\n", "comparison", 1),
    ("x = 1 and 2\n", "boolean operator", 1),
    ("x = not 1\n", "operator", 1),
    ("x = ~1\n", "operator", 1),
    ("x = 1 << 2\n", "operator", 1),
    ("x = 1 @ 2\n", "operator", 1),
    ("x = b'a'\n", "literal", 1),
    ("x = 1j\n", "literal", 1),
    ("x = ...\n", "literal", 1),
    ("x = {1, 2}\n", "set", 1),
    ("x = {'a': 1}\n", "dict", 1),
    ("def f():\n    return 1\n", "function definition", 1),
    ("class A:\n    pass\n", "class definition", 1),
    ("while True:\n    x = 1\n", "while loop", 1),
    ("for i in range(3):\n    x = i\nelse:\n    y = 1\n", "loop", 4),
    ("for i in range(3):\n    break\n", "break", 2),
    ("for i in range(3):\n    continue\n", "continue", 2),
    ("for i in range(3):\n    if i:\n        x = 1\n", "if statement", 2),
    ("for i in range(2.5):\n    x = i\n", "loop", 1),
    ("n = 15 / 2\nfor i in range(n):\n    x = i\n", "loop", 2),
    ("for i in range(True):\n    x = i\n", "loop", 1),
    ("for () in [(1, 2)]:\n    x = 1\n", "loop", 1),
    ("for i in (range(2)\n): x = i\n", "syntax", 2),
    ("for i in range(2) \\\n: x = i\n", "syntax", 2),
    ("for i in range(2):\\\nx = i\n", "syntax", 2),
    ("for i in range(2):\n    x = i\n    \\\ny = i\n", "syntax", 4),
    ("x = (1 +\n 2); y = 3\n", "syntax", 2),
    ("for i in range():\n    x = i\n", "loop", 1),
    ("for i in range(1, 2, 3, 4):\n    x = i\n", "loop", 1),
    ("for i in range(stop=3):\n    x = i\n", "loop", 1),
    ("for i in range(0, 5, 0):\n    x = i\n", "loop", 1),
    ("for i in range(0):\n    x = i\n", "loop", 1),
    ("for i in range(5, 0):\n    x = i\n", "loop", 1),
    ("for i in []:\n    x = i\n", "loop", 1),
    ("for i in 5:\n    x = i\n", "loop", 1),
    ("for i in 'abc':\n    x = i\n", "loop", 1),
    ("for i in enumerate([1, 2]):\n    x = i\n", "loop", 1),
    ("for i, j in zip([1], [2]):\n    x = i\n", "loop", 1),
    ("p = cq.Workplane('XY').box(1, 1, 1)\nfor i in p:\n    x = i\n", "loop", 2),
    ("for i in p.vals():\n    x = i\n", "name", 1),
    ("for x, y in [1, 2]:\n    z = x\n", "loop", 1),
    ("for x, y in [(1, 2, 3)]:\n    z = x\n", "loop", 1),
    ("for (a, b), c in [(1, 2)]:\n    z = c\n", "loop", 1),
    ("for x[0] in [1, 2]:\n    z = 1\n", "subscript", 1),
    ("for cq in range(2):\n    z = 1\n", "name", 1),
    ("for range in [1, 2]:\n    z = 1\n", "name", 1),
    ("for __x__ in range(2):\n    z = 1\n", "name", 1),
    ("for i in range(2): x = i\n", "syntax", 1),
    ("for i in range(2):\n    x = i; y = i\n", "syntax", 2),
    ("async def f():\n    async for i in x:\n        y = 1\n", "function definition", 1),
    ("x = range(3)\n", "call", 1),
    ("range = 3\n", "name", 1),
    ("x += 1\n", "name", 1),
    ("p = cq.Workplane('XY').box(1, 1, 1)\np += 1\n", "arithmetic", 2),
    ("x = 1\nx |= 1\n", "operator", 2),
    ("x = [1]\nx[0] += 1\n", "subscript", 2),
    ("x = 1\nx /= 0\n", "arithmetic", 2),
    ("if True:\n    x = 1\n", "if statement", 1),
    ("with cq as x:\n    y = 1\n", "with statement", 1),
    ("try:\n    x = 1\nexcept Exception:\n    x = 2\n", "try statement", 1),
    ("raise ValueError\n", "raise", 1),
    ("assert True\n", "assert", 1),
    ("x = 1\ndel x\n", "del", 2),
    ("global x\n", "global", 1),
    ("pass\n", "pass", 1),
    ("x: int = 1\n", "annotated assignment", 1),
    ("a = b = 1\n", "assignment target", 1),
    ("cq.x = 1\n", "assignment target", 1),
    ("x = [1]\nx[0] = 2\n", "subscript", 2),
    ("cq = 1\n", "name", 1),
    ("__builtins__ = 1\n", "name", 1),
    ("x = undefined_name\n", "name", 1),
    ("x = cq\n", "name", 1),
    ("x = 1\nshow_object(x)\n", "show_object", 2),
    ("show_object(cq.Workplane('XY').box(1, 1, 1))\n", "show_object", 1),
    ("1 + 1\n", "expression statement", 1),
    ("x = 9 ** 9 ** 9\n", "arithmetic", 1),
    ("x = 10 ** 100000\n", "arithmetic", 1),
    ("x = 1e11 * 1e11\n", "arithmetic", 1),
    ("x = 1e308\n", "number", 1),
    ("x = 1 / 0\n", "arithmetic", 1),
    ("x = 5 % 0\n", "arithmetic", 1),
    ("x = 123456789012345678901234567890\n", "number", 1),
    ("x = " + "9" * 400 + "\n", "number", 1),  # too large to be a float at all
    ("x = 0x" + "f" * 400 + "\n", "number", 1),
    ("x = (10 ** 11) ** 64\n", "arithmetic", 1),
    ("x = 10 ** 11\ny = x * x * x\n", "arithmetic", 2),
    ("x = 1e999\n", "number", 1),
    ("r = cq.Workplane('XY').box(10 ** 9, 1, 1)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).faces('>Z').workplane().rarray(1, 1, 1000, 1000).hole(0.5)\n", "pattern", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).faces('>Z').workplane().polarArray(10, 0, 360, 10 ** 6).hole(0.5)\n", "argument", 1),
    # A regular polygon is not a way to put ten thousand points on the stack.
    ("r = cq.Workplane('XY').polygon(10000, 150, forConstruction=True).vertices()\n", "argument", 1),
    ("r = cq.Workplane('XY').polygon(101, 150).extrude(1)\n", "argument", 1),
    # The usual last line of a CadQuery script: the tool writes the files, the script does not.
    ("result = cq.Workplane('XY').box(1, 1, 1)\ncq.exporters.export(result, 'plate.step')\n", "export", 2),
    ("result = cq.Workplane('XY').box(1, 1, 1)\nresult.export('plate.step')\n", "export", 2),
    ("result = cq.Workplane('XY').box(1, 1, 1)\nx = cq.exporters.export(result, 'plate.step')\n", "export", 2),
    ("result = cq.Workplane('XY').box(1, 1, 1).toSvg()\n", "export", 1),
    ("a = cq.Assembly()\n", "call", 1),
    ("result = cq.Workplane('XY').box(1, 1, 1)\nresult.val().exportStep('plate.step')\n", "export", 2),
    ("result = cq.Workplane('XY').box(1, 1, 1)\nresult.faces('>Z')\n", "expression statement", 2),
    # The line is the one a reader would point at, inside a call that spans several.
    ("result = (\n    cq.Workplane('XY')\n    .box(1, 1, 1)\n    .objects\n)\n", "attribute", 4),
    ("result = cq.Workplane('XY').box(\n    1, 1, 1,\n    centered=True,\n    bogus=1,\n)\n", "argument", 4),
    ("result = cq.Workplane('XY').box(\n    1,\n    'wide',\n    1,\n)\n", "argument", 3),
    ("p = [\n    (0, 0),\n    (1, 1),\n    'a',\n]\n", "sequence", 4),
    # centered takes one flag per axis of the thing it centres.
    ("r = cq.Workplane('XY').box(1, 1, 1, centered=(True, False))\n", "argument", 1),
    ("r = cq.Workplane('XY').rect(1, 1, centered=(True, False, True)).extrude(1)\n", "argument", 1),
    ("x = (-8) ** 0.5\n", "arithmetic", 1),
    # One statement per line, and no line so long that its end is off the screen: a second
    # statement far to the right of the visible one would otherwise decide the part.
    ("a = 1; b = 2\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 1),
    ("result = cq.Workplane('XY').box(10, 10, 10)" + " " * 300 + "; result = cq.Workplane('XY').box(99, 99, 99)\n", "syntax", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1)\nx = " + "1 + " * 300 + "1\n", "syntax", 2),
    ("x = 1\n\x00y = 2\n", "syntax", 2),
    # What a viewer shows as one line must be what the parser reads as one line.
    ("x = 1\n\x0cy = 2\n", "syntax", 2),
    ("x = 1\n# a comment\ry = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 2),
    ("x = 1\x0b\n", "syntax", 1),
    ("x = 1  # \x7f\n", "syntax", 1),
    ("x = 1  # \x1b[31m\n", "syntax", 1),
    # The same for characters that reorder what a viewer draws, or break a line for it.
    ("x = 1\n# a plate \u202e 4 mm holes\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 2),
    ("# \u2067 right to left\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 1),
    ("# a comment\u2028r = cq.Workplane('XY').box(2, 2, 2)\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 1),
    ("# a\u2029b\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 1),
    ("# a\u0085b\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 1),
    ("# \ud800\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", 1),
    # Padding that pushes code out of sight: sideways within a line, or down past a screenful of blank lines.
    ("result = cq.Workplane('XY').box(10, 10, 10)" + " " * 60 + ".union(cq.Workplane('XY').box(99, 99, 99))\n", "syntax", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1)\n" + "\n" * 60 + "r = cq.Workplane('XY').box(9, 9, 9)\n", "syntax", 2),
    ("x = (1\n", "syntax", 1),
    ("x = 1\n  y = 2\n", "syntax", 2),
    ("async def f():\n    await g()\n", "function definition", 1),
    ("x = yield\n", "yield", 1),
    ("match x:\n    case 1:\n        y = 1\n", "match statement", 1),
    ("type X = int\n", "type alias", 1),
    ("@decorator\ndef f():\n    pass\n", "function definition", 2),
    # What item 55 admits, and no further: the math table, the seven built-ins, an index, a comprehension, a tuple of names.
    ("math = 3\n", "name", 1),
    ("min = 2\n", "name", 1),
    ("for len in range(2):\n    x = 1\n", "name", 1),
    ("a, math = 1, 2\n", "name", 1),
    ("x = math.system\n", "attribute", 1),
    ("x = math.system('ls')\n", "call", 1),
    ("x = math.__dict__\n", "attribute", 1),
    ("x = math.sin.__call__(1)\n", "attribute", 1),
    ("x = math.e\n", "attribute", 1),
    ("x = math.inf\n", "attribute", 1),
    ("x = math.sin\n", "attribute", 1),
    ("x = math\n", "name", 1),
    ("x = abs\n", "name", 1),
    ("x = getattr(math, 'sin')\n", "call", 1),
    ("x = sorted([2, 1])\n", "call", 1),
    ("from math import *\n", "import", 1),
    ("from math import sin\n", "import", 1),
    ("import math as m\n", "import", 1),
    ("import math, os\n", "import", 1),
    ("import math.sys\n", "import", 1),
    ("p = (1, 2, 3)\nx = p[1:2]\n", "slice", 2),
    ("p = (1, 2, 3)\nx = p[3]\n", "subscript", 2),
    ("p = (1, 2, 3)\nx = p[-4]\n", "subscript", 2),
    ("p = (1, 2, 3)\nx = p[1.0]\n", "subscript", 2),
    ("p = (1, 2, 3)\nx = p[True]\n", "subscript", 2),
    ("p = (1, 2, 3)\nx = p[0, 1]\n", "subscript", 2),
    ("x = 'XY'[0]\n", "subscript", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1)\nx = r[0]\n", "subscript", 2),
    ("x = math.sqrt(-1)\n", "arithmetic", 1),
    ("x = math.acos(2)\n", "arithmetic", 1),
    ("x = math.tan(math.pi / 2)\n", "arithmetic", 1),
    ("x = int(1e400)\n", "number", 1),
    ("x = math.sin(1, 2)\n", "call", 1),
    ("x = math.atan2(1)\n", "call", 1),
    ("x = math.sin(x=1)\n", "call", 1),
    ("x = math.sin('1')\n", "call", 1),
    ("x = math.sin((1, 2))\n", "call", 1),
    ("x = min()\n", "call", 1),
    ("x = min([])\n", "call", 1),
    ("x = min(5)\n", "call", 1),
    ("x = min([(1, 2), (3, 4)])\n", "call", 1),
    ("x = max(1, 2, key=3)\n", "call", 1),
    ("x = len(5)\n", "call", 1),
    ("x = len('abc')\n", "call", 1),
    ("x = int('5')\n", "call", 1),
    ("x = float('inf')\n", "call", 1),
    ("x = abs(True)\n", "call", 1),
    ("x = round(5, -10 ** 9)\n", "call", 1),
    ("x = round(1.5, 0.5)\n", "call", 1),
    ("x = [i for i in range(3) if i]\n", "comprehension", 1),
    ("x = [i for i in range(3) for j in range(2)]\n", "comprehension", 1),
    ("x = [i for i in 'abc']\n", "comprehension", 1),
    ("x = [i for i in range(2.5)]\n", "comprehension", 1),
    ("x = [i for i in []]\n", "comprehension", 1),
    ("x = [i for i in range(10 ** 6)]\n", "comprehension", 1),
    ("x = [a for (a, b), c in [(1, 2)]]\n", "comprehension", 1),
    ("x = [i for cq in range(3)]\n", "name", 1),
    ("x = {i for i in range(3)}\n", "comprehension", 1),
    ("x = {i: i for i in range(3)}\n", "comprehension", 1),
    ("x = [cq.Workplane('XY').box(i + 1, 1, 1) for i in range(3)]\n", "sequence", 1),
    ("x = [y for y in range(3)]\nz = y\n", "name", 2),
    ("a, b = 1, 2, 3\n", "assignment target", 1),
    ("p = (1, 2, 3)\na, b = p\n", "assignment target", 2),
    ("a, b = 5\n", "assignment target", 1),
    ("(a, b), c = (1, 2), 3\n", "assignment target", 1),
    ("[a, b] = 1, 2\n", "assignment target", 1),
    ("a, b.c = 1, 2\n", "assignment target", 1),
    ("a, *b = 1, 2, 3\n", "starred argument", 1),
    # Item 56: sweep's path is an outline drawn earlier, and nothing reaches the kernel's other modes.
    ("path = cq.Workplane('XY').box(5, 5, 5)\nr = cq.Workplane('XY').rect(4, 4).sweep(path)\n", "argument", 2),
    ("path = cq.Workplane('XZ').moveTo(0, 20)\nr = cq.Workplane('XY').rect(4, 4).sweep(path)\n", "argument", 2),
    ("path = cq.Workplane('XZ').polyline([(0, 0), (0, 20)]).translate((1, 0, 0))\nr = cq.Workplane('XY').rect(4, 4).sweep(path)\n", "argument", 2),
    ("r = cq.Workplane('XY').rect(4, 4).sweep(5)\n", "argument", 1),
    ("r = cq.Workplane('XY').rect(4, 4).sweep()\n", "argument", 1),
    ("path = cq.Workplane('XZ').polyline([(0, 0), (0, 20)])\nr = cq.Workplane('XY').rect(4, 4).sweep(path, transition='bogus')\n", "argument", 2),
    ("path = cq.Workplane('XZ').polyline([(0, 0), (0, 20)])\nr = cq.Workplane('XY').rect(4, 4).sweep(path, normal=(0, 0, 1))\n", "argument", 2),
    ("path = cq.Workplane('XZ').polyline([(0, 0), (0, 20)])\nr = cq.Workplane('XY').rect(4, 4).sweep(path, auxSpine=path)\n", "argument", 2),
    ("r = cq.Workplane('XY').circle(5).workplane(offset=5).circle(3).loft(combine='cut')\n", "argument", 1),
    ("r = cq.Workplane('XY').rect(4, 4).revolve(combine='s')\n", "argument", 1),
    ("r = cq.Workplane('XY').rect(4, 4).offset2D(1, kind='tangent')\n", "argument", 1),
    ("r = cq.Workplane('XY').spline([(0, 0), (1, 1)], tol=0.1)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).end(0)\n", "argument", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).split(keepTop=True)\n", "method", 1),
    ("r = cq.Workplane('XY').parametricCurve(lambda t: (t, t))\n", "lambda", 1),
]


@pytest.mark.parametrize(("script", "construct", "line"), REFUSED, ids=[repr(item[0][:48]) for item in REFUSED])
def test_everything_else_is_refused_with_its_construct_and_line(script, construct, line):
    with pytest.raises(ScriptRefused) as refused:
        compile_script(script)
    assert construct in refused.value.construct
    assert refused.value.line == line
    assert refused.value.message


def test_a_refusal_says_what_to_do_next():
    def message(script: str) -> str:
        with pytest.raises(ScriptRefused) as refused:
            compile_script(script)
        return refused.value.message

    box = "result = cq.Workplane('XY').box(1, 1, 1)\n"
    assert "Delete this line" in message(box + "cq.exporters.export(result, 'plate.step')\n")
    grid = "r{i} = cq.Workplane('XY').box(100, 100, 2).faces('>Z').workplane().rarray(1, 1, 10, 10).hole(0.5)\n"
    assert "201 in the script" in message(grid.format(i=0) + grid.format(i=1) + grid.format(i=2).replace("10, 10", "1, 1"))
    assert "fractional power" in message("x = (-8) ** 0.5\n")
    assert "starts with a letter" in message("_t = 2\n")
    assert message("from cadquery import Workplane\n") == message("import os\n")
    assert "an if statement" in message("if 1:\n    x = 1\n") and "a while loop" in message("while 1:\n    x = 1\n")
    # A loop that cannot be read says what one may run over, and what to write instead.
    assert "for i in range(5):" in message("for i in enumerate([1, 2]):\n    x = i\n")
    assert "range(length // pitch)" in message("for i in range(7.5):\n    x = i\n")
    assert "for i in range(5):" in message("x = range(3)\n")
    assert "union" in message(box + "result += result\n")
    assert "split" in message("result = cq.Workplane('XY')" + ".close()" * 98 + "\n")
    # What a script wrote is quoted back in part, never in full.
    for long in ("x = " + "a" * 900 + "\n", box + "y = result." + "a" * 900 + "()\n", box + "y = result.box(1, 1, 1, " + "a" * 900 + "=1)\n"):
        assert "aaa..." in message(long) and len(message(long)) < 700
    assert "break it" in message("x = " + "1 + " * 300 + "1\n")
    # A method off the list: the nearest names on it, and where all of them are, not the whole table in every refusal.
    near_miss = message(box + "result = result.faces('>Z').workplane().rect(4, 4).cutThru()\n")
    assert "The nearest on it: cutThruAll" in near_miss and "references/operations.md" in near_miss and len(near_miss) < 300
    assert "nearest" not in message(box + "result = result.sketch()\n")


def test_the_export_refusal_shadows_no_allow_listed_method():
    from deerflow_extension_cad import interpreter

    assert not [name for name in allowlist.METHODS if name.lower().startswith(interpreter._EXPORTS)]


LOOP = """\
import cadquery as cq

pitch = 12
x = -18
result = cq.Workplane("XY").box(60, 20, 4)
for i in range(4):
    result = result.faces(">Z").workplane().pushPoints([(x, 0)]).hole(3)
    x += pitch
"""
WRITTEN_OUT = """\
import cadquery as cq

result = cq.Workplane("XY").box(60, 20, 4)
result = result.faces(">Z").workplane().pushPoints([(-18, 0)]).hole(3)
result = result.faces(">Z").workplane().pushPoints([(-6, 0)]).hole(3)
result = result.faces(">Z").workplane().pushPoints([(6, 0)]).hole(3)
result = result.faces(">Z").workplane().pushPoints([(18, 0)]).hole(3)
"""


def _shape(program):
    """What the kernel is asked to do, without where the script said it."""
    return [(op.receiver, op.method, op.arguments) for op in program.operations], program.result


def test_a_loop_is_the_same_program_as_its_statements_written_out():
    """The whole guarantee: a loop adds nothing a script could not already say line by line."""
    loop, flat = compile_script(LOOP), compile_script(WRITTEN_OUT)
    assert _shape(loop) == _shape(flat)
    assert len(loop.operations) == 2 + 4 * 4 <= MAX_OPERATIONS
    # One line now stands for four operations, so each says which pass it belongs to.
    holes = [op for op in loop.operations if op.method == "hole"]
    assert [op.line for op in holes] == [7, 7, 7, 7]
    assert [op.where for op in holes] == [f"pass {number} of the loop on line 6 (i = {number - 1})" for number in (1, 2, 3, 4)]
    assert [op.where for op in loop.operations[:2]] == ["", ""] and not any(op.where for op in flat.operations)


@pytest.mark.parametrize(
    ("header", "values"),
    [
        ("for v in range(3):", [0, 1, 2]),
        ("for v in range(2, 5):", [2, 3, 4]),
        ("for v in range(0, 50, 20):", [0, 20, 40]),
        ("for v in range(3, 0, -1):", [3, 2, 1]),
        ("for v in range(-2, 2):", [-2, -1, 0, 1]),
        ("for v in range(count // 2):", [0, 1]),
        ("for v in range(count / 2):", [0, 1]),
        ("for v in [5, 7.5, -1]:", [5, 7.5, -1]),
        ("for v in (4, 2):", [4, 2]),
        ("for v in sizes:", [10, 20]),
        ("for unused, v in [(0, 1), (0, 2)]:", [1, 2]),
        ("for v, unused in points:", [3, 5]),
    ],
)
def test_a_loop_runs_over_a_range_or_a_list_the_script_states(header, values):
    script = f"count = 4\nsizes = [10, 20]\npoints = [(3, 4), (5, 6)]\nresult = cq.Workplane('XY')\n{header}\n    result = result.box(1 + v % 2, 1, 1).translate((v, 0, 0))\n"
    moves = [dict(op.arguments)["vec"] for op in compile_script(script).operations if op.method == "translate"]
    assert moves == [(value, 0, 0) for value in values]


def test_loops_nest_and_a_name_set_in_a_loop_is_still_set_after_it():
    grid = "for row in range(2):\n    for column in range(3):\n        total += 1\n        result = result.translate((row, column, 0))\n"
    script = "total = 0\nresult = cq.Workplane('XY').box(50, 50, 2)\n" + grid + "result = result.translate((total, row, column))\n"
    moves = [dict(op.arguments)["vec"] for op in compile_script(script).operations if op.method == "translate"]
    assert moves == [(0, 0, 0), (0, 1, 0), (0, 2, 0), (1, 0, 0), (1, 1, 0), (1, 2, 0), (6, 1, 2)]
    inner = compile_script(script).operations[2]
    # Innermost first: the pass that failed, then the passes around it.
    assert inner.where == "pass 1 of the loop on line 4 (column = 0), pass 1 of the loop on line 3 (row = 0)"


def test_a_refusal_inside_a_loop_says_which_pass():
    script = "result = cq.Workplane('XY').box(9, 9, 9)\nfor i in range(5):\n    gap = 12 / (i - 3)\n"
    with pytest.raises(ScriptRefused) as refused:
        compile_script(script)
    assert (refused.value.construct, refused.value.line) == ("arithmetic", 3)
    assert refused.value.message == "division by zero (in pass 4 of the loop on line 2 (i = 3))"
    nested = "for a in range(2):\n    for b in [(1, 2)]:\n        c = b.x\n"
    with pytest.raises(ScriptRefused) as refused:
        compile_script(nested)
    # Said once, with every loop around it, innermost first.
    assert refused.value.message.count("(in ") == 1
    assert refused.value.message.endswith("(in pass 1 of the loop on line 2 (b = (1, 2)), pass 1 of the loop on line 1 (a = 0))")


def test_loops_are_bounded_in_passes_depth_and_operations():
    def refusal(script: str) -> ScriptRefused:
        with pytest.raises(ScriptRefused) as refused:
            compile_script(script)
        return refused.value

    assert compile_script(f"result = cq.Workplane('XY').box(1, 1, 1)\nfor i in range({MAX_LOOP_PASSES}):\n    x = i\n")
    assert "passes in total" in refusal(f"for i in range({MAX_LOOP_PASSES + 1}):\n    x = i\n").message
    # A range of a billion is refused from its length: nothing is counted out first.
    assert "passes in total" in refusal("for i in range(10 ** 9):\n    x = i\n").message
    # Added up over the script, nested and one after another.
    assert "passes in total" in refusal("for i in range(40):\n    for j in range(40):\n        x = i\n").message
    assert "passes in total" in refusal("for i in range(600):\n    x = i\nfor j in range(600):\n    y = j\n").message
    deep = "".join(" " * 4 * level + f"for v{level} in range(1):\n" for level in range(MAX_LOOP_DEPTH + 1)) + " " * 4 * (MAX_LOOP_DEPTH + 1) + "x = 1\n"
    assert f"at most {MAX_LOOP_DEPTH} deep" in refusal(deep).message
    # A loop multiplies operations, and the cap on them is the same one.
    many = refusal("result = cq.Workplane('XY').box(1, 1, 1)\nfor i in range(200):\n    result = result.translate((1, 0, 0)).translate((0, 1, 0))\n")
    assert (many.construct, "at most 300 operations" in many.message, "pass 150" in many.message) == ("script length", True, True)
    # Numbers stay capped inside a loop: it cannot grow one past what a single line may hold.
    assert "no larger than" in refusal("x = 10\nfor i in range(20):\n    x = x * x\n").message
    points = refusal("result = cq.Workplane('XY').box(99, 99, 1)\nfor i in range(30):\n    result = result.faces('>Z').workplane().rarray(1, 1, 3, 3).hole(0.2)\n")
    assert (points.construct, "in the script" in points.message) == ("pattern", True)


def test_reading_is_bounded_in_work_and_not_only_in_passes():
    """A thousand passes of a body that walks long lists took fifteen seconds to read; the cap on passes did not bound it."""

    def wrapped(name: str, item: str, count: int) -> str:
        rows = [", ".join([item] * 100) for _ in range(count // 100)] + ([", ".join([item] * (count % 100))] if count % 100 else [])
        return f"{name} = [\n" + ",\n".join(rows) + "\n]\n"

    body = "".join("    " + line + "\n" for line in (wrapped("a", "p", 390) + wrapped("b", "p", 390)).splitlines())
    slow = wrapped("p", "1", 400).replace("[", "(", 1).replace("]", ")") + "for i in range(1000):\n" + body + "result = cq.Workplane('XY').box(1, 1, 1)\n"
    started = time.perf_counter()
    with pytest.raises(ScriptRefused) as refused:
        compile_script(slow)
    assert time.perf_counter() - started < 3
    assert refused.value.construct == "script length" and "more work" in refused.value.message
    assert MAX_WORK >= 100_000
    # Statements count as well as values: a thousand passes over hundreds of notes are not free.
    notes = "result = cq.Workplane('XY').box(1, 1, 1)\nfor i in range(1000):\n" + '    "note"\n' * 980
    with pytest.raises(ScriptRefused) as refused:
        compile_script(notes)
    assert "more work" in refused.value.message
    # An ordinary long loop is nowhere near it: 74 passes of four operations, 296 of the 300 a script may perform.
    long_loop = "result = cq.Workplane('XY').box(900, 20, 4)\nfor i in range(74):\n    result = result.faces('>Z').workplane().pushPoints([(-440 + i * 12, 0)]).hole(3)\n"
    assert len(compile_script(long_loop).operations) == 2 + 74 * 4
    grid = "points = [\n" + ",\n".join(", ".join(f"({x}, {y})" for x in range(20)) for y in range(20)) + "\n]\nresult = cq.Workplane('XY').box(9, 9, 9)\nfor x, y in points:\n    total = x + y\n"
    assert compile_script(grid)


def test_a_pass_clause_is_short_and_says_its_numbers_exactly():
    def message(script: str) -> str:
        with pytest.raises(ScriptRefused) as refused:
            compile_script(script)
        return refused.value.message

    # Whole numbers as they are and decimals in full: six digits named a value the loop never held.
    assert message("for i in range(1234567, 1234570):\n    y = 1 / (i - 1234568)\n").endswith("(in pass 2 of the loop on line 1 (i = 1234568))")
    assert message("for x in [0.30000001, 0.30000002]:\n    y = 1 / (x - 0.30000002)\n").endswith("(x = 0.30000002))")
    # Twelve digits: every digit a person wrote, without the tail a division leaves behind.
    assert message("for x in [14.41 * 6.22 - 76]:\n    y = 1 / 0\n").endswith("(x = 13.6302))")
    # A long point is cut, however many loops hold one and however many names take it apart.
    long_point = "p = (\n" + ",\n".join(", ".join(["-1.23456e-05"] * 50) for _ in range(8)) + "\n)\n"
    nested = long_point + "".join(" " * 4 * level + f"for v{level} in [p]:\n" for level in range(4)) + " " * 16 + "y = 1 / 0\n"
    assert len(message(nested)) < 400 and "400 numbers" in message(nested)
    assert len(message(long_point + "for a, b in [p]:\n    x = 1\n")) < 200
    names = ", ".join(f"n{index:03d}_{'x' * 58}" for index in range(180))
    many = "for " + names.replace(", ", ",\n    ") + " in [(\n" + ",\n".join(", ".join(["1"] * 90) for _ in range(2)) + "\n)]:\n    y = 1 / 0\n"
    assert len(message(many)) < 200
    # The worst ordinary case: four loops deep, two names each, a method that is not on the list.
    deep = "result = cq.Workplane('XY').box(1, 1, 1)\n" + "".join(" " * 4 * level + f"for a{level}, b{level} in [(1, 2)]:\n" for level in range(4)) + " " * 16 + "result = result.val()\n"
    assert len(message(deep)) < 700 and message(deep).count("pass 1 of the loop") == 4


def test_a_count_for_a_loop_is_a_whole_number_however_it_was_computed():
    def passes(header: str) -> int:
        script = f"spine = 50\npitch = 3.5\nresult = cq.Workplane('XY').box(9, 9, 9)\n{header}\n    result = result.translate((1, 0, 0))\n"
        return len(compile_script(script).operations) - 2

    # Whole division keeps the decimal point when either number has one: 50 // 3.5 is 14.0.
    assert (passes("for i in range(spine // pitch):"), passes("for i in range(10 / 2):"), passes("for i in range(2.0, 8.0, 2.0):")) == (14, 5, 3)
    with pytest.raises(ScriptRefused) as refused:
        compile_script("for i in range(15 / 2):\n    x = i\n")
    assert "got 7.5" in refused.value.message and "whole" in refused.value.message


def test_a_sign_alternates_over_any_number_of_passes():
    # The usual way to say "every other one" without a branch. A base of one or less cannot grow, so its exponent is not capped.
    script = "result = cq.Workplane('XY').box(9, 9, 9)\nfor i in range(200):\n    side = (-1) ** i\n    shrink = 0.5 ** i\n"
    assert compile_script(script)
    for bad in ("x = 2 ** 65\n", "x = 1.5 ** 65\n", "x = 0.5 ** -2000\n", "x = (-1) ** 0.5\n", "x = 0 ** -1\n"):
        with pytest.raises(ScriptRefused) as refused:
            compile_script(bad)
        assert refused.value.construct == "arithmetic"


def test_a_loop_body_reads_the_way_its_indentation_shows():
    """With loops, indentation decides what a line belongs to, so nothing may sit where a viewer does not look for it."""

    def refusal(script: str) -> ScriptRefused:
        with pytest.raises(ScriptRefused) as refused:
            compile_script(script)
        return refused.value

    box = "result = cq.Workplane('XY').box(60, 40, 6)\n"
    hole = "result = result.faces('>Z').workplane().hole(30)\n"
    # Far to the right: a viewer shows the line as blank.
    assert "indented" in refusal(box + "for i in range(1):\n" + " " * 950 + hole).message
    assert "indented" in refusal(box + "for i in range(1):\n" + "\t" * 120 + hole).message
    assert "indented" in refusal("result = (\n" + " " * (MAX_INDENT + 1) + "cq.Workplane('XY').box(1, 1, 1)\n)\n").message
    assert compile_script("result = (\n" + " " * MAX_INDENT + "cq.Workplane('XY').box(1, 1, 1)\n)\n")
    # A tab is as wide as a viewer draws it: six in a row are 48 blanks.
    assert "blanks in a row" in refusal(box + "x = 1" + "\t" * 6 + "# note\n").message
    assert compile_script(box + "for i in range(2):\n\tresult = result.translate((1, 0, 0))\n")
    # Beside the end of a header that runs over two lines.
    assert refusal(box + "for i in (range(2)\n): " + hole).line == 3
    assert refusal(box + "for i in range(2) \\\n: " + hole).line == 3
    # A backslash carries a line into a loop that its indentation says it is not in.
    assert "indented" in refusal(box + "for i in range(2):\\\n" + hole).message
    after = refusal(box + "for i in range(3):\n    result = result.translate((1, 0, 0))\n    \\\nresult = result.translate((0, 0, 5))\n")
    assert (after.line, "loop on line 2" in after.message) == (5, True)
    # A backslash on a line of its own leaves the next line where its indentation puts it: in the body, once per pass.
    carried = compile_script(box + "for i in range(3):\n    result = result.translate((1, 0, 0))\n\\\n    result = result.translate((0, 0, 5))\n")
    assert [op.where[:6] for op in carried.operations if op.line == 5] == ["pass 1", "pass 2", "pass 3"]
    # A long chain may still be continued with a backslash, inside a loop and outside one.
    assert compile_script("result = cq.Workplane('XY') \\\n    .box(1, 1, 1)\nfor i in range(2):\n    result = result \\\n        .translate((1, 0, 0))\n")


BOX = "result = cq.Workplane('XY').box(60, 40, 6)\n"
MOVE = "result = result.translate((1, 0, 0))\n"
ORDINARY_LOOPS = {
    "a body indented with a tab": BOX + "for i in range(2):\n\t" + MOVE,
    "a body indented with two spaces": BOX + "for i in range(2):\n  " + MOVE,
    "a body indented with eight spaces": BOX + "for i in range(2):\n        " + MOVE,
    "nested loops with different widths": BOX + "for i in range(2):\n  for j in range(2):\n        " + MOVE + "  " + MOVE,
    "a statement after a nested loop ends": BOX + "for i in range(2):\n    for j in range(2):\n        " + MOVE + "    " + MOVE + MOVE,
    "comments and blank lines in a body": BOX + "for i in range(2):\n    # move it\n\n    " + MOVE + "\n        # a comment indented further\n    " + MOVE,
    "a note as the first line of a body": BOX + 'for i in range(2):\n    "each pass moves the part"\n    ' + MOVE,
    "any language in a comment inside a loop": BOX + "for i in range(2):\n    # Bohrung Ø4, 穴, отверстие, سوراخ\n    " + MOVE,
    "a statement over several lines first in a body": BOX + "for i in range(2):\n    result = (\n        result.faces('>Z')\n        .workplane()\n        .hole(2 + i)\n    )\n",
    "a continuation aligned under its bracket": BOX + "for i in range(2):\n    result = result.faces('>Z').workplane().pushPoints([(-10, 0),\n                                                        (10 + i, 0)]).hole(2)\n",
    "a header over two lines": BOX + "for x, y in [(0, 0),\n             (5, 5)]:\n    " + MOVE,
    "a parenthesised header": BOX + "for i in (range(2)):\n    " + MOVE,
    "Windows line endings": (BOX + "for i in range(2):\n    " + MOVE + "    " + MOVE).replace("\n", "\r\n"),
    "a byte order mark": "\ufeff" + BOX + "for i in range(2):\n    " + MOVE,
    "an import and show_object in a loop": "for i in range(2):\n    import cadquery as cq\n    part = cq.Workplane('XY').box(1 + i, 1, 1)\n    show_object(part)\n",
}


@pytest.mark.parametrize("script", ORDINARY_LOOPS.values(), ids=ORDINARY_LOOPS.keys())
def test_the_line_rules_refuse_no_loop_written_the_ordinary_ways(script):
    assert compile_script(script).operations


def test_centered_takes_one_flag_per_axis():
    assert compile_script("r = cq.Workplane('XY').box(1, 1, 1, centered=(True, True, False))\n")
    assert compile_script("r = cq.Workplane('XY').rect(1, 1, centered=(True, False)).extrude(1)\n")
    assert compile_script("r = cq.Workplane('XY').box(9, 9, 1).faces('>Z').workplane().rarray(2, 2, 2, 2, center=(True, False)).hole(0.5)\n")


def test_a_script_without_a_part_is_refused():
    with pytest.raises(ScriptRefused) as refused:
        compile_script("x = 1\n")
    assert refused.value.construct == "result"


def test_identifiers_python_would_normalise_into_forbidden_names_are_refused():
    # Python applies NFKC to identifiers: fullwidth letters become ASCII ones.
    for script in ("ｃｑ = 1\n", "r = cq.Workplane('XY').box(1, 1, 1).ｅｘｐｏｒｔ('/tmp/x')\n", "x = cq.ｅｘｐｏｒｔｅｒｓ\n", "r = ｃｑ.Workplane('XY').ｅｖａｌ('1')\n"):
        with pytest.raises(ScriptRefused):
            compile_script(script)
    # Names are read from the tree, after that normalisation: a fullwidth name is the plain name.
    assert compile_script("ｒｅｓｕｌｔ = cq.Workplane('XY').box(1, 1, 1)\n").result_name == "result"


def test_a_comment_may_use_any_visible_character():
    program = compile_script("# 60 × 40 mm, ±0.1°, Ø4, 安装板, plaque de montage — µm\nresult = cq.Workplane('XY').box(60, 40, 6)\n")
    assert [operation.method for operation in program.operations] == ["Workplane", "box"]
    # Joiners are ordinary spelling in Persian and Hindi and part of many emoji; they move no line and reorder nothing.
    for comment in ("# می\u200cخواهم یک صفحه", "# क्\u200dष", "# a\u200bb", "# 👩\u200d🔧 bracket"):
        assert compile_script(f"{comment}\nresult = cq.Workplane('XY').box(60, 40, 6)\n")
    # A byte order mark at the very start is how some editors save a file.
    assert compile_script("\ufeffresult = cq.Workplane('XY').box(60, 40, 6)\n")
    # Indentation inside a call and a column of aligned comments are ordinary.
    assert compile_script("result = (\n" + " " * 48 + "cq.Workplane('XY')\n" + " " * 48 + ".box(60, 40, 6)" + " " * 30 + "# the plate\n)\n")


def test_a_refusal_for_a_hidden_character_names_it():
    with pytest.raises(ScriptRefused) as refused:
        compile_script("# plate\u202e\nresult = cq.Workplane('XY').box(1, 1, 1)\n")
    assert "U+202E" in refused.value.message and refused.value.line == 1
    with pytest.raises(ScriptRefused) as not_text:
        compile_script(b"result = 1")
    assert "text" in not_text.value.message


def test_size_nesting_and_node_caps_refuse_before_any_evaluation():
    with pytest.raises(ScriptRefused) as too_long:
        compile_script("x = 1\n" + "# pad\n" * (MAX_SCRIPT_BYTES // 6 + 1))
    assert too_long.value.construct == "script size"

    # One token per line, so the limit on line length is not what refuses them.
    for hostile in ("x = " + "(\n" * 5000 + "1" + "\n)" * 5000, "x = (" + "-\n" * 5000 + "1)", "x = (" + "+\n".join(["1"] * 5000) + ")", "x = " + "[\n" * 500 + "]" * 500):
        with pytest.raises(ScriptRefused) as nested:
            compile_script(hostile)
        assert nested.value.construct in ("nesting", "script length") or (nested.value.construct == "syntax" and "longer than" not in nested.value.message)

    statements = "\n".join(f"v{i} = {i}" for i in range(MAX_NODES))
    with pytest.raises(ScriptRefused) as many:
        compile_script(statements)
    assert many.value.construct == "script length"


def test_patterns_are_capped_per_call_and_across_the_script():
    grid = "r{i} = cq.Workplane('XY').box(100, 100, 2).faces('>Z').workplane().rarray(1, 1, {n}, {n}).hole(0.5)\n"
    assert compile_script(grid.format(i=0, n=10))  # 100 points: the per-call cap
    with pytest.raises(ScriptRefused) as per_call:
        compile_script(grid.format(i=0, n=11))
    assert per_call.value.construct == "pattern"
    assert compile_script(grid.format(i=0, n=10) + grid.format(i=1, n=10))  # 200: the per-script cap
    with pytest.raises(ScriptRefused) as per_script:
        compile_script(grid.format(i=0, n=10) + grid.format(i=1, n=10) + grid.format(i=2, n=1))
    assert per_script.value.construct == "pattern" and per_script.value.line == 3
    points = "r = cq.Workplane('XY').box(100, 100, 2).faces('>Z').workplane().pushPoints([" + ", ".join(f"({i}, 0)" for i in range(101)) + "]).hole(0.5)\n"
    with pytest.raises(ScriptRefused) as pushed:
        compile_script(points)
    assert pushed.value.construct == "pattern"
    assert (allowlist.MAX_INSTANCES_PER_CALL, allowlist.MAX_INSTANCES_PER_SCRIPT) == (100, 200)


def test_numbers_the_kernel_would_choke_on_are_refused_as_arguments():
    for script in (
        "r = cq.Workplane('XY').box(1e-9, 1, 1)\n",  # the kernel answers a vanishing length with an empty error
        "r = cq.Workplane('XY').box(1, 1, 1).rotate((0, 0, 0), (0, 0, 1), 99999)\n",
        "r = cq.Workplane('XY').box(1, 1, 1).translate((1e9, 0, 0))\n",  # far enough to lose precision in the STEP
        "r = cq.Workplane('XY').box(1, 1, 1).mirror('front')\n",  # a Workplane name, not a mirror plane
        "r = cq.Workplane('XY').box(1, 1, 1, centered='abc')\n",  # the kernel would accept this silently
        "r = cq.Workplane('XY').rect(4, 4).extrude(True)\n",  # and would read True as 1
    ):
        with pytest.raises(ScriptRefused) as refused:
            compile_script(script)
        assert refused.value.construct == "argument"


def test_combining_parts_with_an_operator_points_to_the_method():
    with pytest.raises(ScriptRefused) as refused:
        compile_script("a = cq.Workplane('XY').box(1, 1, 1)\nb = cq.Workplane('XY').box(2, 2, 2)\nresult = a + b\n")
    assert refused.value.construct == "arithmetic" and "a.union(b)" in refused.value.message


def test_a_part_argument_refers_to_an_earlier_operation_not_to_an_object():
    program = compile_script("a = cq.Workplane('XY').box(4, 4, 4)\nb = cq.Workplane('XY').sphere(3)\nresult = a.intersect(b)\n")
    assert program.operations[-1].arguments == (("toIntersect", Ref(3)),)
    assert program.operations[-1].receiver == 1


def test_the_tool_description_and_the_readme_list_exactly_the_allow_listed_methods():
    """The model and the operator are told what the table holds, no more and no less."""
    from deerflow_extension_cad.tool import DESCRIPTION

    described = set(re.findall(r"[A-Za-z0-9]+", DESCRIPTION[DESCRIPTION.index("Methods:") + 8 : DESCRIPTION.index("bbox_xyz_mm is")]))
    assert described == set(allowlist.METHODS)
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("| Group | Methods |") : readme.index("Selector strings are")]
    assert set(re.findall(r"`([A-Za-z0-9]+)`", table)) == set(allowlist.METHODS)
    assert f"{len(allowlist.METHODS)} methods plus the constructor" in readme


def test_model_text_never_reaches_exec_eval_or_compile():
    """Static half: the package has no call that could run script text."""
    package = Path(__file__).resolve().parents[1] / "deerflow_extension_cad"
    offenders = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                # re.compile builds a pattern from the package's own text, not from a script.
                is_regex = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"
                if name in {"exec", "eval", "compile", "__import__", "execfile", "run_path", "run_module", "import_module"} and not is_regex:
                    offenders.append(f"{path.name}:{node.lineno} {name}")
    # ast.parse is the one reader of script text; it builds a tree and runs nothing.
    assert offenders == []
    interpreter = (package / "interpreter.py").read_text(encoding="utf-8")
    assert len(re.findall(r"\bast\.parse\(", interpreter)) == 1
    assert "getattr(" not in interpreter


def test_reading_a_hostile_script_raises_no_audit_event_but_the_parsers_own():
    """Runtime half: nothing is imported, opened or executed while scripts are read."""
    import sys

    events: list[tuple[str, tuple]] = []
    watching = [False]

    def hook(event, args):
        if watching[0] and event in {"exec", "import", "open", "os.system", "subprocess.Popen", "socket.connect", "os.listdir", "os.remove", "ctypes.dlopen"}:
            # The parser's own: on a syntax error CPython looks for the source line in a
            # file named after the filename it was given, the fixed string "<script>".
            if (event, args[0]) != ("open", "<script>"):
                events.append((event, args))

    sys.addaudithook(hook)
    # Warm every lazy import the reader itself needs before watching.
    compile_script(PLATE)
    watching[0] = True
    try:
        for script, _, _ in REFUSED:
            with pytest.raises(ScriptRefused):
                compile_script(script)
        compile_script(PLATE)
        compile_script(LOOP)
    finally:
        watching[0] = False
    assert events == []
