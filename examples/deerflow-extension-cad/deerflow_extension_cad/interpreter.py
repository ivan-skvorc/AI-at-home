"""Read a CadQuery script without running it.

``compile_script`` parses the text into a syntax tree and walks it. The walk
accepts ``import cadquery as cq``, assignments to plain names, numbers,
strings, tuples, lists, arithmetic on numbers, ``cq.Workplane(...)`` and calls
to the methods in :mod:`allowlist`. Everything else is refused with the
construct and its line. The outcome is a :class:`Program`: a flat list of
allow-listed operations with plain-data arguments, which ``build.run_program``
performs against the kernel.

Nothing here executes script text. ``ast.parse`` builds a tree and runs
nothing; no value from the script is ever used to look up an attribute. A
script has no loops, branches or functions, so every number is known before
the kernel starts: a refusal costs no geometry and needs no CadQuery.
"""

from __future__ import annotations

import ast
import math
import re
import unicodedata
from dataclasses import dataclass

from deerflow_extension_cad import allowlist as table

MAX_SCRIPT_BYTES = 32 * 1024
MAX_NODES = 2_000
MAX_DEPTH = 200
MAX_OPERATIONS = 300
MAX_STRING = 80
#: No number in a script, literal or computed, may exceed this.
MAX_NUMBER = 1e12
MAX_EXPONENT = 64
MAX_COUNT = 10_000

_SELECTOR = re.compile(table.SELECTOR_PATTERN)
_TAG = re.compile(table.TAG_PATTERN)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
#: Every control character but tab, line feed and the carriage return of a CRLF pair.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\r(?!\n)")
#: Beyond ASCII: controls, format characters (zero-width, direction overrides),
#: lone surrogates, and the line and paragraph separators.
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


class ScriptRefused(Exception):
    """The script asks for something a script may not contain."""

    def __init__(self, construct: str, line: int | None, message: str):
        super().__init__(f"line {line}: {message}" if line else message)
        self.construct = construct
        self.line = line
        self.message = message


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
    ast.For: "loop",
    ast.AsyncFor: "loop",
    ast.While: "loop",
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
    ast.AugAssign: "augmented assignment",
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
_ALLOWED_SUMMARY = "A script may contain: import cadquery as cq, assignments to names, numbers, strings, tuples, lists, arithmetic, cq.Workplane(...) and the allow-listed methods of a part."


