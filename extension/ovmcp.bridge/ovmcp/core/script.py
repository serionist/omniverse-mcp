"""A script the bridge runs, for /execute and a script job (#158): compiled once, told awaiting or plain, and run on
Kit's loop with no thread, since USD off Kit's main thread crashes it.

A script compiles as the standard library's asyncio REPL compiles a line, with top-level `await` allowed, and runs as
the REPL runs it: its code as a function of the script's namespace, awaited when the compiler made it a coroutine. The
compiler's flag says exactly whether the script itself awaits, which a job needs: a script that never awaits holds
Kit's main thread from its start to its end, whatever runs it.
"""

import ast
import builtins
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import CodeType, FunctionType
from typing import Any, cast

# The name a script's tracebacks give it: exec() of a string named it so before #158, and an agent reads the same
# traceback as before.
FILENAME = "<string>"
# The coroutine function a script with a top-level return runs in, as every awaiting script ran before #158.
WRAPPER = "__mcp_exec__"
_FLAGS = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
_RETURN_OUTSIDE = "'return' outside function"

NEVER_AWAITS = (
    "This script never awaits, so it would hold Kit's main thread from its start to its end: Kit wouldn't render, and "
    "nothing could read or cancel the job. Await in its loop, `await omni.kit.app.get_app().next_update_async()` once "
    "a step, so Kit updates between steps; or run a short script with execute_script."
)


@dataclass(frozen=True)
class Script:
    code: CodeType
    awaits: bool  # whether the script's own code awaits, outside any function it defines
    returns: bool  # compiled inside WRAPPER, for a top-level return


def compile_script(source: str | bytes, filename: str = FILENAME) -> Script:
    """`source` compiled, with top-level `await` allowed; bytes decoded as Python decodes a source file (PEP 263).

    A top-level `return`, which the compiler refuses there, ran before #158 inside a coroutine function the script was
    indented into: such a script still runs inside one, built from its own syntax tree so its lines keep their
    numbers, and what it returns is its result. Any other SyntaxError is raised.
    """
    try:
        code = compile(source, filename, "exec", flags=_FLAGS, dont_inherit=True)
    except SyntaxError as e:
        if e.msg != _RETURN_OUTSIDE:
            raise
        return _returning(source, filename)
    return Script(code, _is_coroutine(code), returns=False)


def _is_coroutine(code: CodeType) -> bool:
    return bool(code.co_flags & inspect.CO_COROUTINE)


class _ReturnsDropped(ast.NodeTransformer):
    """A script's top-level returns as expressions, its functions left as they are: what the compiler makes of the
    rest says whether the script awaits."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return node

    def visit_Return(self, node: ast.Return) -> ast.AST:
        return ast.copy_location(ast.Expr(node.value) if node.value is not None else ast.Pass(), node)


def _returning(source: str | bytes, filename: str) -> Script:
    plain = _ReturnsDropped().visit(ast.parse(source, filename))
    awaits = _is_coroutine(compile(plain, filename, "exec", flags=_FLAGS, dont_inherit=True))
    wrapper = ast.parse(f"async def {WRAPPER}():\n    return locals().get('result')\n", filename)
    function = cast("ast.AsyncFunctionDef", wrapper.body[0])
    function.body[:0] = ast.parse(source, filename).body
    return Script(compile(wrapper, filename, "exec", dont_inherit=True), awaits, returns=True)


async def run(script: Script, namespace: dict[str, Any]) -> None:
    """Runs `script` in `namespace`, on the caller's task: its names and its `result` land there.

    As a function of the namespace, not through exec(): a module's code, called so, reads and writes its names in the
    namespace as exec() would, and a coroutine comes back when the script awaits (the asyncio REPL runs a line so).
    """
    namespace.setdefault("__builtins__", builtins.__dict__)
    ran = FunctionType(script.code, namespace)()
    if inspect.iscoroutine(ran):
        await ran
    if script.returns:
        returned = await namespace.pop(WRAPPER)()
        if returned is not None:
            namespace["result"] = returned


def jsonable(value: Any) -> Any:
    """A script's result as the bridge sends it: as it is when JSON holds it, else its str."""
    if value is None:
        return None
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def read_file(path: str) -> tuple[bytes, str]:
    """A script file on Kit's machine: its bytes, for the compiler to decode as Python's source rules say, and its
    absolute path, which its tracebacks name and read its lines from. OSError when it can't be read."""
    absolute = Path(path).resolve()
    return absolute.read_bytes(), str(absolute)
