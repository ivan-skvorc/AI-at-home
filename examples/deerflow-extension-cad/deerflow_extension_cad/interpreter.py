"""Read a CadQuery script without running it.

``compile_script`` parses the text into a syntax tree and walks it. The walk
accepts ``import cadquery as cq`` and ``import math``, assignments to plain
names (several at once: ``w, d, t = 60, 40, 6``), numbers, strings, tuples,
lists, arithmetic on numbers, the closed numbers table of :mod:`allowlist`
(``math.pi``, ``math.sin(x)``, ``min``, ``max``, ``round`` ...), an index known
when the script is read (``p[0]``), list comprehensions with one ``for``,
``for`` loops over ``range(...)`` or a list, ``cq.Workplane(...)`` and calls to
the methods in :mod:`allowlist`. Everything else is refused with the construct,
what it refused and its line. The outcome is a :class:`Program`: a flat list of
allow-listed operations with plain-data arguments, which ``build.run_program``
performs against the kernel.

Nothing here executes script text. ``ast.parse`` builds a tree and runs
nothing; no value from the script is ever used to look up an attribute. The
numbers table is computed here, by the reader's own functions on numbers it has
checked. A ``for`` loop and a comprehension are unrolled here, pass by pass:
what they run over is a range or a list the script states, so a loop is the
same statements written out and a comprehension the same list written out, and
the program stays flat. A script has no branches, functions or ``while``, so
every number is known before the kernel starts: a refusal costs no geometry and
needs no CadQuery.
"""

from __future__ import annotations

import ast
import difflib
import math
import re
import unicodedata
from dataclasses import dataclass

from deerflow_extension_cad import allowlist as table

MAX_SCRIPT_BYTES = 32 * 1024
#: Characters on one line. With one statement per line, nothing that decides the part
#: sits far to the right of what a viewer shows.
MAX_LINE = 1_000
MAX_NODES = 2_000
MAX_DEPTH = 200
MAX_OPERATIONS = 300
MAX_STRING = 80
#: No number in a script, literal or computed, may exceed this.
MAX_NUMBER = 1e12
MAX_EXPONENT = 64
MAX_COUNT = 10_000
#: Passes of every loop in a script, added up: past any part's features, and few enough
#: that a failure can name its pass. What reading costs is bounded by MAX_WORK below.
MAX_LOOP_PASSES = 1_000
#: Loops inside loops. Each level adds a clause to where a failure is said to be.
MAX_LOOP_DEPTH = 4
#: Values read and list items walked, loops unrolled. Passes alone do not bound reading: a
#: body that walks long lists a thousand times took fifteen seconds. An ordinary script
#: spends a few thousand.
MAX_WORK = 200_000
#: How much of one pass a failure quotes, and of all the passes around it together.
MAX_PASS_SAID = 60
MAX_WHERE = 240

_SELECTOR = re.compile(table.SELECTOR_PATTERN)
_TAG = re.compile(table.TAG_PATTERN)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
#: Every control character but tab, line feed and the carriage return of a CRLF pair.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\r(?!\n)")
#: Beyond ASCII: controls, lone surrogates, and the line and paragraph separators,
#: which move where a line starts for a viewer...
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cs", "Zl", "Zp"})
#: ...and the direction marks and overrides, which reorder what a viewer draws. Other
#: format characters (joiners in Persian, Hindi and emoji) can only occur in a comment,
#: where they move no line and reorder nothing.
_DIRECTION_MARKS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
#: Blanks in a row after a line's first character, and blank lines in a row: more is padding
#: that pushes code out of sight, sideways or down.
MAX_BLANK_RUN = 40
_PADDING = re.compile(rf"\S {{{MAX_BLANK_RUN + 1},}}\S")
#: Columns a line may be indented, a tab counted as a viewer draws it. Further right, a
#: narrow viewer shows the line as blank; a loop body is a whole statement that could sit there.
MAX_INDENT = 80
TAB_WIDTH = 8


class ScriptRefused(Exception):
    """The script asks for something a script may not contain."""

    def __init__(self, construct: str, line: int | None, message: str, name: str | None = None):
        super().__init__(f"line {line}: {message}" if line else message)
        self.construct = construct
        self.line = line
        self.message = message
        #: What was refused, as the script wrote it where that is shorter than a sentence
        #: ('loft', 'import os', 'math.sqrt'); else the construct. Counted by kind, not read.
        self.name = name or construct
        #: True once the message says which loop pass it happened in.
        self.placed = False


@dataclass(frozen=True)
class Ref:
    """A part built by an earlier operation, by its position in the program."""

    slot: int


@dataclass(frozen=True)
class Operation:
    line: int
    #: The operation whose part this method is called on; None for cq.Workplane(...).
    receiver: int | None
    #: "Workplane" or a key of ``allowlist.METHODS``.
    method: str
    #: Keyword arguments in CadQuery's parameter order; values are plain data or Ref.
    arguments: tuple[tuple[str, object], ...]
    #: For an operation inside a loop, which pass it belongs to, in words: one line of a loop stands for many operations.
    where: str = ""
    #: The same as data: (line of the loop, number of the pass) for each loop around the operation, outermost first.
    passes: tuple[tuple[int, int], ...] = ()
    #: True in the last pass of the innermost loop.
    last: bool = False
    #: Which call of the script this is, the same in every pass: where the call ends (line, column).
    site: tuple[int, int] = (0, 0)

    @property
    def loop(self) -> int:
        """The line of the innermost loop the operation is in; 0 outside a loop."""
        return self.passes[-1][0] if self.passes else 0


@dataclass(frozen=True)
class Program:
    operations: tuple[Operation, ...]
    #: Position of the operation that yields the part.
    result: int
    result_name: str
    #: The numbers the script starts with: top-level names assigned once, before the first
    #: operation, in the order assigned. What a follow-up edit changes.
    parameters: tuple[tuple[str, int | float], ...] = ()


# --- What the tree may contain ----------------------------------------------

_ALLOWED = frozenset(
    {
        ast.Module,
        ast.Import,
        ast.alias,
        ast.Assign,
        ast.AugAssign,
        ast.For,
        ast.Expr,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Constant,
        ast.Tuple,
        ast.List,
        ast.UnaryOp,
        ast.UAdd,
        ast.USub,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.Call,
        ast.Attribute,
        ast.keyword,
        ast.Subscript,
        ast.ListComp,
        ast.comprehension,
    }
)