def _refuse(construct: str, line: int | None, message: str):
    raise ScriptRefused(construct, line, message)


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
            _refuse("nesting", line, f"the expression is nested deeper than {MAX_DEPTH} levels")
        kind = type(node)
        if kind not in _ALLOWED:
            construct = _CONSTRUCTS.get(kind, kind.__name__.lower())
            _refuse(construct, line, f"a script may not contain a {construct}. {_ALLOWED_SUMMARY}")
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
        self.shown: str | None = None
        self.last_part: str | None = None

    # Statements

    def statement(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import):
            if len(node.names) != 1 or node.names[0].name != "cadquery" or node.names[0].asname != "cq":
                _refuse("import", node.lineno, "the only import a script may contain is: import cadquery as cq")
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                _refuse("assignment target", node.lineno, "assign one value to one plain name, for example: width = 40")
            name = self.target(node.targets[0].id, node.lineno)
            value = self.value(node.value)
            self.names[name] = value
            if isinstance(value, Ref):
                self.last_part = name
        elif isinstance(node, ast.Expr):
            self.expression_statement(node)
        else:  # pragma: no cover - _check_tree refuses every other statement first
            _refuse("statement", node.lineno, _ALLOWED_SUMMARY)

    def target(self, name: str, line: int) -> str:
        if name in ("cq", "show_object") or "__" in name or not _NAME.fullmatch(name):
            _refuse("name", line, f"{name!r} cannot be assigned: use a plain name of letters, digits and single underscores, and not cq")
        return name

    def expression_statement(self, node: ast.Expr) -> None:
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return  # a docstring
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id != "show_object":
                _refuse("call", node.lineno, f"{value.func.id}() cannot be called. A script may call cq.Workplane(...) and the methods of a part.")
            shown = value.args[0] if len(value.args) == 1 else None
            keywords_ok = all(keyword.arg == "name" and isinstance(keyword.value, ast.Constant) for keyword in value.keywords)
            if not isinstance(shown, ast.Name) or not keywords_ok or not isinstance(self.names.get(shown.id), Ref):
                _refuse("show_object", node.lineno, "show_object takes the name of one part built earlier, for example: show_object(result)")
            self.shown = shown.id
            return
        _refuse("expression statement", node.lineno, "this line computes a value and drops it: assign it to a name")

    # Expressions

    def value(self, node: ast.expr) -> object:
        if isinstance(node, ast.Constant):
            return self.constant(node)
        if isinstance(node, ast.Name):
            if node.id == "cq":
                _refuse("name", node.lineno, "cq can only be used as cq.Workplane(...)")
            if node.id not in self.names:
                _refuse("name", node.lineno, f"{node.id!r} is not defined earlier in the script")
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
            _refuse("attribute", node.lineno, f".{node.attr} cannot be read: a script may only call the allow-listed methods of a part")
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
        for item in items:
            nested = isinstance(item, tuple)
            if not (nested or isinstance(item, bool) or _is_number(item)) or (nested and any(isinstance(inner, tuple) for inner in item)):
                _refuse("sequence", node.lineno, "a list or tuple holds numbers, booleans, or points made of numbers")
        return items

    def arithmetic(self, node: ast.BinOp) -> object:
        left, right = self.value(node.left), self.value(node.right)
        if not _is_number(left) or not _is_number(right):
            hint = " To combine parts, call a.union(b), a.cut(b) or a.intersect(b)." if isinstance(left, Ref) or isinstance(right, Ref) else ""
            _refuse("arithmetic", node.lineno, f"arithmetic works on numbers only, not on {_describe(left if not _is_number(left) else right)}.{hint}")
        try:
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            elif isinstance(node.op, ast.Div):
                result = left / right
            elif isinstance(node.op, ast.FloorDiv):
                result = left // right
            elif isinstance(node.op, ast.Mod):
                result = left % right
            else:
                if abs(right) > MAX_EXPONENT:
                    _refuse("arithmetic", node.lineno, f"an exponent may not exceed {MAX_EXPONENT}")
                result = left**right
        except ZeroDivisionError:
            _refuse("arithmetic", node.lineno, "division by zero")
        except OverflowError:
            _refuse("arithmetic", node.lineno, "the result is too large")
        if not _in_range(result):
            _refuse("arithmetic", node.lineno, f"the result must be a finite number no larger than {MAX_NUMBER:g}")
        return result

    # Calls

    def call(self, node: ast.Call) -> Ref:
        function = node.func
        if isinstance(function, ast.Name):
            _refuse("call", node.lineno, f"{function.id}() cannot be called. A script may call cq.Workplane(...) and the methods of a part.")
        if not isinstance(function, ast.Attribute):
            _refuse("call", node.lineno, "only cq.Workplane(...) and the methods of a part can be called")
        # A chained call starts on the chain's first line; the method's own name is where it reads.
        line = function.end_lineno or node.lineno
        if isinstance(function.value, ast.Name) and function.value.id == "cq":
            if function.attr != "Workplane":
                _refuse("call", line, f"cq.{function.attr} is not available: the only thing a script may use on cq is cq.Workplane(...)")
            return self.operation(node, line, None, "Workplane", table.CONSTRUCTOR)
        receiver = self.value(function.value)
        if not isinstance(receiver, Ref):
            _refuse("attribute", line, f".{function.attr}() cannot be called on {_describe(receiver)}: only a part has methods")
        method = table.METHODS.get(function.attr)
        if method is None:
            _refuse("method", line, f".{function.attr}() is not on the allow-list. Available: {', '.join(sorted(table.METHODS))}")
        return self.operation(node, line, receiver.slot, function.attr, method)

    def operation(self, node: ast.Call, line: int, receiver: int | None, name: str, method: table.Method) -> Ref:
        label = "cq.Workplane" if receiver is None else name
        params = {param.name: param for param in method.params}
        if len(node.args) > len(method.params):
            _refuse("argument", line, f"{label}() takes at most {len(method.params)} arguments, got {len(node.args)}")
        supplied: dict[str, ast.expr] = {param.name: argument for param, argument in zip(method.params, node.args)}
        for keyword in node.keywords:
            if keyword.arg not in params:
                _refuse("argument", line, f"{label}() has no argument {keyword.arg!r}. It takes: {', '.join(params) or 'no arguments'}")
            if keyword.arg in supplied:
                _refuse("argument", line, f"{label}() got {keyword.arg!r} twice")
            supplied[keyword.arg] = keyword.value
        arguments = []
        bound: dict[str, object] = {}
        for param in method.params:
            if param.name not in supplied:
                if param.required:
                    _refuse("argument", line, f"{label}() needs {param.name!r}")
                continue
            value = self.fit(label, param, self.value(supplied[param.name]), line)
            bound[param.name] = value
            arguments.append((param.name, value))
        if method.instances:
            points = math.prod(len(bound[key]) if isinstance(bound[key], list) else bound[key] for key in method.instances)
            self.instances += points
            if points > table.MAX_INSTANCES_PER_CALL or self.instances > table.MAX_INSTANCES_PER_SCRIPT:
                _refuse("pattern", line, f"{label}() would make {points} points: at most {table.MAX_INSTANCES_PER_CALL} per call and {table.MAX_INSTANCES_PER_SCRIPT} per script")
        if len(self.operations) >= MAX_OPERATIONS:
            _refuse("script length", line, f"a script may perform at most {MAX_OPERATIONS} operations")
        self.operations.append(Operation(line, receiver, name, tuple(arguments)))
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
    table.SIDES: "a whole number of at least 3",
    table.BOOL: "True or False",
    table.POINT: "a point of two or three numbers, for example (10, 0)",
    table.POINTS: "a list of points, for example [(0, 0), (10, 0)]",
    table.CENTERED: "True, False, or a tuple of them such as (True, True, False)",
    table.PLANE: "one of " + ", ".join(repr(name) for name in table.PLANE_NAMES),
    table.SELECTOR: "a CadQuery selector such as '>Z' or '|Z and >Y'",
    table.TAG: "a label of letters, digits and underscores",
    table.WORKPLANE: "a part built earlier in the script",
}


