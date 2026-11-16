"""Read a CadQuery script without running it.

``compile_script`` parses the text into a syntax tree and walks it. The walk
accepts ``import cadquery as cq``, assignments to plain names, numbers,
strings, tuples, lists, arithmetic on numbers, ``for`` loops over ``range(...)``
or a list, ``cq.Workplane(...)`` and calls to the methods in :mod:`allowlist`.
Everything else is refused with the construct and its line. The outcome is a
:class:`Program`: a flat list of allow-listed operations with plain-data
arguments, which ``build.run_program`` performs against the kernel.

Nothing here executes script text. ``ast.parse`` builds a tree and runs
nothing; no value from the script is ever used to look up an attribute. A
``for`` loop is unrolled here, pass by pass: what it runs over is a range or a
list the script states, so the loop is the same statements written out, and
the program stays flat. A script has no branches, functions or ``while``, so
every number is known before the kernel starts: a refusal costs no geometry
and needs no CadQuery.
"""

from __future__ import annotations

import ast
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

    def __init__(self, construct: str, line: int | None, message: str):
        super().__init__(f"line {line}: {message}" if line else message)
        self.construct = construct
        self.line = line
        self.message = message
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
    }
)

_CONSTRUCTS: dict[type, str] = {
    ast.ImportFrom: "import",
    ast.Lambda: "lambda",
    ast.ListComp: "comprehension",
    ast.SetComp: "comprehension",
    ast.DictComp: "comprehension",
    ast.GeneratorExp: "comprehension",
    ast.IfExp: "conditional expression",
    ast.NamedExpr: "assignment expression",
    ast.JoinedStr: "f-string",
    ast.FormattedValue: "f-string",
    ast.Subscript: "subscript",
    ast.Slice: "subscript",
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
_ONLY_IMPORT = "the only import a script may contain is: import cadquery as cq"
_ALLOWED_SUMMARY = "A script may contain: import cadquery as cq, assignments to names, numbers, strings, tuples, lists, arithmetic, for loops over range(...) or a list, cq.Workplane(...) and the allow-listed methods of a part."
_LOOP_OVER = "a loop runs over range(...) or over a list of numbers or points, for example: for i in range(5):"
#: Names a script reads and may not assign: the module, the viewer's call, and what a loop counts with.
_RESERVED = ("cq", "show_object", "range")


#: Attribute names that mean "write a file": the tool does that itself, after its checks.
_EXPORTS = ("export", "save", "tosvg")
MAX_ECHO = 60


def _refuse(construct: str, line: int | None, message: str):
    raise ScriptRefused(construct, line, message)


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
            _refuse("import", line, _ONLY_IMPORT)
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

    # Statements

    def statement(self, node: ast.stmt) -> None:
        self.spend(1, node.lineno)  # a note or an import costs a pass through here too
        if isinstance(node, ast.Import):
            if len(node.names) != 1 or node.names[0].name != "cadquery" or node.names[0].asname != "cq":
                _refuse("import", node.lineno, _ONLY_IMPORT)
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                _refuse("assignment target", node.lineno, "assign one value to one plain name, for example: width = 40")
            name = self.target(node.targets[0].id, node.lineno)
            value = self.value(node.value)
            self.names[name] = value
            if name == "result":
                self.result_line = node.lineno
            if isinstance(value, Ref):
                self.last_part = (name, value.slot)
        elif isinstance(node, ast.AugAssign):
            # x += step is x = x + step: numbers only, like the arithmetic it stands for.
            if not isinstance(node.target, ast.Name):
                _refuse("assignment target", node.lineno, "assign one value to one plain name, for example: width = 40")
            name = self.target(node.target.id, node.lineno)
            if name not in self.names:
                _refuse("name", node.lineno, f"{_short(name)!r} is not defined earlier in the script")
            self.names[name] = self.combine(node.op, self.names[name], self.value(node.value), node.lineno)
            if name == "result":
                self.result_line = node.lineno
        elif isinstance(node, ast.For):
            self.loop(node)
        elif isinstance(node, ast.Expr):
            self.expression_statement(node)
        else:  # pragma: no cover - _check_tree refuses every other statement first
            _refuse("statement", node.lineno, _ALLOWED_SUMMARY)

    def spend(self, amount: int, line: int) -> None:
        """Count what reading costs, so no script is read for longer than a moment."""
        self.work += amount
        if self.work > MAX_WORK:
            _refuse("script length", line, "the script asks for more work than a script may: its loops repeat long lists too often. Shorten the lists or the loops.")

    def target(self, name: str, line: int) -> str:
        if name in _RESERVED:
            _refuse("name", line, f"{name!r} is a name the script is given and cannot be assigned: use another name")
        if "__" in name or not _NAME.fullmatch(name):
            _refuse("name", line, f"{_short(name)!r} cannot be assigned: use a name that starts with a letter and holds letters, digits and single underscores, at most 64 characters, and not cq")
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
        if not elements or not all(isinstance(element, ast.Name) for element in elements):
            _refuse("loop", line, "a loop counts with a plain name, or with one name per number of a point, for example: for x, y in [(0, 0), (10, 0)]:")
        names = [self.target(element.id, line) for element in elements]
        items = self.loop_items(node.iter)
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
                self.names[name] = value
                if name == "result":
                    self.result_line = line
            said = ", ".join(f"{name} = {_show(value)}" for name, value in list(zip(names, values))[:3]) + (", ..." if len(names) > 3 else "")
            self.loops.append((line, number, f"pass {number} of the loop on line {line} ({_short(said, MAX_PASS_SAID)})", number == len(items)))
            try:
                for statement in node.body:
                    self.statement(statement)
            except ScriptRefused as refused:
                if refused.placed:
                    raise
                # Said once, by the innermost loop, which is the one that knows every loop around it.
                placed = ScriptRefused(refused.construct, refused.line, f"{refused.message} (in {self.where()})")
                placed.placed = True
                raise placed from None
            finally:
                self.loops.pop()

    def loop_items(self, node: ast.expr) -> tuple:
        """What a loop runs over, known in full before its first pass."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id != "range":
                _refuse("loop", node.lineno, f"{_LOOP_OVER} {_short(node.func.id)}() is not available.")
            if node.keywords or not 1 <= len(node.args) <= 3:
                _refuse("loop", node.lineno, "range() takes one to three whole numbers, for example range(5) or range(0, 50, 10)")
            bounds = [self.value(argument) for argument in node.args]
            for index, bound in enumerate(bounds):
                # 50 // 3.5 is 14.0: a count worked out from a decimal is whole and still has its point.
                if type(bound) is float and bound.is_integer():
                    bound = bounds[index] = int(bound)
                if type(bound) is not int:
                    said = repr(bound) if type(bound) is float else _describe(bound)
                    _refuse("loop", node.lineno, f"range() takes whole numbers, got {said}: round a count down with //, for example range(length // pitch)")
            if len(bounds) == 3 and bounds[2] == 0:
                _refuse("loop", node.lineno, "range() cannot step by zero")
            steps = range(*bounds)
            if len(steps) > MAX_LOOP_PASSES:
                _refuse("loop", node.lineno, f"the loops of a script may run at most {MAX_LOOP_PASSES} passes in total")
            return tuple(steps)
        items = self.value(node)
        if not isinstance(items, tuple):
            _refuse("loop", node.lineno, f"{_LOOP_OVER} This one runs over {_describe(items)}.")
        return items

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
                _refuse("name", node.lineno, "cq can only be used as cq.Workplane(...)")
            if node.id not in self.names:
                _refuse("name", node.lineno, f"{_short(node.id)!r} is not defined earlier in the script")
            return self.names[node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            return self.sequence(node)
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
            _refuse("attribute", node.end_lineno or node.lineno, f".{_short(node.attr)} cannot be read: a script may only call the allow-listed methods of a part")
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
            nested = isinstance(item, tuple)
            if not (nested or isinstance(item, bool) or _is_number(item)) or (nested and any(isinstance(inner, tuple) for inner in item)):
                _refuse("sequence", element.lineno, "a list or tuple holds numbers, booleans, or points made of numbers")
        return items

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
                _refuse("call", node.lineno, "range(...) is what a loop runs over, for example: for i in range(5): It cannot be used as a value.")
            _refuse("call", node.lineno, f"{_short(function.id)}() cannot be called. A script may call cq.Workplane(...) and the methods of a part.")
        if not isinstance(function, ast.Attribute):
            _refuse("call", node.lineno, "only cq.Workplane(...) and the methods of a part can be called")
        # A chained call starts on the chain's first line; the method's own name is where it reads.
        line = function.end_lineno or node.lineno
        if function.attr.lower().startswith(_EXPORTS):
            # The usual last line of a CadQuery script. Nothing here writes a file for it.
            _refuse("export", line, "a script does not export: the tool writes the STEP, STL and GLB files itself once the part passes its checks. Delete this line.")
        if isinstance(function.value, ast.Name) and function.value.id == "cq":
            if function.attr != "Workplane":
                _refuse("call", line, f"cq.{_short(function.attr)} is not available: the only thing a script may use on cq is cq.Workplane(...)")
            return self.operation(node, line, None, "Workplane", table.CONSTRUCTOR)
        receiver = self.value(function.value)
        if not isinstance(receiver, Ref):
            _refuse("attribute", line, f".{_short(function.attr)}() cannot be called on {_describe(receiver)}: only a part has methods")
        method = table.METHODS.get(function.attr)
        if method is None:
            _refuse("method", line, f".{_short(function.attr)}() is not on the allow-list. Available: {', '.join(sorted(table.METHODS))}")
        return self.operation(node, line, receiver.slot, function.attr, method)

    def operation(self, node: ast.Call, line: int, receiver: int | None, name: str, method: table.Method) -> Ref:
        label = "cq.Workplane" if receiver is None else name
        params = {param.name: param for param in method.params}
        if len(node.args) > len(method.params):
            _refuse("argument", line, f"{label}() takes at most {len(method.params)} arguments, got {len(node.args)}")
        supplied: dict[str, ast.expr] = {param.name: argument for param, argument in zip(method.params, node.args)}
        for keyword in node.keywords:
            if keyword.arg not in params:
                _refuse("argument", keyword.lineno, f"{label}() has no argument {_short(keyword.arg)!r}. It takes: {', '.join(params) or 'no arguments'}")
            if keyword.arg in supplied:
                _refuse("argument", keyword.lineno, f"{label}() got {keyword.arg!r} twice")
            supplied[keyword.arg] = keyword.value
        arguments = []
        bound: dict[str, object] = {}
        for param in method.params:
            if param.name not in supplied:
                if param.required:
                    _refuse("argument", line, f"{label}() needs {param.name!r}")
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
                    "pattern", line, f"{label}() would make {points} point{'' if points == 1 else 's'}, {self.instances} in the script so far: at most {table.MAX_INSTANCES_PER_CALL} per call and {table.MAX_INSTANCES_PER_SCRIPT} per script"
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
        fitted = _fit(kind, value)
        if fitted is _UNFIT:
            _refuse("argument", line, f"{label}({param.name}=...) must be {_EXPECTED[kind] if isinstance(kind, str) else 'one of ' + ', '.join(map(repr, kind))}, got {_describe(value)}")
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
    return Program(tuple(reader.operations), chosen[1], chosen[0])