_CONSTRUCTS: dict[type, str] = {
    ast.ImportFrom: "import",
    ast.Lambda: "lambda",
    ast.SetComp: "comprehension",
    ast.DictComp: "comprehension",
    ast.GeneratorExp: "comprehension",
    ast.IfExp: "conditional expression",
    ast.NamedExpr: "assignment expression",
    ast.JoinedStr: "f-string",
    ast.FormattedValue: "f-string",
    ast.Slice: "slice",
    ast.Compare: "comparison",
    ast.BoolOp: "boolean operator",
    ast.Set: "set",
    ast.Dict: "dict",
    ast.FunctionDef: "function definition",
    ast.AsyncFunctionDef: "function definition",
    ast.ClassDef: "class definition",
    ast.AsyncFor: "async loop",
    ast.While: "while loop",
    ast.Break: "break",
    ast.Continue: "continue",
    ast.If: "if statement",
    ast.With: "with statement",
    ast.AsyncWith: "with statement",
    ast.Try: "try statement",
    ast.TryStar: "try statement",
    ast.Raise: "raise",
    ast.Assert: "assert",
    ast.Delete: "del",
    ast.Global: "global",
    ast.Nonlocal: "global",
    ast.Pass: "pass",
    ast.AnnAssign: "annotated assignment",
    ast.Match: "match statement",
    ast.TypeAlias: "type alias",
    ast.Starred: "starred argument",
    ast.Yield: "yield",
    ast.YieldFrom: "yield",
    ast.Await: "await",
    ast.Return: "return",
    ast.Not: "operator",
    ast.Invert: "operator",
    ast.LShift: "operator",
    ast.RShift: "operator",
    ast.BitOr: "operator",
    ast.BitXor: "operator",
    ast.BitAnd: "operator",
    ast.MatMult: "operator",
}

_POSITIONED = (ast.stmt, ast.expr, ast.keyword, ast.alias)
_ONLY_IMPORT = "a script may contain two imports: import cadquery as cq and import math"
_FROM_MATH = "from math import ... is not available: write import math, then math.sqrt(x) or math.pi"
_ALLOWED_SUMMARY = (
    "A script may contain: import cadquery as cq and import math, assignments to names (a, b = 1, 2), numbers, strings, tuples, lists, arithmetic, "
    "math.pi and the math functions, abs, min, max, round, int, float, len, an index such as p[0], a list comprehension with one for, "
    "for loops over range(...) or a list, cq.Workplane(...) and the allow-listed methods of a part."
)
_LOOP_OVER = "a loop runs over range(...) or over a list of numbers or points, for example: for i in range(5):"
_COMPREHENSION_OVER = "a comprehension runs over range(...) or over a list of numbers or points, for example: [(10 * i, 0) for i in range(5)]"
#: Names a script reads and may not assign: the modules, the viewer's call, what a loop counts with, and the built-ins.
_RESERVED = ("cq", "math", "show_object", "range", *table.BUILTINS)


#: Attribute names that mean "write a file": the tool does that itself, after its checks.
_EXPORTS = ("export", "save", "tosvg")
MAX_ECHO = 60


#: Where every method is named. The list itself is too long to repeat in each refusal: it
#: grows with the table, and a refusal four loops deep has to stay a few lines.
_ALL_METHODS = "Every method a part has is named after Methods: in cad_build's description and in references/operations.md of the cad-modeling skill."


def _nearest(name: str) -> str:
    """The allow-listed methods spelled most like *name*, for a typo or a near miss such as cutThru."""
    close = difflib.get_close_matches(name[:MAX_ECHO], table.METHODS, n=4, cutoff=0.6)
    return f" The nearest on it: {', '.join(close)}." if close else ""


def _refuse(construct: str, line: int | None, message: str, name: str | None = None):
    raise ScriptRefused(construct, line, message, name)


def _short(text: str, limit: int = MAX_ECHO) -> str:
    """What a script wrote, cut for quoting back: a refusal is not a way to fill the answer."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _article(noun: str) -> str:
    return f"an {noun}" if noun[:1] in "aeiou" else f"a {noun}"


def _show(value: object) -> str:
    """A loop variable's value, as it is said beside a failure: exact, and short however long the value."""
    if isinstance(value, tuple):
        if len(value) > 3:
            return f"({_show(value[0])}, {_show(value[1])}, ... {len(value)} numbers)"
        return "(" + ", ".join(_show(item) for item in value) + ")"
    # A whole number as it is and a decimal to twelve digits: every digit a person wrote, and
    # not the tail a division leaves. Six digits named a value the loop never held.
    return f"{value:.12g}" if type(value) is float else str(value)


def _check_lines(statements: list[ast.stmt], lines: list[bytes], loop: ast.For | None = None) -> None:
    """Every statement starts its own line, and a loop's body is indented as one block under it.

    With loops, indentation decides what a line belongs to. A statement beside the end
    of a header, or one that a backslash carries into a loop from the margin, would be
    read here as part of the loop and by a person as not.
    """
    column = None
    for statement in statements:
        # The parser counts columns in bytes of UTF-8, so the line is cut in bytes.
        if lines[statement.lineno - 1][: statement.col_offset].strip():
            _refuse("syntax", statement.lineno, "one statement per line: start this one on its own line")
        if loop is not None:
            column = statement.col_offset if column is None else column
            if statement.col_offset <= loop.col_offset or statement.col_offset != column:
                _refuse("syntax", statement.lineno, f"this line belongs to the loop on line {loop.lineno} and is not indented like the rest of its body: indent it under the loop, or end the loop first")
        if isinstance(statement, ast.For):
            _check_lines(statement.body, lines, statement)


def _check_tree(tree: ast.Module) -> None:
    """Refuse a forbidden construct, a deep tree or a long script before anything is evaluated.

    Iterative on purpose: a recursive walk over a hostile tree would itself overflow.
    """
    count = 0
    stack: list[tuple[ast.AST, int, int | None]] = [(tree, 0, None)]
    while stack:
        node, depth, line = stack.pop()
        if isinstance(node, _POSITIONED):
            line = node.lineno
        count += 1
        if count > MAX_NODES:
            _refuse("script length", line, f"the script is too long: more than {MAX_NODES} syntax nodes")
        if depth > MAX_DEPTH:
            _refuse("nesting", line, f"the expression is nested deeper than {MAX_DEPTH} levels; split a long chain of calls across two assignments")
        kind = type(node)
        if kind is ast.ImportFrom:
            written = _short(f"from {'.' * node.level}{node.module or ''} import {', '.join(alias.name for alias in node.names)}")
            _refuse("import", line, _FROM_MATH if node.module == "math" and not node.level else _ONLY_IMPORT, written)
        if kind not in _ALLOWED:
            construct = _CONSTRUCTS.get(kind, kind.__name__.lower())
            _refuse(construct, line, f"a script may not contain {_article(construct)}. {_ALLOWED_SUMMARY}")
        if kind is ast.keyword and node.arg is None:
            _refuse("keyword unpacking", line, "arguments may not be unpacked with **; name each argument")
        children = list(ast.iter_child_nodes(node))
        # Reversed so the stack yields them in source order: the first refusal is the earliest one.
        stack.extend((child, depth + 1, line) for child in reversed(children))