def _whole(value: object, minimum: int) -> object:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if type(value) is int and minimum <= value <= MAX_COUNT else _UNFIT


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
        return _whole(value, 3)
    if kind == table.BOOL:
        return value if isinstance(value, bool) else _UNFIT
    if kind == table.POINT:
        return _point(value)
    if kind == table.POINTS:
        if isinstance(value, tuple) and value and all(_point(item) is not _UNFIT for item in value):
            return list(value)
        return _UNFIT
    if kind == table.CENTERED:
        if isinstance(value, bool) or (isinstance(value, tuple) and len(value) in (2, 3) and all(isinstance(item, bool) for item in value)):
            return value
        return _UNFIT
    if kind == table.PLANE:
        return value if isinstance(value, str) and value in table.PLANE_NAMES else _UNFIT
    if kind == table.SELECTOR:
        return value if isinstance(value, str) and _SELECTOR.fullmatch(value) else _UNFIT
    if kind == table.TAG:
        return value if isinstance(value, str) and _TAG.fullmatch(value) else _UNFIT
    if kind == table.WORKPLANE:
        return value if isinstance(value, Ref) else _UNFIT
    return _UNFIT


def _hidden_character(source: str) -> str | None:
    """The first character a viewer and the parser would not agree on, if any."""
    control = _CONTROL.search(source)
    if control:
        return control.group()[0]
    if source.isascii():
        return None
    return next((character for character in source if character > "\x7f" and unicodedata.category(character) in _HIDDEN_CATEGORIES), None)


def compile_script(source: str) -> Program:
    """Turn script text into allow-listed operations, or raise :class:`ScriptRefused`."""
    if not isinstance(source, str):
        _refuse("script size", None, "the script must be text")
    if len(source.encode("utf-8", "replace")) > MAX_SCRIPT_BYTES:
        _refuse("script size", None, f"the script is larger than {MAX_SCRIPT_BYTES // 1024} KiB")
    hidden = _hidden_character(source)
    if hidden is not None:
        # A form feed or a lone carriage return starts a new line for the parser and
        # not for a viewer, and a direction override reorders what a viewer draws: the
        # script kept beside the part must read the way it was read here.
        _refuse("syntax", None, f"the script contains an invisible or control character (U+{ord(hidden):04X}); use plain text with ordinary line breaks")
    try:
        tree = ast.parse(source, filename="<script>", mode="exec")
    except SyntaxError as exc:
        _refuse("syntax", exc.lineno, f"syntax error: {exc.msg}")
    except (ValueError, RecursionError, MemoryError):
        _refuse("nesting", None, "the script is nested too deeply to read")
    _check_tree(tree)
    reader = _Reader()
    try:
        for statement in tree.body:
            reader.statement(statement)
    except RecursionError:
        _refuse("nesting", None, "the script is nested too deeply to read")
    name = "result" if isinstance(reader.names.get("result"), Ref) else reader.shown or reader.last_part
    if name is None:
        _refuse("result", None, "the script builds no part: assign one to a name, for example result = cq.Workplane('XY').box(10, 10, 10)")
    return Program(tuple(reader.operations), reader.names[name].slot, name)
