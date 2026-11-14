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
from deerflow_extension_cad.interpreter import MAX_NODES, MAX_SCRIPT_BYTES, Ref, ScriptRefused, compile_script

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
    assert compile_script("result = " + two[4:] + "show_object(b)\n").result_name == "result"


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
    ("r = cq.Workplane('XY').box(1, 1, 1).exportSvg('/tmp/x.svg')\n", "method", 1),
    ("r = cq.Workplane('XY').box(1, 1, 1).export('/tmp/x.step')\n", "method", 1),
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
    ("for i in (1, 2):\n    x = i\n", "loop", 1),
    ("while True:\n    x = 1\n", "loop", 1),
    ("if True:\n    x = 1\n", "if statement", 1),
    ("with cq as x:\n    y = 1\n", "with statement", 1),
    ("try:\n    x = 1\nexcept Exception:\n    x = 2\n", "try statement", 1),
    ("raise ValueError\n", "raise", 1),
    ("assert True\n", "assert", 1),
    ("x = 1\ndel x\n", "del", 2),
    ("global x\n", "global", 1),
    ("pass\n", "pass", 1),
    ("x = 1\nx += 1\n", "augmented assignment", 2),
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
    ("x = 1\n\x00y = 2\n", "syntax", None),
    # What a viewer shows as one line must be what the parser reads as one line.
    ("x = 1\n\x0cy = 2\n", "syntax", None),
    ("x = 1\n# a comment\ry = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("x = 1\x0b\n", "syntax", None),
    ("x = 1  # \x7f\n", "syntax", None),
    ("x = 1  # \x1b[31m\n", "syntax", None),
    # The same for characters a viewer does not draw, reorders, or breaks a line on.
    ("# a plate \u202e 4 mm holes\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("# a\u200bb\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("# a comment\u2028r = cq.Workplane('XY').box(2, 2, 2)\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("# a\u2029b\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("# a\u0085b\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("\ufeffr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
    ("# \ud800\nr = cq.Workplane('XY').box(1, 1, 1)\n", "syntax", None),
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


def test_a_refusal_for_a_hidden_character_names_it():
    with pytest.raises(ScriptRefused) as refused:
        compile_script("# plate\u202e\nresult = cq.Workplane('XY').box(1, 1, 1)\n")
    assert "U+202E" in refused.value.message
    with pytest.raises(ScriptRefused) as not_text:
        compile_script(b"result = 1")
    assert "text" in not_text.value.message


def test_size_nesting_and_node_caps_refuse_before_any_evaluation():
    with pytest.raises(ScriptRefused) as too_long:
        compile_script("x = 1\n" + "# pad\n" * (MAX_SCRIPT_BYTES // 6 + 1))
    assert too_long.value.construct == "script size"

    for hostile in ("x = " + "(" * 5000 + "1" + ")" * 5000, "x = " + "-" * 5000 + "1", "x = " + "+".join(["1"] * 5000), "x = " + "[" * 500 + "]" * 500):
        with pytest.raises(ScriptRefused) as nested:
            compile_script(hostile)
        assert nested.value.construct in ("nesting", "script length", "syntax")

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
    finally:
        watching[0] = False
    assert events == []