# --- Values -----------------------------------------------------------------


def _is_number(value: object) -> bool:
    return type(value) in (int, float)


def _in_range(value: object) -> bool:
    """A finite number within the cap. An int is compared as an int: one too large for a float cannot be asked isfinite()."""
    if type(value) is int:
        return abs(value) <= MAX_NUMBER
    return type(value) is float and math.isfinite(value) and abs(value) <= MAX_NUMBER


def _describe(value: object) -> str:
    if isinstance(value, Ref):
        return "a part"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value)
    if _is_number(value):
        return f"{value:g}"
    if isinstance(value, str):
        return f"the string {value!r}"
    return "a list or tuple"


def _holdable(item: object) -> bool:
    """What a list or tuple may hold: numbers, booleans, or points made of numbers."""
    if isinstance(item, tuple):
        return not any(isinstance(inner, tuple) for inner in item)
    return isinstance(item, bool) or _is_number(item)


# --- The numbers table: what the reader computes itself ---------------------

#: ``allowlist.MATH_FUNCTIONS``, by the function that computes each. A script's name for one
#: is a key here, checked against the table first; nothing is looked up on the math module.
_MATH = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sqrt": math.sqrt,
    "hypot": math.hypot,
    "radians": math.radians,
    "degrees": math.degrees,
    "floor": math.floor,
    "ceil": math.ceil,
}
_MATH_CONSTANTS = {"pi": math.pi, "tau": math.tau}
_MATH_SAID = f"A script may use math.pi, math.tau and these functions of math: {', '.join(table.MATH_FUNCTIONS)}."
#: Digits round() may keep or drop. An int rounded to ten thousand digits is computed
#: as a power of ten that large; a number of a script has twelve.
MAX_ROUND_DIGITS = 15


class _Unfit(Exception):
    """A built-in called with what it does not take; the reader says so as a refusal."""


def _number(value: object, what: str) -> int | float:
    if not _is_number(value):
        raise _Unfit(f"{what} takes numbers, not {_describe(value)}")
    return value


def _one(arguments: list, what: str) -> object:
    if len(arguments) != 1:
        raise _Unfit(f"{what} takes one value, got {len(arguments)}")
    return arguments[0]


def _extreme(choose):
    def extreme(arguments: list, what: str) -> int | float:
        # min(a, b, ...) or min(list): the two ways Python takes, on numbers only, since points would be compared.
        values = arguments[0] if len(arguments) == 1 and isinstance(arguments[0], tuple) else arguments
        if len(arguments) == 1 and not isinstance(arguments[0], tuple):
            raise _Unfit(f"{what} takes two numbers or more, or one list of numbers")
        if not values:
            raise _Unfit(f"{what} of an empty list has no answer")
        return choose(_number(value, what) for value in values)

    return extreme


def _round(arguments: list, what: str) -> int | float:
    if not 1 <= len(arguments) <= 2:
        raise _Unfit(f"{what} takes a number and, optionally, how many digits to keep")
    value = _number(arguments[0], what)
    if len(arguments) == 1:
        return round(value)
    digits = arguments[1]
    if type(digits) is not int or abs(digits) > MAX_ROUND_DIGITS:
        raise _Unfit(f"{what} keeps a whole number of digits from -{MAX_ROUND_DIGITS} to {MAX_ROUND_DIGITS}, got {_describe(digits)}")
    return round(value, digits)


def _length(arguments: list, what: str) -> int:
    value = _one(arguments, what)
    if not isinstance(value, tuple):
        raise _Unfit(f"{what} takes a list or a point, not {_describe(value)}")
    return len(value)


#: ``allowlist.BUILTINS``, by the function that computes each.
_BUILTIN = {
    "abs": lambda arguments, what: abs(_number(_one(arguments, what), what)),
    "min": _extreme(min),
    "max": _extreme(max),
    "round": _round,
    "int": lambda arguments, what: int(_number(_one(arguments, what), what)),
    "float": lambda arguments, what: float(_number(_one(arguments, what), what)),
    "len": _length,
}


