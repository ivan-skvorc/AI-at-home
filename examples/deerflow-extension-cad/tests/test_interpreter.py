"""The script is read, never run: what the reader accepts and what it refuses.

These tests need no CAD kernel. ``compile_script`` turns text into a list of
allow-listed operations or raises ``ScriptRefused`` with the construct and line.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from deerflow_extension_cad import allowlist
from deerflow_extension_cad.interpreter import MAX_LOOP_DEPTH, MAX_LOOP_PASSES, MAX_NODES, MAX_OPERATIONS, MAX_SCRIPT_BYTES, Ref, ScriptRefused, compile_script

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
    ],
)
def test_ordinary_scripts_are_accepted(script):
    program = compile_script(script)
    assert program.operations and program.operations[program.result].method in allowlist.METHODS


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
    ("x = [i for i in (1, 2)]\n", "comprehension", 1),
    ("x = (i for i in (1, 2))\n", "comprehension", 1),
    ("x = 1 if 2 else 3\n", "conditional expression", 1),
    ("x = (y := 1)\n", "assignment expression", 1),
    ("y = 1\nx = f'{y}'\n", "f-string", 2),
    ("x = '%s' % 1\n", "arithmetic", 1),
    ("x = 'a' + 'b'\n", "arithmetic", 1),
    ("x = 'a' * 3\n", "arithmetic", 1),
    ("x = [0] * 3\n", "arithmetic", 1),
    ("x = (1, 2)[0]\n", "subscript", 1),
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
    ("n = 10 / 2\nfor i in range(n):\n    x = i\n", "loop", 2),
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
    ("x = [i for i in range(3)]\n", "comprehension", 1),
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
    ("a, b = 1, 2\n", "assignment target", 1),
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