class _Reader:
    def __init__(self) -> None:
        self.names: dict[str, object] = {}
        self.operations: list[Operation] = []
        self.instances = 0
        self.passes = 0
        self.work = 0
        #: The loop passes being read, outermost first: the loop's line, the pass's number, how it is said, whether it is the last.
        self.loops: list[tuple[int, int, str, bool]] = []
        #: (name, slot) pairs: the part a name held at that moment, whatever the name holds later.
        self.shown: tuple[str, int] | None = None
        self.shown_line: int | None = None
        self.last_part: tuple[str, int] | None = None
        self.result_line: int | None = None
        #: How often each name is assigned, and the numbers assigned at the top before the first operation.
        self.assignments: dict[str, int] = {}
        self.starting_numbers: dict[str, int | float] = {}

    # Statements

    def statement(self, node: ast.stmt) -> None:
        self.spend(1, node.lineno)  # a note or an import costs a pass through here too
        if isinstance(node, ast.Import):
            written = [alias.name + (f" as {alias.asname}" if alias.asname else "") for alias in node.names]
            if written != ["cadquery as cq"] and written != ["math"]:
                _refuse("import", node.lineno, _ONLY_IMPORT, _short("import " + ", ".join(written)))
        elif isinstance(node, ast.Assign):
            target = node.targets[0] if len(node.targets) == 1 else None
            if isinstance(target, ast.Name):
                name = self.target(target.id, node.lineno)
                self.assign(name, self.value(node.value), node.lineno)
            elif isinstance(target, ast.Tuple):
                self.unpack(target, node.value, node.lineno)
            else:
                self.refuse_target(target, node.lineno)
        elif isinstance(node, ast.AugAssign):
            # x += step is x = x + step: numbers only, like the arithmetic it stands for.
            if not isinstance(node.target, ast.Name):
                self.refuse_target(node.target, node.lineno)
            name = self.target(node.target.id, node.lineno)
            if name not in self.names:
                _refuse("name", node.lineno, f"{_short(name)!r} is not defined earlier in the script", name)
            self.assign(name, self.combine(node.op, self.names[name], self.value(node.value), node.lineno), node.lineno)
        elif isinstance(node, ast.For):
            self.loop(node)
        elif isinstance(node, ast.Expr):
            self.expression_statement(node)
        else:  # pragma: no cover - _check_tree refuses every other statement first
            _refuse("statement", node.lineno, _ALLOWED_SUMMARY)

    def assign(self, name: str, value: object, line: int, *, counted_by_a_loop: bool = False) -> None:
        self.names[name] = value
        self.assignments[name] = self.assignments.get(name, 0) + 1
        if not (counted_by_a_loop or self.loops or self.operations) and _is_number(value) and name not in self.starting_numbers:
            self.starting_numbers[name] = value
        if name == "result":
            self.result_line = line
        if isinstance(value, Ref):
            self.last_part = (name, value.slot)

    def unpack(self, target: ast.Tuple, source: ast.expr, line: int) -> None:
        """w, d, t = 60, 40, 6 is the three assignments written out; every value is read before any is assigned."""
        if not target.elts or not all(isinstance(element, ast.Name) for element in target.elts):
            _refuse("assignment target", line, "assign to plain names, one per value, for example: w, d, t = 60, 40, 6")
        names = [self.target(element.id, line) for element in target.elts]
        if isinstance(source, (ast.Tuple, ast.List)) and len(source.elts) == len(names):
            # One value per name as written: a part may be one of them, as on a line of its own.
            values = tuple(self.value(element) for element in source.elts)
        else:
            values = self.value(source)
            if not isinstance(values, tuple) or len(values) != len(names):
                said = f"{len(values)} values" if isinstance(values, tuple) else _describe(values)
                _refuse("assignment target", line, f"{len(names)} names take {len(names)} values, and this is {said}")
        for name, value in zip(names, values):
            self.assign(name, value, line)

    def refuse_target(self, target: ast.expr | None, line: int) -> None:
        if isinstance(target, ast.Subscript):
            _refuse("subscript", line, "an item of a list cannot be changed: write the list out again with the new item")
        _refuse("assignment target", line, "assign one value to one plain name, for example: width = 40, or one per name: w, d = 60, 40")

    def parameters(self) -> tuple[tuple[str, int | float], ...]:
        return tuple((name, value) for name, value in self.starting_numbers.items() if self.assignments[name] == 1)

    def spend(self, amount: int, line: int) -> None:
        """Count what reading costs, so no script is read for longer than a moment."""
        self.work += amount
        if self.work > MAX_WORK:
            _refuse("script length", line, "the script asks for more work than a script may: its loops repeat long lists too often. Shorten the lists or the loops.")

    def target(self, name: str, line: int) -> str:
        if name in _RESERVED:
            _refuse("name", line, f"{name!r} is a name the script is given and cannot be assigned: use another name", name)
        if "__" in name or not _NAME.fullmatch(name):
            _refuse("name", line, f"{_short(name)!r} cannot be assigned: use a name that starts with a letter and holds letters, digits and single underscores, at most 64 characters, and not cq", _short(name))
        return name

    # Loops

    def loop(self, node: ast.For) -> None:
        """Read the body once per pass, as if the script had written it out that many times."""
        line = node.lineno
        if node.orelse:
            _refuse("loop", node.orelse[0].lineno, "a loop may not have an else block")
        if len(self.loops) >= MAX_LOOP_DEPTH:
            _refuse("loop", line, f"loops may be nested at most {MAX_LOOP_DEPTH} deep")
        elements = node.target.elts if isinstance(node.target, ast.Tuple) else [node.target]
        if any(isinstance(element, ast.Subscript) for element in elements):
            _refuse("subscript", line, "a loop counts with a plain name, not with an item of a list")
        if not elements or not all(isinstance(element, ast.Name) for element in elements):
            _refuse("loop", line, "a loop counts with a plain name, or with one name per number of a point, for example: for x, y in [(0, 0), (10, 0)]:")
        names = [self.target(element.id, line) for element in elements]
        items = self.items(node.iter, "loop", MAX_LOOP_PASSES, f"the loops of a script may run at most {MAX_LOOP_PASSES} passes in total", _LOOP_OVER)
        if not items:
            _refuse("loop", line, "this loop would not run once: its range or list is empty")
        for number, item in enumerate(items, 1):
            self.passes += 1
            self.spend(1, line)
            if self.passes > MAX_LOOP_PASSES:
                _refuse("loop", line, f"the loops of a script may run at most {MAX_LOOP_PASSES} passes in total")
            if isinstance(node.target, ast.Tuple):
                if not isinstance(item, tuple) or len(item) != len(names):
                    _refuse("loop", line, f"this loop takes {len(names)} names per item, and item {number} is {_short(_show(item))}")
                values = item
            else:
                values = (item,)
            for name, value in zip(names, values):
                self.assign(name, value, line, counted_by_a_loop=True)
            said = ", ".join(f"{name} = {_show(value)}" for name, value in list(zip(names, values))[:3]) + (", ..." if len(names) > 3 else "")
            self.loops.append((line, number, f"pass {number} of the loop on line {line} ({_short(said, MAX_PASS_SAID)})", number == len(items)))
            try:
                for statement in node.body:
                    self.statement(statement)
            except ScriptRefused as refused:
                self.place(refused)
            finally:
                self.loops.pop()

    def place(self, refused: ScriptRefused) -> None:
        """Say once, from the innermost loop or comprehension, which knows every one around it, where a refusal happened."""
        if refused.placed:
            raise refused
        placed = ScriptRefused(refused.construct, refused.line, f"{refused.message} (in {self.where()})", refused.name)
        placed.placed = True
        raise placed from None

    def items(self, node: ast.expr, construct: str, most: int, too_many: str, over: str) -> tuple:
        """What a loop or a comprehension runs over, known in full before its first pass."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id != "range":
                _refuse(construct, node.lineno, f"{over} {_short(node.func.id)}() is not available.", _short(node.func.id))
            if node.keywords or not 1 <= len(node.args) <= 3:
                _refuse(construct, node.lineno, "range() takes one to three whole numbers, for example range(5) or range(0, 50, 10)")
            bounds = [self.value(argument) for argument in node.args]
            for index, bound in enumerate(bounds):
                # 50 // 3.5 is 14.0: a count worked out from a decimal is whole and still has its point.
                if type(bound) is float and bound.is_integer():
                    bound = bounds[index] = int(bound)
                if type(bound) is not int:
                    said = repr(bound) if type(bound) is float else _describe(bound)
                    _refuse(construct, node.lineno, f"range() takes whole numbers, got {said}: round a count down with //, for example range(length // pitch)")
            if len(bounds) == 3 and bounds[2] == 0:
                _refuse(construct, node.lineno, "range() cannot step by zero")
            steps = range(*bounds)
            if len(steps) > most:
                _refuse(construct, node.lineno, too_many)
            return tuple(steps)
        items = self.value(node)
        if not isinstance(items, tuple):
            _refuse(construct, node.lineno, f"{over} This one runs over {_describe(items)}.")
        return items

    def comprehension(self, node: ast.ListComp) -> tuple:
        """[(10 * i, 0) for i in range(3)] is the list written out: read item by item, like the passes of a loop.

        Its name is the comprehension's own, as in Python: what the name held before is
        held again after. It makes a list, never an operation, so the passes of loops do
        not count it; the work of reading does, item by item.
        """
        line = node.lineno
        if len(node.generators) != 1 or node.generators[0].ifs:
            _refuse("comprehension", line, "a comprehension has one for and no if: write the list out, or build what varies with arithmetic such as (-1) ** i")
        generator = node.generators[0]
        elements = generator.target.elts if isinstance(generator.target, ast.Tuple) else [generator.target]
        if not elements or not all(isinstance(element, ast.Name) for element in elements):
            _refuse("comprehension", line, "a comprehension counts with a plain name, or with one name per number of a point, for example: [(y, x) for x, y in points]")
        names = [self.target(element.id, line) for element in elements]
        items = self.items(generator.iter, "comprehension", table.MAX_SEQUENCE_ITEMS, f"a list holds at most {table.MAX_SEQUENCE_ITEMS} items", _COMPREHENSION_OVER)
        if not items:
            _refuse("comprehension", line, "this comprehension makes an empty list: its range or list is empty")
        held = {name: self.names[name] for name in names if name in self.names}
        made = []
        try:
            for number, item in enumerate(items, 1):
                self.spend(1, line)
                if isinstance(generator.target, ast.Tuple):
                    if not isinstance(item, tuple) or len(item) != len(names):
                        _refuse("comprehension", line, f"this comprehension takes {len(names)} names per item, and item {number} is {_short(_show(item))}")
                    values = item
                else:
                    values = (item,)
                self.names.update(zip(names, values))
                said = ", ".join(f"{name} = {_show(value)}" for name, value in list(zip(names, values))[:3]) + (", ..." if len(names) > 3 else "")
                self.loops.append((line, number, f"item {number} of the list on line {line} ({_short(said, MAX_PASS_SAID)})", number == len(items)))
                try:
                    value = self.value(node.elt)
                    if isinstance(value, tuple):
                        self.spend(len(value), line)
                    if not _holdable(value):
                        _refuse("sequence", node.elt.lineno, "a list or tuple holds numbers, booleans, or points made of numbers")
                    made.append(value)
                except ScriptRefused as refused:
                    self.place(refused)
                finally:
                    self.loops.pop()
        finally:
            for name in names:
                if name in held:
                    self.names[name] = held[name]
                else:
                    self.names.pop(name, None)
        return tuple(made)

    def where(self) -> str:
        """The passes being read, innermost first and no longer than a sentence; empty outside a loop."""
        said: list[str] = []
        for _, _, clause, _ in reversed(self.loops):
            if said and sum(map(len, said)) + len(clause) > MAX_WHERE:
                said.append(f"and {len(self.loops) - len(said)} more around it")
                break
            said.append(clause)
        return ", ".join(said)

    def expression_statement(self, node: ast.Expr) -> None:
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return  # a docstring
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id != "show_object":
                self.call(value)  # refuses, in the words for this name
            shown = value.args[0] if len(value.args) == 1 else None
            keywords_ok = all(keyword.arg == "name" and isinstance(keyword.value, ast.Constant) for keyword in value.keywords)
            if not isinstance(shown, ast.Name) or not keywords_ok or not isinstance(self.names.get(shown.id), Ref):
                _refuse("show_object", node.lineno, "show_object takes the name of one part built earlier, for example: show_object(result)")
            self.shown = (shown.id, self.names[shown.id].slot)
            self.shown_line = node.lineno
            return
        if isinstance(value, ast.Call):
            self.value(value)  # what is wrong with the call itself is the more useful answer
        _refuse("expression statement", node.lineno, "this line computes a value and drops it: assign it to a name")

    # Expressions

    def value(self, node: ast.expr) -> object:
        self.spend(1, node.lineno)
        if isinstance(node, ast.Constant):
            return self.constant(node)
        if isinstance(node, ast.Name):
            if node.id == "cq":
                _refuse("name", node.lineno, "cq can only be used as cq.Workplane(...)", "cq")
            if node.id == "math":
                _refuse("name", node.lineno, "math can only be used as math.pi, math.tau or a math function such as math.sqrt(x)", "math")
            if node.id in table.BUILTINS:
                _refuse("name", node.lineno, f"{node.id} can only be called, for example {node.id}(x)", node.id)
            if node.id not in self.names:
                _refuse("name", node.lineno, f"{_short(node.id)!r} is not defined earlier in the script", _short(node.id))
            return self.names[node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            return self.sequence(node)
        if isinstance(node, ast.Subscript):
            return self.subscript(node)
        if isinstance(node, ast.ListComp):
            return self.comprehension(node)
        if isinstance(node, ast.UnaryOp):
            operand = self.value(node.operand)
            if not _is_number(operand):
                _refuse("arithmetic", node.lineno, f"a sign applies to a number, not to {_describe(operand)}")
            return -operand if isinstance(node.op, ast.USub) else operand
        if isinstance(node, ast.BinOp):
            return self.arithmetic(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Attribute):
            # The attribute's own line: a chain starts on the line of its first name.
            line = node.end_lineno or node.lineno
            if isinstance(node.value, ast.Name) and node.value.id == "math":
                if node.attr in table.MATH_CONSTANTS:
                    return _MATH_CONSTANTS[node.attr]
                said = f"math.{_short(node.attr)}"
                if node.attr in table.MATH_FUNCTIONS:
                    _refuse("attribute", line, f"{said} is a function: call it, for example {said}(x)", said)
                _refuse("attribute", line, f"{said} is not available. {_MATH_SAID}", said)
            _refuse("attribute", line, f".{_short(node.attr)} cannot be read: a script may only call the allow-listed methods of a part", f".{_short(node.attr)}")
        _refuse("expression", node.lineno, _ALLOWED_SUMMARY)  # pragma: no cover - _check_tree refuses these first

    def constant(self, node: ast.Constant) -> object:
        value = node.value
        if value is None or isinstance(value, bool):
            return value
        if _is_number(value):
            if not _in_range(value):
                _refuse("number", node.lineno, f"numbers must be finite and no larger than {MAX_NUMBER:g}")
            return value
        if isinstance(value, str):
            if len(value) > MAX_STRING or not value.isascii() or not value.isprintable():
                _refuse("literal", node.lineno, f"strings are plain ASCII of at most {MAX_STRING} characters")
            return value
        _refuse("literal", node.lineno, "only numbers, strings, True, False and None can be written as values")

    def sequence(self, node: ast.Tuple | ast.List) -> tuple:
        if len(node.elts) > table.MAX_SEQUENCE_ITEMS:
            _refuse("sequence", node.lineno, f"a list or tuple holds at most {table.MAX_SEQUENCE_ITEMS} items")
        items = tuple(self.value(element) for element in node.elts)
        # A name may stand for a long tuple, and the check below walks each one.
        self.spend(sum(len(item) for item in items if isinstance(item, tuple)), node.lineno)
        for element, item in zip(node.elts, items):
            if not _holdable(item):
                _refuse("sequence", element.lineno, "a list or tuple holds numbers, booleans, or points made of numbers")
        return items

    def subscript(self, node: ast.Subscript) -> object:
        """p[0]: an item of a list or a point, by a whole number the reader knows. No slices."""
        base = self.value(node.value)
        index = self.value(node.slice)
        line = node.lineno
        if not isinstance(base, tuple):
            _refuse("subscript", line, f"an index picks an item of a list or a point, not of {_describe(base)}")
        if type(index) is not int:
            said = repr(index) if type(index) is float else _describe(index)
            _refuse("subscript", line, f"an index is a whole number, got {said}: for a count worked out by division, use // or int(...)")
        if not -len(base) <= index < len(base):
            _refuse("subscript", line, f"index {index} is outside this list of {len(base)}: the first item is [0] and the last is [{len(base) - 1}] or [-1]")
        return base[index]

    def math_call(self, node: ast.Call, line: int) -> int | float:
        """math.sin(x) and the rest of the table, computed by the reader on numbers it checked."""
        name = node.func.attr
        said = f"math.{_short(name)}"
        if name not in table.MATH_FUNCTIONS:
            _refuse("call", line, f"{said}() is not available. {_MATH_SAID}", said)
        fewest, most = table.MATH_FUNCTIONS[name]
        count = f"{fewest} number{'' if fewest == 1 else 's'}" if fewest == most else f"{fewest} to {most} numbers"
        if node.keywords or not fewest <= len(node.args) <= most:
            _refuse("call", line, f"{said}() takes {count}, given in order without names", said)
        arguments = [self.value(argument) for argument in node.args]
        if not all(_is_number(argument) for argument in arguments):
            _refuse("call", line, f"{said}() takes {count}, not {_describe(next(a for a in arguments if not _is_number(a)))}", said)
        try:
            result = _MATH[name](*arguments)
        except (ValueError, OverflowError):
            _refuse("arithmetic", line, f"{said}({', '.join(map(_show, arguments))}) has no answer: the number is outside what {said} takes", said)
        return self.checked(result, line, said)

    def builtin(self, node: ast.Call, line: int) -> int | float:
        """abs, min, max, round, int, float and len, on numbers and on lists the script states."""
        name = node.func.id
        if node.keywords:
            _refuse("call", line, f"{name}() takes no named arguments here", name)
        arguments = [self.value(argument) for argument in node.args]
        self.spend(sum(len(argument) for argument in arguments if isinstance(argument, tuple)), line)
        try:
            result = _BUILTIN[name](arguments, f"{name}()")
        except _Unfit as unfit:
            _refuse("call", line, str(unfit), name)
        except (ValueError, OverflowError):
            _refuse("arithmetic", line, f"{name}() has no finite answer here", name)
        return self.checked(result, line, name)

    def checked(self, value: int | float, line: int, name: str) -> int | float:
        if not _in_range(value):
            _refuse("arithmetic", line, f"the result must be a finite number no larger than {MAX_NUMBER:g}", name)
        return value

    def arithmetic(self, node: ast.BinOp) -> object:
        return self.combine(node.op, self.value(node.left), self.value(node.right), node.lineno)

    def combine(self, operator: ast.operator, left: object, right: object, line: int) -> object:
        if not _is_number(left) or not _is_number(right):
            hint = " To combine parts, call a.union(b), a.cut(b) or a.intersect(b)." if isinstance(left, Ref) or isinstance(right, Ref) else ""
            _refuse("arithmetic", line, f"arithmetic works on numbers only, not on {_describe(left if not _is_number(left) else right)}.{hint}")
        try:
            if isinstance(operator, ast.Add):
                result = left + right
            elif isinstance(operator, ast.Sub):
                result = left - right
            elif isinstance(operator, ast.Mult):
                result = left * right
            elif isinstance(operator, ast.Div):
                result = left / right
            elif isinstance(operator, ast.FloorDiv):
                result = left // right
            elif isinstance(operator, ast.Mod):
                result = left % right
            else:
                # A base of one or less cannot grow, so (-1) ** i may alternate a sign over any number of passes.
                if abs(right) > MAX_EXPONENT and abs(left) > 1:
                    _refuse("arithmetic", line, f"an exponent may not exceed {MAX_EXPONENT}")
                result = left**right
        except ZeroDivisionError:
            _refuse("arithmetic", line, "division by zero")
        except OverflowError:
            _refuse("arithmetic", line, "the result is too large")
        if isinstance(result, complex):
            _refuse("arithmetic", line, "a negative number cannot be raised to a fractional power")
        if not _in_range(result):
            _refuse("arithmetic", line, f"the result must be a finite number no larger than {MAX_NUMBER:g}")
        return result

    # Calls

    def call(self, node: ast.Call) -> Ref:
        function = node.func
        if isinstance(function, ast.Name):
            if function.id == "range":
                _refuse("call", node.lineno, "range(...) is what a loop runs over, for example: for i in range(5): It cannot be used as a value.", "range")
            if function.id in table.BUILTINS:
                return self.builtin(node, node.lineno)
            _refuse(
                "call",
                node.lineno,
                f"{_short(function.id)}() cannot be called. A script may call cq.Workplane(...), the methods of a part, the math functions and {', '.join(table.BUILTINS)}.",
                _short(function.id),
            )
        if not isinstance(function, ast.Attribute):
            _refuse("call", node.lineno, "only cq.Workplane(...) and the methods of a part can be called")
        # A chained call starts on the chain's first line; the method's own name is where it reads.
        line = function.end_lineno or node.lineno
        if function.attr.lower().startswith(_EXPORTS):
            # The usual last line of a CadQuery script. Nothing here writes a file for it.
            _refuse("export", line, "a script does not export: the tool writes the STEP, STL and GLB files itself once the part passes its checks. Delete this line.", _short(function.attr))
        if isinstance(function.value, ast.Name) and function.value.id == "cq":
            if function.attr != "Workplane":
                _refuse("call", line, f"cq.{_short(function.attr)} is not available: the only thing a script may use on cq is cq.Workplane(...)", f"cq.{_short(function.attr)}")
            return self.operation(node, line, None, "Workplane", table.CONSTRUCTOR)
        if isinstance(function.value, ast.Name) and function.value.id == "math":
            return self.math_call(node, line)
        receiver = self.value(function.value)
        if not isinstance(receiver, Ref):
            _refuse("attribute", line, f".{_short(function.attr)}() cannot be called on {_describe(receiver)}: only a part has methods", f".{_short(function.attr)}")
        method = table.METHODS.get(function.attr)
        if method is None:
            _refuse("method", line, f".{_short(function.attr)}() is not on the allow-list.{_nearest(function.attr)} {_ALL_METHODS}", _short(function.attr))
        return self.operation(node, line, receiver.slot, function.attr, method)

    def operation(self, node: ast.Call, line: int, receiver: int | None, name: str, method: table.Method) -> Ref:
        label = "cq.Workplane" if receiver is None else name
        params = {param.name: param for param in method.params}
        if len(node.args) > len(method.params):
            _refuse("argument", line, f"{label}() takes at most {len(method.params)} arguments, got {len(node.args)}", label)
        supplied: dict[str, ast.expr] = {param.name: argument for param, argument in zip(method.params, node.args)}
        for keyword in node.keywords:
            if keyword.arg not in params:
                _refuse("argument", keyword.lineno, f"{label}() has no argument {_short(keyword.arg)!r}. It takes: {', '.join(params) or 'no arguments'}", label)
            if keyword.arg in supplied:
                _refuse("argument", keyword.lineno, f"{label}() got {keyword.arg!r} twice", label)
            supplied[keyword.arg] = keyword.value
        arguments = []
        bound: dict[str, object] = {}
        for param in method.params:
            if param.name not in supplied:
                if param.required:
                    _refuse("argument", line, f"{label}() needs {param.name!r}", label)
                continue
            # An argument on its own line is refused on that line, not on the method's.
            value = self.fit(label, param, self.value(supplied[param.name]), max(line, supplied[param.name].lineno))
            bound[param.name] = value
            arguments.append((param.name, value))
        if method.instances:
            points = math.prod(len(bound[key]) if isinstance(bound[key], list) else bound[key] for key in method.instances)
            self.instances += points
            if points > table.MAX_INSTANCES_PER_CALL or self.instances > table.MAX_INSTANCES_PER_SCRIPT:
                _refuse(
                    "pattern",
                    line,
                    f"{label}() would make {points} point{'' if points == 1 else 's'}, {self.instances} in the script so far: at most {table.MAX_INSTANCES_PER_CALL} per call and {table.MAX_INSTANCES_PER_SCRIPT} per script",
                    label,
                )
        if len(self.operations) >= MAX_OPERATIONS:
            _refuse("script length", line, f"a script may perform at most {MAX_OPERATIONS} operations")
        passes = tuple((loop, number) for loop, number, _, _ in self.loops)
        site = (node.end_lineno or node.lineno, node.end_col_offset or 0)
        self.operations.append(Operation(line, receiver, name, tuple(arguments), self.where(), passes, bool(self.loops) and self.loops[-1][3], site))
        return Ref(len(self.operations) - 1)

    def fit(self, label: str, param: table.Param, value: object, line: int) -> object:
        """Return *value* in the form the kernel takes, or refuse it for this parameter."""
        kind = param.kind
        if value is None and param.nullable:
            return None
        if kind == table.PATH:
            # Decided from what the script drew, so a path that holds a solid is refused before the kernel loads.
            fitted = value if isinstance(value, Ref) and self.operations[value.slot].method in table.OUTLINES else _UNFIT
        else:
            fitted = _fit(kind, value)
        if fitted is _UNFIT:
            _refuse("argument", line, f"{label}({param.name}=...) must be {_EXPECTED[kind] if isinstance(kind, str) else 'one of ' + ', '.join(map(repr, kind))}, got {_describe(value)}", label)
        return fitted


_UNFIT = object()
_EXPECTED = {
    table.LENGTH: f"a length in millimetres from {table.MIN_LENGTH:g} to {table.MAX_MAGNITUDE:g}",
    table.NUMBER: f"a number between -{table.MAX_MAGNITUDE:g} and {table.MAX_MAGNITUDE:g}",
    table.ANGLE: f"an angle in degrees between -{table.MAX_ANGLE:g} and {table.MAX_ANGLE:g}",
    table.COUNT: f"a whole number from 1 to {MAX_COUNT}",
    table.SIDES: f"a whole number from 3 to {table.MAX_SIDES}",
    table.BOOL: "True or False",
    table.POINT: "a point of two or three numbers, for example (10, 0)",
    table.POINTS: "a list of points, for example [(0, 0), (10, 0)]",
    table.CENTERED_2D: "True, False, or one of them per axis such as (True, False)",
    table.CENTERED_3D: "True, False, or one of them per axis such as (True, True, False)",
    table.PLANE: "one of " + ", ".join(repr(name) for name in table.PLANE_NAMES),
    table.SELECTOR: "a CadQuery selector such as '>Z' or '|Z and >Y'",
    table.TAG: "a label of letters, digits and underscores",
    table.WORKPLANE: "a part built earlier in the script",
    table.PATH: "an outline drawn earlier in the script that ends with lines, arcs, a spline or a circle, for example path = cq.Workplane('XZ').polyline([(0, 0), (0, 20), (20, 20)])",
}


def _whole(value: object, minimum: int, maximum: int = MAX_COUNT) -> object:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if type(value) is int and minimum <= value <= maximum else _UNFIT


def _flags(value: object, axes: int) -> object:
    if isinstance(value, bool) or (isinstance(value, tuple) and len(value) == axes and all(isinstance(item, bool) for item in value)):
        return value
    return _UNFIT


def _point(value: object) -> object:
    if isinstance(value, tuple) and len(value) in (2, 3) and all(_is_number(item) and abs(item) <= table.MAX_MAGNITUDE for item in value):
        return value
    return _UNFIT


def _fit(kind: str | tuple[str, ...], value: object) -> object:
    if isinstance(kind, tuple):
        return value if isinstance(value, str) and value in kind else _UNFIT
    if kind == table.LENGTH:
        return value if _is_number(value) and table.MIN_LENGTH <= value <= table.MAX_MAGNITUDE else _UNFIT
    if kind == table.NUMBER:
        return value if _is_number(value) and abs(value) <= table.MAX_MAGNITUDE else _UNFIT
    if kind == table.ANGLE:
        return value if _is_number(value) and abs(value) <= table.MAX_ANGLE else _UNFIT
    if kind == table.COUNT:
        return _whole(value, 1)
    if kind == table.SIDES:
        return _whole(value, 3, table.MAX_SIDES)
    if kind == table.BOOL:
        return value if isinstance(value, bool) else _UNFIT
    if kind == table.POINT:
        return _point(value)
    if kind == table.POINTS:
        if isinstance(value, tuple) and value and all(_point(item) is not _UNFIT for item in value):
            return list(value)
        return _UNFIT
    if kind == table.CENTERED_2D:
        return _flags(value, 2)
    if kind == table.CENTERED_3D:
        return _flags(value, 3)
    if kind == table.PLANE:
        return value if isinstance(value, str) and value in table.PLANE_NAMES else _UNFIT
    if kind == table.SELECTOR:
        return value if isinstance(value, str) and _SELECTOR.fullmatch(value) else _UNFIT
    if kind == table.TAG:
        return value if isinstance(value, str) and _TAG.fullmatch(value) else _UNFIT
    if kind == table.WORKPLANE:
        return value if isinstance(value, Ref) else _UNFIT
    return _UNFIT


def _hidden_character(source: str) -> int | None:
    """Where the first character is that a viewer and the parser would not agree on, if any."""
    control = _CONTROL.search(source)
    first = control.start() if control else None
    if not source.isascii():
        for index, character in enumerate(source[:first]):
            if character > "\x7f" and (character in _DIRECTION_MARKS or unicodedata.category(character) in _HIDDEN_CATEGORIES):
                return index
    return first


def compile_script(source: str) -> Program:
    """Turn script text into allow-listed operations, or raise :class:`ScriptRefused`."""
    if not isinstance(source, str):
        _refuse("script size", None, "the script must be text")
    if len(source.encode("utf-8", "replace")) > MAX_SCRIPT_BYTES:
        _refuse("script size", None, f"the script is larger than {MAX_SCRIPT_BYTES // 1024} KiB")
    source = source.removeprefix("\ufeff")  # a byte order mark, as some editors save a file
    hidden = _hidden_character(source)
    if hidden is not None:
        # A form feed or a lone carriage return starts a new line for the parser and
        # not for a viewer, and a direction override reorders what a viewer draws: the
        # script kept beside the part must read the way it was read here.
        line = source.count("\n", 0, hidden) + 1  # nothing before it breaks a line any other way
        _refuse("syntax", line, f"the script contains a control or text-direction character (U+{ord(source[hidden]):04X}); use plain text with ordinary line breaks")
    # After the gate above only a line feed ends a line, so these are the parser's lines.
    blank = 0
    lines = source.split("\n")
    for number, text in enumerate(lines, 1):
        if len(text) > MAX_LINE:
            _refuse("syntax", number, f"this line is longer than {MAX_LINE} characters: break it into shorter lines")
        # A tab is as wide as a viewer draws it.
        drawn = text.expandtabs(TAB_WIDTH)
        if _PADDING.search(drawn):
            _refuse("syntax", number, f"this line holds more than {MAX_BLANK_RUN} blanks in a row: remove the padding")
        if drawn.strip() and len(drawn) - len(drawn.lstrip()) > MAX_INDENT:
            _refuse("syntax", number, f"this line is indented more than {MAX_INDENT} columns: move it left")
        blank = 0 if text.strip() else blank + 1
        if blank > MAX_BLANK_RUN:
            _refuse("syntax", number - blank + 1, f"more than {MAX_BLANK_RUN} blank lines in a row: remove them")
    try:
        tree = ast.parse(source, filename="<script>", mode="exec")
    except SyntaxError as exc:
        _refuse("syntax", exc.lineno, f"syntax error: {exc.msg}")
    except (ValueError, RecursionError, MemoryError):
        _refuse("nesting", None, "the script is nested too deeply to read")
    _check_tree(tree)
    _check_lines(tree.body, [text.encode("utf-8") for text in lines])
    reader = _Reader()
    try:
        for statement in tree.body:
            reader.statement(statement)
    except RecursionError:
        _refuse("nesting", None, "the script is nested too deeply to read")
    # The part is chosen by what was built: a name that held it may hold a number by now.
    if "result" in reader.names:
        held = reader.names["result"]
        if not isinstance(held, Ref):
            _refuse("result", reader.result_line, f"result must be the part, and it ends as {_describe(held)}")
        if reader.shown is not None and reader.shown[1] != held.slot:
            _refuse("result", reader.shown_line, f"result and show_object({reader.shown[0]}) name different parts: keep the one that is the part")
        chosen = ("result", held.slot)
    else:
        chosen = reader.shown or reader.last_part
    if chosen is None:
        _refuse("result", None, "the script builds no part: assign one to a name, for example result = cq.Workplane('XY').box(10, 10, 10)")
    return Program(tuple(reader.operations), chosen[1], chosen[0], reader.parameters())
