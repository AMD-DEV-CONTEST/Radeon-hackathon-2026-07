#!/usr/bin/env python3
"""Determinex I/O-example extractor.

Turns a tool's shipped pytest suite into concrete black-box examples:
    {test, argv, stdin, env, expect_rc, expect_stdout (exact), expect_in[...]}
by AST-parsing each test function for its run-helper invocation and assertions,
and resolving golden-file references (`(RESOURCES / "x.golden").read_text()`)
against the actual golden files on disk. These examples are ground truth -- the
local oracle (determinex_local_oracle) runs the reimpl against them with zero
network and no Docker, so a fix is validated in milliseconds before any eval.

It is deliberately CONSERVATIVE: an example is emitted only when argv is
recoverable AND at least one expectation (rc / exact stdout / contains) is
known. Anything ambiguous is skipped and counted -- never a guessed expectation,
so the oracle never reports false confidence.

PB-compliant: read-only over the shipped tests. It never edits a test, a golden,
collection, or the eval.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUN_NAMES = {
    "run",
    "run_exe",
    "run_hx",
    "run_cmd",
    "_run",
    "run_executable",
    "run_minimap",
    "run_nomino",
    "run_tool",
    "invoke",
    "execute",
}
STDIN_KW = {"stdin", "input", "input_bytes", "input_text", "input_data", "input_str", "stdin_data"}
ARGS_KW = {"args", "argv", "arguments"}
RESULT_ATTRS = {"returncode", "code", "rc"}

# WRAPPER-NAME AUTO-DISCOVERY (2026-07-16): RUN_NAMES is a hardcoded allowlist that was being
# grown one tool-specific name at a time (run_minimap, run_nomino are literally per-tool
# entries). Audited against the real corpus: 210,040 observed tests, 148,132 (70.5%) silently
# skipped by extract_file/extract_dir. A single real case (jq) recovered ~20% of its own skips
# by adding ONE missing name (run_jq) -- and different jq test-suite BRANCHES used run_exe,
# run_jq, and other names for the exact same underlying subprocess wrapper, proving a static
# name list can never keep pace across ~200 real tools each with their own convention. Fixed
# by resolving BEHAVIOR instead of NAME: any locally-defined function (in the test file itself
# or a sibling conftest.py/utils.py/helpers.py/common.py/testutils.py) whose body directly
# calls subprocess.run/Popen/call/check_output/check_call or os.system/os.popen is treated as
# an ad-hoc runner for THIS test directory, regardless of what it's named.
_SHELL_CALL_ATTRS = {"run", "Popen", "call", "check_output", "check_call"}
_OS_SHELL_ATTRS = {"system", "popen"}
_SHELL_MODULE_NAMES = {"subprocess", "sp"}
_OS_MODULE_NAMES = {"os"}
_HELPER_FILENAMES = ("conftest.py", "utils.py", "helpers.py", "common.py", "testutils.py")


def _shells_out(func: ast.FunctionDef, extra_names: set | None = None) -> bool:
    """Does this function's body directly invoke a subprocess/shell call, or call a name
    already known to be a runner (a wrapper-of-a-wrapper)? Used only to WIDEN which call
    sites _find_run_call considers -- a false positive here just means a name that still has
    to pass the real argv-resolution logic below to matter, so it carries no regression risk.

    `extra_names` (2026-07-17) lets the CHAINED-WRAPPER fixed-point loop in
    _discover_wrapper_names check against names discovered in an EARLIER pass, not just the
    static RUN_NAMES set -- see that function's docstring for why this matters (lua_exec/
    run_lua_cmd/run_binary never shell out directly THEMSELVES, they call an already-
    discovered wrapper)."""
    known = RUN_NAMES | (extra_names or set())
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            base = f.value.id
            if (base in _SHELL_MODULE_NAMES and f.attr in _SHELL_CALL_ATTRS) or (
                base in _OS_MODULE_NAMES and f.attr in _OS_SHELL_ATTRS
            ):
                return True
        elif isinstance(f, ast.Name) and f.id in known:
            return True
    return False


def _discover_wrapper_names(tree: ast.Module, path: Path) -> set[str]:
    """Per-file/per-directory auto-discovered runner names: scan this file's own AST plus
    any sibling helper module for functions that shell out, regardless of their name.

    CHAINED WRAPPERS (2026-07-17): a fixture-factory (or plain function) can expose a run
    name that TESTS actually call without ever shelling out itself -- it just calls an
    ALREADY-discovered wrapper and forwards its own parameters. Found via lua's
    `run_lua_cmd(lua_exec)` (its closure does `return run_lua([lua_exec] + args, ...)`) and
    cheat's `run_binary(binary_path)` (`return run_cheat(binary_path, args, ...)`): neither
    shells out directly, so the original single-pass _shells_out(node) (checking only the
    static RUN_NAMES) never recognized run_lua_cmd/run_binary as run names at all -- the
    TEST's own call to them was rejected before argv resolution even started, corpus-wide
    (yj/cheat/lua sat at 65-99% skip because of exactly this gap). Iterates to a fixed
    point (bounded by candidate count) so a chain three-or-more deep also resolves: pass 1
    finds run_lua/run_cheat (direct subprocess calls); pass 2 finds run_lua_cmd/run_binary
    (call something pass 1 found); a hypothetical pass 3 would find a wrapper of THOSE."""
    candidates: list[ast.FunctionDef] = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    ]
    for helper_name in _HELPER_FILENAMES:
        hp = path.parent / helper_name
        if not hp.exists() or hp == path:
            continue
        try:
            htree = ast.parse(hp.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        candidates.extend(node for node in ast.walk(htree) if isinstance(node, ast.FunctionDef))

    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in candidates:
            if node.name in names:
                continue
            if _shells_out(node, names):
                names.add(node.name)
                changed = True
    return names


def _shells_out_own_body(func: ast.FunctionDef, extra_names: set | None = None) -> bool:
    """Like _shells_out, but scoped to THIS function's own statements only -- does not
    descend into a nested FunctionDef. Needed to tell apart 'run_duckdb shells out
    itself' (false -- its own body just defines+returns a closure) from 'run_duckdb
    shells out via a nested closure it returns' (true, but the CLOSURE is the real
    target for keyword-flag introspection, not run_duckdb's own parameter list).

    `extra_names` (2026-07-17): same chained-wrapper need as _shells_out's own
    extra_names -- a nested closure can call an ALREADY-DISCOVERED wrapper (cheat's
    run_binary's `_run` calls `run_cheat(binary_path, args)`, itself only known via a
    previous fixed-point pass, not the static RUN_NAMES) rather than shelling out
    directly. Without this, _discover_wrapper_kwarg_flags could name run_binary as a
    run NAME (via _discover_wrapper_names' own fixed point) but never find ITS base,
    silently producing argv missing the executable placeholder entirely -- confidently
    wrong, not just skipped, since the aggregate recovery count doesn't change (the
    test still counts as 'resolved', just with an incomplete argv)."""
    known = RUN_NAMES | (extra_names or set())

    def walk_own_scope(n):
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ast.FunctionDef) and child is not func:
                continue  # nested def has its own scope -- don't descend into it
            yield child
            yield from walk_own_scope(child)

    for node in walk_own_scope(func):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            base = f.value.id
            if (base in _SHELL_MODULE_NAMES and f.attr in _SHELL_CALL_ATTRS) or (
                base in _OS_MODULE_NAMES and f.attr in _OS_SHELL_ATTRS
            ):
                return True
        elif isinstance(f, ast.Name) and f.id in known:
            return True
    return False


def _find_returned_inner_closure(node: ast.FunctionDef) -> ast.FunctionDef | None:
    """If `node`'s top-level body defines a nested closure and then returns it by bare
    name (`def _run(...): ...; return _run`), return that inner FunctionDef. This is the
    'fixture-factory' shape (found for xh's run_binary, duckdb's run_duckdb): the OUTER
    function's own body never calls subprocess directly, but a closure it builds and
    returns does -- and that closure's OWN parameters (not the outer function's) are what
    a caller's keyword arguments actually bind to at the call site."""
    inner_names = {n.name: n for n in node.body if isinstance(n, ast.FunctionDef)}
    if not inner_names:
        return None
    for stmt in ast.walk(node):
        if isinstance(stmt, (ast.Return, ast.Expr)) and stmt is not node:
            val = stmt.value if isinstance(stmt, ast.Return) else stmt.value
            if isinstance(val, ast.Name) and val.id in inner_names:
                return inner_names[val.id]
    return None


_KWARG_PASSTHROUGH = "\x00passthrough\x00"
_KWARG_APPEND_PASSTHROUGH = "\x00append_passthrough\x00"


def _extract_kwarg_flag_map(func: ast.FunctionDef) -> dict[str, str]:
    """Learn, from a run-wrapper's OWN body, which of ITS keyword parameters map to a
    literal CLI flag: the `if <kwname>: <cmd>.extend([<literal>, <kwname>])` idiom (found
    in duckdb's conftest.py: `if sql: cmd.extend(["-c", sql])`), OR a PASSTHROUGH --
    `if <kwname>: <cmd>.extend(<kwname>)` -- where the kwarg's own LIST VALUE is spliced
    in verbatim, no fixed flag prefix at all (found via ditaa's whole test suite:
    `if extra_args: args.extend(extra_args)`, called as `run_ditaa(input_file,
    output_file, extra_args=["-v"])`). Before this, an unrecognized kwarg like
    extra_args silently matched NOTHING in _find_run_call's keyword loop -- not treated
    as unresolvable (there's no abort path for keywords, only positional args), so the
    candidate resolved SUCCESSFULLY but missing the extra_args contribution entirely: a
    confidently WRONG example (correctly-shaped but incomplete argv), worse than the
    correctly-skipped case, found by hand-checking real ditaa call sites rather than by
    the aggregate count. Passthrough is marked with the sentinel _KWARG_PASSTHROUGH
    (distinct from any real CLI flag string) so _find_run_call knows to splice the
    kwarg's resolved list value directly rather than treating it as `[flag, value]`.
    Never generalized further without a real sample, matching this chain's discipline
    of sizing before generalizing."""
    param_names = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
    out: dict[str, str] = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Name) and test.id in param_names):
            continue
        kwname = test.id
        for stmt in node.body:
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
                continue
            call = stmt.value
            if not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr == "append" and len(call.args) == 1:
                # SINGLE-VALUE APPEND PASSTHROUGH (2026-07-17): `if flags:
                # cmd.append(flags)` -- yj's whole conftest.py (run_yj(flags="-h")) --
                # the kwarg's own STRING value appended directly as ONE argv token,
                # distinct from _KWARG_PASSTHROUGH (which splices a LIST kwarg's
                # elements). Marked with its own sentinel since _find_run_call's
                # handling differs: no isinstance(v, list) unwrap, just str(v).
                arg0 = call.args[0]
                if isinstance(arg0, ast.Name) and arg0.id == kwname:
                    out[kwname] = _KWARG_APPEND_PASSTHROUGH
                continue
            if call.func.attr != "extend":
                continue
            if len(call.args) != 1:
                continue
            arg0 = call.args[0]
            if isinstance(arg0, ast.Name) and arg0.id == kwname:
                out[kwname] = _KWARG_PASSTHROUGH
                continue
            if not isinstance(arg0, ast.List):
                continue
            elts = arg0.elts
            if len(elts) != 2:
                continue
            flag_c = _const(elts[0])
            if isinstance(flag_c, str) and isinstance(elts[1], ast.Name) and elts[1].id == kwname:
                out[kwname] = flag_c
    return out


def _is_executable_path_expr(node) -> bool:
    """True if `node` (optionally wrapped in str(...)) is a path expression whose final
    `/`-joined component is the literal string 'executable' -- matches the oracle's own
    placeholder convention (determinex_local_oracle._drop_binary_placeholder strips any
    argv[0] whose basename is 'executable'). Doesn't need the full absolute path resolved
    (which may depend on a conftest.py-level constant like WORKSPACE_ROOT) -- only the
    trailing literal component matters for this convention."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
    ):
        node = node.args[0]
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if _const(node.right) == "executable":
            return True
        node = node.left
    # A single STRING LITERAL containing slashes, e.g. Path("../executable") or a bare
    # "./executable" (2026-07-17) -- yj's whole conftest.py: `candidates = [
    # Path("../executable"), Path("./executable"), Path(__file__).parent... /
    # "executable"]` -- the first two are never built via a BinOp/Div chain at all (the
    # separators are baked directly into one string), so the while-loop above never
    # even runs. Checked via the SAME basename-splitting reasoning fix 32 already
    # applies to bare string constants, just also unwrapping an outer Path(...) call.
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Path"
        and len(node.args) == 1
    ):
        node = node.args[0]
    c = _const(node)
    if isinstance(c, str) and c.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] == "executable":
        return True
    return False


def _discover_custom_scratch_dir_fixtures(tree: ast.Module) -> set[str]:
    """Find @pytest.fixture names that hand back a fresh, per-test SCRATCH DIRECTORY
    built directly from `tempfile.TemporaryDirectory()` under a CUSTOM name, rather than
    pytest's own built-in `tmp_path`/`tmpdir`:

        @pytest.fixture
        def temp_dir():
            with tempfile.TemporaryDirectory() as tmpdir:
                yield Path(tmpdir)

    Found via ditaa's whole test suite (`output_file = temp_dir / "output.png"`, then
    `run_ditaa(input_file, output_file)`) -- semantically IDENTICAL scratch-directory
    reasoning to tmp_path/tmpdir (a fresh, empty, per-test location the tool creates
    output into), just under an arbitrary fixture name. Returned names get merged with
    the hardcoded {"tmp_path", "tmpdir"} set wherever scratch-base checking happens
    (_track_local_scratch_vars, _file_arg's inline scratch-path case)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        uses_tempfile = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "TemporaryDirectory"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "tempfile"
            for n in ast.walk(node)
        )
        if uses_tempfile:
            names.add(node.name)
    return names


def _track_local_scratch_vars(func: ast.FunctionDef, scratch_bases: set) -> dict[str, str]:
    """Map a TEST-LOCAL variable name -> literal basename, for `output_file = temp_dir /
    "output.png"` assignments where the base is a KNOWN scratch-directory name (pytest's
    own tmp_path/tmpdir, or a custom fixture from _discover_custom_scratch_dir_fixtures)
    -- the SAME reasoning _track_scratch_path_fixtures applies to a FIXTURE's own body,
    generalized to a plain local assignment inside a TEST function. Found via ditaa's
    whole test suite: `output_file` is then passed BARE (no str() wrap) to
    `run_ditaa(input_file, output_file)`, resolved via the ordinary vars_map bare-Name
    lookup _resolve already does -- no special _file_arg handling needed once this is
    merged into vars_map."""
    out: dict[str, str] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.BinOp)
            and isinstance(node.value.op, ast.Div)
            and isinstance(node.value.left, ast.Name)
            and node.value.left.id in scratch_bases
        ):
            rhs = _const(node.value.right)
            if isinstance(rhs, str):
                out[node.targets[0].id] = rhs
    return out


def _discover_temp_file_factory_fixtures(tree: ast.Module) -> set[str]:
    """Find @pytest.fixture names that hand back a CALLABLE FACTORY producing a fresh
    real scratch file path via `tempfile.mkstemp(...)` each time it's invoked:

        @pytest.fixture
        def temp_audio_file():
            files = []
            def _temp_file(suffix=".wav"):
                fd, path = tempfile.mkstemp(suffix=suffix)
                os.close(fd)
                files.append(path)
                return path
            yield _temp_file
            for f in files: os.unlink(f)

    Found via sox's whole test suite (1320 occurrences across 21 test files):
    `input_file = temp_audio_file(".wav")` then `output_file = temp_audio_file(".wav")`
    -- TWO calls in the SAME test, each producing a genuinely DISTINCT real path (mkstemp
    guarantees uniqueness), unlike tmp_path/tmpdir's single shared directory. This is a
    different shape from _discover_custom_scratch_dir_fixtures (that one wraps
    TemporaryDirectory and hands back a directory to divide with `/`; this one wraps
    mkstemp and hands back a ready-made FILE path from a call, no division needed)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        uses_mkstemp = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "mkstemp"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "tempfile"
            for n in ast.walk(node)
        )
        if uses_mkstemp:
            names.add(node.name)
    return names


def _track_temp_file_factory_vars(func: ast.FunctionDef, factory_names: set) -> dict[str, str]:
    """Map a TEST-LOCAL variable assigned from a CALL to a known temp-file-factory
    fixture (`input_file = temp_audio_file(".wav")`) to a distinct literal basename --
    each call site gets its own scratch file (never shared, since mkstemp guarantees a
    fresh path per real call and sox's tests routinely call the factory twice in one
    test for a distinct input vs output file). Basename is built from a per-function
    call counter plus the literal suffix argument if given (`.wav`), so
    `scratch_0.wav`, `scratch_1.wav`, ... -- falls back to no extension if the suffix
    arg isn't a plain string constant. Resolved the same way any other local constant
    is, via the ordinary vars_map bare-Name lookup -- no _file_arg wiring needed."""
    out: dict[str, str] = {}
    counter = 0
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in factory_names
        ):
            suffix = ""
            if node.value.args:
                s = _const(node.value.args[0])
                if isinstance(s, str):
                    suffix = s
            elif node.value.keywords:
                for kw in node.value.keywords:
                    if kw.arg == "suffix":
                        s = _const(kw.value)
                        if isinstance(s, str):
                            suffix = s
            out[node.targets[0].id] = f"scratch_{counter}{suffix}"
            counter += 1
    return out


def _discover_temp_files_object_fixtures(tree: ast.Module) -> set[str]:
    """Find @pytest.fixture names that hand back a CUSTOM OBJECT wrapping a real
    tempfile.mkdtemp() scratch directory, exposing `.create(name, content)` (stage a
    real file) and `.path(name="")` (resolve a path inside the scratch dir, or the
    dir itself when name is omitted) methods:

        @pytest.fixture
        def temp_files():
            tempdir = tempfile.mkdtemp()
            class TempFiles:
                def create(self, name, content=""): ...
                def path(self, name=""): ...
            yield TempFiles(tempdir)
            shutil.rmtree(tempdir, ignore_errors=True)

    Found via dust's whole test suite (278 occurrences of `temp_files.*` in ONE
    tool's tests alone; the identical class shape also confirmed in caps-log,
    samtools, htop, and gdal this same session) -- a shared idiom across many
    tools, not a single-tool quirk. Distinct from _discover_custom_scratch_dir_fixtures
    (that one yields the bare directory itself, divided with `/` at call sites) and
    _discover_temp_file_factory_fixtures (mkstemp-based, yields a callable producing
    a fresh FILE per call) -- this one yields an OBJECT with METHOD calls, a third
    distinct shape. Detected structurally: the fixture body calls
    `tempfile.mkdtemp()` (not TemporaryDirectory's context-manager form) AND defines
    a nested ClassDef with a method named "create" -- narrow enough to avoid
    over-matching an unrelated tempdir-based fixture."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        uses_mkdtemp = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "mkdtemp"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "tempfile"
            for n in ast.walk(node)
        )
        has_create_method = any(
            isinstance(n, ast.ClassDef)
            and any(isinstance(m, ast.FunctionDef) and m.name == "create" for m in n.body)
            for n in ast.walk(node)
        )
        if uses_mkdtemp and has_create_method:
            names.add(node.name)
    return names


def _track_temp_files_object_creates(
    func: ast.FunctionDef, obj_names: set, vars_map: dict
) -> dict[str, tuple[str, str]]:
    """Map a real basename -> its staged content, for `<obj>.create(name, content)`
    calls (a bare statement expression, return value not captured) where `<obj>` is
    one of the test's own temp-files-object fixture parameters. `name` and `content`
    both resolve via the ordinary _resolve() path (handles f-strings, literals, and
    -- since fix 36's _const Mult support -- `"x" * 10000`-style repetition), so
    dust's whole `temp_files.create("large.txt", "x" * 10000)` family resolves
    without any special-casing here."""
    out: dict[str, tuple[str, str]] = {}
    for node in ast.walk(func):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "create"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in obj_names
        ):
            continue
        if len(call.args) < 1:
            continue
        name = _resolve(call.args[0], vars_map)
        if not isinstance(name, str):
            continue
        content = ""
        if len(call.args) >= 2:
            c = _resolve(call.args[1], vars_map)
            content = c if isinstance(c, (str, bytes)) else ""
        out[name] = (
            name,
            content if isinstance(content, str) else content.decode("utf-8", "replace"),
        )
    return out


def _discover_temp_files_context_manager_classes(tree: ast.Module) -> set[str]:
    """Find module-level classes (not wrapped in @pytest.fixture at all) matching the
    SAME temp-files-object API (`.create(name, content)`) but exposed as a
    CONTEXT MANAGER instead of a fixture:

        class TempFiles:
            def __enter__(self):
                self.tempdir = tempfile.mkdtemp()
                return self
            def __exit__(self, *args):
                shutil.rmtree(self.tempdir, ignore_errors=True)
            def create(self, name, content): ...
            def path(self, name): ...

        def test_dataset_copy():
            with TempFiles() as tf:
                dst = str(tf.path("copy.tif"))
                result = run("dataset", "copy", BYTE_TIF, dst)

    Found via gdal's whole test suite (355 occurrences across 44 files -- the
    dominant remaining blocker after fix 36, which only handled the FIXTURE-
    parameter binding of this same object shape). The class itself is IDENTICAL
    in spirit to fix 36's target (mkdtemp-backed, .create()/.path() methods) --
    only the BINDING differs: a `with ClassName() as var` inside the TEST'S OWN
    body, not a pytest fixture parameter, so `var`'s name is local to each test
    function rather than a single tool-wide fixture parameter name. Returns the
    CLASS names; _track_with_block_scratch_objects resolves the per-test bound
    variable name(s) separately."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        method_names = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
        if "__enter__" in method_names and "create" in method_names:
            names.add(node.name)
    return names


def _track_with_block_scratch_objects(func: ast.FunctionDef, class_names: set) -> set[str]:
    """Find `with <ClassName>() as <var>:` inside a TEST'S OWN body, where
    `ClassName` is one of the discovered temp-files context-manager classes --
    returns the bound variable name(s) so the caller can treat them exactly like a
    fixture-parameter temp-files object for the REST of that test's own body (same
    .create()/.path() resolution, no further special-casing needed)."""
    out: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in class_names
                and isinstance(item.optional_vars, ast.Name)
            ):
                out.add(item.optional_vars.id)
    return out


def _is_path_wrap_call(node) -> bool:
    """True for `Path(<expr>)` / `pathlib.Path(<expr>)` -- exactly one positional
    arg, either bare-imported or attribute-qualified Path."""
    return (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "Path")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "Path")
        )
    )


def _resolve_temp_files_path_chain(
    node, obj_names: set, vars_map: dict | None = None
) -> str | None:
    """Resolve a temp-files-object `.path()` reference, INCLUDING a further `/
    "literal"` division chained onto a no-arg call -- caps-log's whole test suite
    (635 occurrences): `log_dir = tf.path() / "logs"` (further dividing the
    scratch-ROOT reference fix 36/37 already resolves to "."), sometimes several
    levels deep (`tf.path() / "a" / "b"`), and sometimes chained onto an ALREADY
    -RESOLVED var rather than a bare `.path()` call: `year_dir = log_dir /
    "y2026"` then `log_file = year_dir / "d2026_03_25.md"` (both caps-log
    fixtures). ALSO handles the sibling shape from a DIFFERENT temp-files-object
    convention (calcurse, 590 occurrences): the same class exposes its scratch
    dir as a bare PUBLIC ATTRIBUTE (`self.tempdir`) instead of a `.path()`
    method -- `tf.tempdir` used directly as an argv arg, or `Path(tf.tempdir) /
    "conf"` further divided. Handles, in order: a plain `<obj>.path()` (-> "."),
    `<obj>.path(name)` (-> name), a bare `<obj>.tempdir` OR `Path(<obj>.tempdir)`
    (-> "."), a BinOp/Div chain whose ultimate LEFT base is one of the above, OR
    whose base is a bare Name already present in `vars_map` (a prior-assignment
    chain) -- joining each `/`-appended literal onto it with "/", mirroring how a
    real Path join would read once staged relative to the fresh per-call rundir.
    Unwraps an outer str(...) first if present. Never guesses past an
    unresolvable literal or a base that isn't one of the above shapes."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
    ):
        node = node.args[0]
    suffix_parts: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        rhs = _const(node.right)
        if not isinstance(rhs, str):
            return None
        suffix_parts.append(rhs)
        node = node.left
    unwrapped = node
    if isinstance(node, ast.Call) and _is_path_wrap_call(node):
        unwrapped = node.args[0]
    if (
        isinstance(unwrapped, ast.Attribute)
        and unwrapped.attr == "tempdir"
        and isinstance(unwrapped.value, ast.Name)
        and unwrapped.value.id in obj_names
    ):
        base = "."
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "path"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in obj_names
    ):
        if not node.args:
            base = "."
        else:
            base = _const(node.args[0])
            if not isinstance(base, str):
                return None
    elif vars_map is not None and isinstance(node, ast.Name) and node.id in vars_map:
        base = vars_map[node.id]
    else:
        return None
    parts = [base] if base != "." else []
    parts.extend(reversed(suffix_parts))
    return "/".join(parts) if parts else "."


def _track_temp_files_path_vars(func: ast.FunctionDef, obj_names: set) -> dict[str, str]:
    """Map a TEST-LOCAL variable assigned from `<obj>.path(name)` (optionally
    further divided, `<obj>.path() / "logs"`, or str()-wrapped) to that resolved
    literal path -- gdal's whole test suite assigns the result to a local var
    FIRST (`dst = str(tf.path('copy.tif'))`), referenced bare later; caps-log's
    whole test suite does the same but with a further `/ "logs"` division on top
    of a no-arg `.path()` call, sometimes chained several assignments deep
    (`log_dir = tf.path() / "logs"`; `year_dir = log_dir / "y2026"`; `log_file =
    year_dir / "d2026_03_25.md"`). _file_arg's own `.path()` handling only
    recognizes the call written DIRECTLY at the argv call site -- this covers the
    assignment-removed case(s), the same reasoning _track_local_scratch_vars
    already applies to `tmp_path / 'x'`-style assignments. Assignments are
    processed in SOURCE ORDER (not ast.walk's traversal order) and the growing
    `out` dict is fed back into each resolution so a later var can chain off an
    earlier one."""
    out: dict[str, str] = {}
    assigns = sorted(
        (
            n
            for n in ast.walk(func)
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
        ),
        key=lambda n: (n.lineno, n.col_offset),
    )
    for node in assigns:
        target = node.targets[0]
        assert isinstance(target, ast.Name)
        resolved = _resolve_temp_files_path_chain(node.value, obj_names, out)
        if resolved is not None:
            out[target.id] = resolved
    return out


def _track_scratch_path_fixtures(tree: ast.Module) -> dict[str, str]:
    """Map a @pytest.fixture's name -> a literal basename string, for fixtures that hand
    back a fresh, per-test SCRATCH path built from pytest's own tmp_path/tmpdir (never
    real staged content, just a location the tool creates itself):

        @pytest.fixture
        def temp_db(tmp_path):
            db_path = tmp_path / "test.db"
            yield str(db_path)

    Found in duckdb's conftest.py, feeding `cmd = [str(executable), temp_db]` inside
    run_duckdb's returned closure. Verified by reading determinex_local_oracle.py's
    _run_reimpl: every Example already runs in a FRESH per-call uuid rundir, so a bare
    relative basename ('test.db') naturally lands in a fresh, empty location with ZERO
    oracle-side changes needed -- nothing to stage. Scoped narrowly to a base literally
    named `tmp_path` or `tmpdir` (pytest's own built-in temp-dir fixtures, always
    fresh-per-test) -- never applied to any other unresolvable base, which would wrongly
    relativize a real content path like `RESOURCES / 'golden.txt'` too (a
    _PathResolver-resolvable, fixed, real file, not a scratch location)."""
    scratch_bases = {"tmp_path", "tmpdir"}
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        local_basenames: dict[str, str] = {}
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.BinOp)
                and isinstance(stmt.value.op, ast.Div)
                and isinstance(stmt.value.left, ast.Name)
                and stmt.value.left.id in scratch_bases
            ):
                rhs = _const(stmt.value.right)
                if isinstance(rhs, str):
                    local_basenames[stmt.targets[0].id] = rhs
        if not local_basenames:
            continue
        for stmt in ast.walk(node):
            val = None
            if isinstance(stmt, ast.Return) and stmt.value is not None:
                val = stmt.value
            elif (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Yield)
                and stmt.value.value is not None
            ):
                val = stmt.value.value
            if val is None:
                continue
            target_name = None
            if (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Name)
                and val.func.id == "str"
                and len(val.args) == 1
                and isinstance(val.args[0], ast.Name)
            ):
                target_name = val.args[0].id
            elif isinstance(val, ast.Name):
                target_name = val.id
            if target_name in local_basenames:
                out[node.name] = local_basenames[target_name]
                break
    return out


def _discover_content_to_file_fixtures(tree: ast.Module) -> dict[str, str]:
    """Map a @pytest.fixture's name -> the DEFAULT basename its returned closure writes
    to, for fixture-factories CALLED WITH CONTENT that stage it to a fresh scratch file
    and return the path:

        @pytest.fixture
        def temp_js_file(tmp_path):
            def _create(content, name="test.js"):
                file_path = tmp_path / name
                file_path.write_text(content)
                return file_path
            return _create

    Found via quickjs's whole test suite (`script = temp_js_file(some_js_source)`, then
    `run_qjs(str(script))`): a DIFFERENT shape from the existing 'name, content' fixture-
    helper _track_files already recognizes (`tf = temp_files.create("test.tex",
    content)`) -- here content comes FIRST and the name is an OPTIONAL keyword with its
    own default, resolved from the closure's own signature rather than the call site.
    Scoped narrowly to the same tmp_path/tmpdir scratch-base convention
    _track_scratch_path_fixtures already trusts (a fresh, empty, per-test location --
    nothing else needs staging beyond the content itself)."""
    scratch_bases = {"tmp_path", "tmpdir"}
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        inner = _find_returned_inner_closure(node)
        if inner is None:
            continue
        params = inner.args.args
        defaults = inner.args.defaults
        if len(params) != 2 or len(defaults) != 1:
            continue
        content_param, name_param = params[0].arg, params[1].arg
        default_name = _const(defaults[0])
        if not isinstance(default_name, str):
            continue
        # Body must be exactly: `<var> = <scratch_base> / name; <var>.write_text(content);
        # return <var>` (or write_bytes) -- never guess past this precise shape.
        body = inner.body
        if len(body) < 3:
            continue
        assign, write_call, ret = body[0], body[1], body[-1]
        if not (
            isinstance(assign, ast.Assign)
            and len(assign.targets) == 1
            and isinstance(assign.targets[0], ast.Name)
            and isinstance(assign.value, ast.BinOp)
            and isinstance(assign.value.op, ast.Div)
            and isinstance(assign.value.left, ast.Name)
            and assign.value.left.id in scratch_bases
            and isinstance(assign.value.right, ast.Name)
            and assign.value.right.id == name_param
        ):
            continue
        path_var = assign.targets[0].id
        if not (
            isinstance(write_call, ast.Expr)
            and isinstance(write_call.value, ast.Call)
            and isinstance(write_call.value.func, ast.Attribute)
            and write_call.value.func.attr in ("write_text", "write_bytes")
            and isinstance(write_call.value.func.value, ast.Name)
            and write_call.value.func.value.id == path_var
            and len(write_call.value.args) == 1
            and isinstance(write_call.value.args[0], ast.Name)
            and write_call.value.args[0].id == content_param
        ):
            continue
        if not (
            isinstance(ret, ast.Return)
            and isinstance(ret.value, ast.Name)
            and ret.value.id == path_var
        ):
            continue
        out[node.name] = default_name
    return out


def _extract_wrapper_base_argv(
    target: ast.FunctionDef,
    extra_vars: dict,
    outer_path_exprs: dict | None = None,
    exec_param_names: set | None = None,
    scratch_bases: set | None = None,
) -> tuple[list | None, list | None]:
    """Find the FIRST `cmd_var = [...]` list assignment in target's body (the same list
    _extract_kwarg_flag_map found being .extend()-ed per-keyword) and resolve each
    element via extra_vars, or the 'executable' placeholder convention for a path
    expression ending in that literal component. The executable-path expression is often
    one indirection away (`executable = WORKSPACE_ROOT / "executable"` on an earlier
    line, then `cmd = [str(executable), ...]` referencing the bare Name) rather than
    inline at the list-literal site -- resolved here by scanning target's own local
    assignments for the SAME bare-Name-to-path-expression shape before falling through to
    a direct check. Returns None (never guesses) the moment any element can't be resolved
    this way.

    Also handles the `cmd = [str(EXECUTABLE)] + args` shape (BinOp Add of a List and the
    wrapper's own variadic-args parameter) found in gomplate/bedtools2/run's conftest.py
    -- functionally identical to duckdb's plain-List `cmd = [...]` for base-argv purposes
    (the `+ args` side is the caller-supplied argv, already handled by _find_run_call's
    own positional/ARGS_KW resolution), just a different AST shape for the SAME idiom.
    Sized: 3 of the top-4 remaining-skip tools (gomplate, bedtools2, esubaalew__run) all
    use this exact `[prefix] + args` concatenation instead of duckdb's flat list.

    `outer_path_exprs` covers the executable-placeholder being MODULE-level (not local to
    target or its enclosing fixture) -- gomplate/bedtools2/run all define
    `EXECUTABLE = Path(__file__).parent... / "executable"` once at conftest.py module
    scope and reference the bare Name from inside the closure; duckdb's original
    one-assignment-removed case was function-local, this is one scope further out."""
    local_path_exprs: dict[str, ast.AST] = dict(outer_path_exprs or {})
    for stmt in ast.walk(target):
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            local_path_exprs[stmt.targets[0].id] = stmt.value

    exec_params = exec_param_names or set()

    def is_exec_ref(node) -> bool:
        if _is_executable_path_expr(node):
            return True
        inner = node
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "str"
            and len(inner.args) == 1
        ):
            inner = inner.args[0]
        if isinstance(inner, ast.Name) and inner.id in local_path_exprs:
            candidate = local_path_exprs[inner.id]
            # ENV-VAR OVERRIDE WITH A PATH-EXPR/STRING FALLBACK (2026-07-17): gdal's
            # whole conftest.py: `EXECUTABLE = os.environ.get('GDAL_EXECUTABLE',
            # str(Path(__file__).parent.parent.parent / "executable"))` -- lets the
            # harness override the binary location via env var while defaulting to
            # the standard placeholder convention. Neither _is_executable_path_expr
            # nor the plain-string check (fix 32) unwraps an os.environ.get()/
            # os.getenv() CALL at all -- _const() has no special case for it either.
            # Unwrap to the DEFAULT (second positional arg, or a `default=` keyword)
            # and apply the SAME two checks to that expression instead.
            if isinstance(candidate, ast.Call):
                fn = candidate.func
                is_env_get = (
                    (
                        # os.environ.get(key, default) -- fn.value is os.environ, itself
                        # an Attribute(Name('os'), 'environ'), not a bare Name('os').
                        isinstance(fn, ast.Attribute)
                        and fn.attr == "get"
                        and isinstance(fn.value, ast.Attribute)
                        and fn.value.attr == "environ"
                        and isinstance(fn.value.value, ast.Name)
                        and fn.value.value.id == "os"
                    )
                    or (
                        # os.getenv(key, default)
                        isinstance(fn, ast.Attribute)
                        and fn.attr == "getenv"
                        and isinstance(fn.value, ast.Name)
                        and fn.value.id == "os"
                    )
                    or (
                        # bare getenv(key, default), e.g. `from os import getenv`
                        isinstance(fn, ast.Name) and fn.id == "getenv"
                    )
                )
                if is_env_get:
                    default = (
                        candidate.args[1]
                        if len(candidate.args) >= 2
                        else next((k.value for k in candidate.keywords if k.arg == "default"), None)
                    )
                    if default is not None:
                        candidate = default
            if _is_executable_path_expr(candidate):
                return True
            # A bare STRING CONSTANT whose basename is "executable" -- samtools's
            # whole conftest.py: `EXECUTABLE = "/workspace/executable"`, never built
            # via a Path(...)./ chain at all (_is_executable_path_expr only unwraps
            # BinOp/Div components), so the placeholder convention was otherwise
            # invisible even though the real value's basename already matches the
            # oracle's own _drop_binary_placeholder convention exactly.
            c = _const(candidate)
            if (
                isinstance(c, str)
                and c.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] == "executable"
            ):
                return True
        # A bare Name matching a known EXECUTABLE FIXTURE parameter (e.g. lua's
        # `run_lua_cmd(lua_exec)`, where `lua_exec` is a fixture that itself resolves to
        # 'executable' via _fixture_return_const) -- not a path EXPRESSION at all, just a
        # parameter whose bound value IS the executable placeholder.
        if isinstance(inner, ast.Name) and inner.id in exec_params:
            return True
        return False

    def resolve_list_literal(list_node: ast.List) -> list | None:
        out = []
        for elt in list_node.elts:
            if is_exec_ref(elt):
                out.append("executable")
                continue
            v = _resolve(elt, extra_vars)
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                out.append(str(v))
            else:
                return None
        return out

    own_param_names = {a.arg for a in target.args.args}
    sbases = scratch_bases or set()

    def scratch_rhs(expr) -> str | None:
        if (
            isinstance(expr, ast.BinOp)
            and isinstance(expr.op, ast.Div)
            and isinstance(expr.left, ast.Name)
            and expr.left.id in sbases
        ):
            rhs = _const(expr.right)
            if isinstance(rhs, str):
                return rhs
        return None

    def resolve_elt(elt) -> str | None:
        """Resolve one SUFFIX element (a token appended after the wrapper's own
        positional-parameter slot): exec-ref, ordinary constant/vmap Name/str(Name),
        or a scratch-dir-relative expression (`temp_dir / 'output.svg'` -- the SAME
        reasoning _track_local_scratch_vars applies to a TEST body, here applied
        inline to the wrapper's own local assignment instead). ditaa's real shape is
        `output_file = temp_dir / "output.svg"` on an earlier line, THEN `args.append(
        str(output_file))` -- the append site only sees the bare Name, so the scratch
        check must run against output_file's OWN bound expression (already collected
        into local_path_exprs above for the executable-ref case), not the append call's
        argument node directly."""
        if is_exec_ref(elt):
            return "executable"
        inner = elt
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "str"
            and len(inner.args) == 1
        ):
            inner = inner.args[0]
        if isinstance(inner, ast.Name) and inner.id in local_path_exprs:
            hit = scratch_rhs(local_path_exprs[inner.id])
            if hit is not None:
                return hit
        hit = scratch_rhs(elt)
        if hit is not None:
            return hit
        v = _resolve(elt, extra_vars)
        return str(v) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else None

    def is_own_param_ref(node) -> bool:
        inner = node
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "str"
            and len(inner.args) == 1
        ):
            inner = inner.args[0]
        return isinstance(inner, ast.Name) and inner.id in own_param_names

    def extract_suffix(cmd_var: str) -> list | None:
        """SUFFIX AFTER THE CALLER'S OWN PARAMETER (2026-07-17): ditaa's whole
        test_svg.py: `args = [EXECUTABLE]; args.append(str(input_file));
        args.append(str(output_file)); args.append('--svg')` -- `input_file` is the
        wrapper's OWN parameter (the existing additive this_base + pos_strs model
        already handles that slot), but `output_file` (a wrapper-LOCAL scratch var,
        `temp_dir / 'output.svg'`) and the literal '--svg' come AFTER it, a SUFFIX the
        prefix-only base model has no way to represent. Before this, run_ditaa_svg's
        base was learned as just ['executable'] with no suffix at all, so the call
        site's own positional arg was silently the ENTIRE remainder of argv --
        missing output_file/--svg/etc. entirely: a confidently WRONG example.
        Scans target's OWN top-level statements (not the assignment's siblings via
        ast.walk, which loses source order) for `cmd_var.append(X)`/`.extend(X)`
        calls; only tokens AFTER the first own-param reference count as suffix, and
        the scan stops at the first ast.If (that's fix 26's conditional-flag
        territory) or the first unresolvable element -- never guesses past either."""
        saw_param = False
        suffix: list[str] = []
        for stmt in target.body:
            if isinstance(stmt, ast.If):
                break
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
                continue
            call = stmt.value
            if not (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == cmd_var
                and call.func.attr in ("append", "extend")
            ):
                continue
            if len(call.args) != 1:
                continue
            arg0 = call.args[0]
            if is_own_param_ref(arg0):
                saw_param = True
                continue
            if not saw_param:
                continue  # a fixed element BEFORE the param slot -- already in base
            if call.func.attr == "extend":
                break  # a bare .extend(name) after the param slot is fix 26's job
            v = resolve_elt(arg0)
            if v is None:
                return None  # can't fully resolve the suffix -- never guess a partial one
            suffix.append(v)
        return suffix if saw_param else None

    for stmt in ast.walk(target):
        if not (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            continue
        val = stmt.value
        if isinstance(val, ast.List):
            out = resolve_list_literal(val)
            if out:
                return out, extract_suffix(stmt.targets[0].id)
        elif (
            isinstance(val, ast.BinOp)
            and isinstance(val.op, ast.Add)
            and isinstance(val.left, ast.List)
            and _is_args_passthrough(val.right)
        ):
            out = resolve_list_literal(val.left)
            if out:
                return out, extract_suffix(stmt.targets[0].id)

    # CHAINED-WRAPPER INLINE CONCAT (2026-07-17): `return run_lua([lua_exec] + args, ...)`
    # -- the base+args concatenation used DIRECTLY as a call argument to another (already-
    # discovered) wrapper, never bound to a local variable first. Found via lua's
    # run_lua_cmd: its whole body is one bare `return <call>(...)`, so the assignment-based
    # scan above finds nothing at all. Only the shape of the concatenation matters here
    # (matching _is_args_passthrough), not which function is being called -- that's
    # resolved separately by _find_run_call's own positional/keyword handling at the
    # actual call site.
    #
    # STARRED *args UNPACK IN A LIST LITERAL (2026-07-17): `[EXECUTABLE, *args]` --
    # semantically IDENTICAL to `[EXECUTABLE] + list(args)` (the BinOp+Add shape just
    # above), just written as a list-literal unpack instead of concatenation. Found via
    # caps-log's whole conftest.py: `def run(*args, stdin=None, ...): return
    # subprocess.run([EXECUTABLE, *args], input=..., ...)` -- "run" is already a
    # hardcoded RUN_NAME so every call site (`run("-h")`, imported directly and called
    # with NO fixture indirection at all) matched a real run-call node, but neither
    # existing scan recognized a Starred element inside a List (resolve_list_literal's
    # per-element loop has no ast.Starred handling, only bare elements) -- base/flags
    # both failed, "run" was never registered as a learned wrapper, and the call's own
    # single argument ("-h") became the ENTIRE argv: `['-h']`, missing the executable
    # entirely. Scoped to the vararg matching the wrapper's OWN `*args` parameter
    # (`target.args.vararg`), as the list's LAST element only -- anything after it would
    # break the additive this_base + pos_strs model the same way fix 29 already guards.
    #
    # ANY CALL NODE, NOT JUST return-WRAPPED (2026-07-17, htop/yq/gdal/dust/tparse/
    # bartib/ethabi/xcp/serpl -- 10 tools sharing this exact gap): `result =
    # subprocess.run([EXECUTABLE, *args], ...); return result` -- an intermediate
    # ASSIGNMENT between the call and the return, found via htop's try/except-wrapped
    # run() (the timeout fallback branch returns a different, unrelated object). The
    # original scan required `isinstance(stmt, ast.Return) and isinstance(stmt.value,
    # ast.Call)` -- a bare `return result` has stmt.value as a Name, never a Call, so
    # this whole shape was invisible regardless of how the list itself was built.
    # Widened to walk EVERY Call node in the function body directly (dropping the
    # Return-wrapper requirement entirely) -- the call's own arguments are what matter,
    # not whether its result is returned directly, assigned first, or ignored.
    vararg_name = target.args.vararg.arg if target.args.vararg else None
    for call_node in ast.walk(target):
        if not isinstance(call_node, ast.Call):
            continue
        for arg in call_node.args:
            if (
                isinstance(arg, ast.BinOp)
                and isinstance(arg.op, ast.Add)
                and isinstance(arg.left, ast.List)
                and _is_args_passthrough(arg.right)
            ):
                out = resolve_list_literal(arg.left)
                if out:
                    return out, None
            if (
                isinstance(arg, ast.List)
                and arg.elts
                and vararg_name is not None
                and isinstance(arg.elts[-1], ast.Starred)
                and isinstance(arg.elts[-1].value, ast.Name)
                and arg.elts[-1].value.id == vararg_name
            ):
                out = resolve_list_literal(ast.List(elts=arg.elts[:-1], ctx=ast.Load()))
                if out is not None:
                    return out, None

    # SINGLE LIST LITERAL WITH OWN-PARAMETER TAIL (2026-07-17): a wrapper whose ENTIRE
    # argv is one list literal passed DIRECTLY as a call argument (subprocess.run's own
    # first positional arg), never bound to a variable first and never a `[prefix] +
    # args` concatenation -- `["java", "-cp", str(EXECUTABLE), classname]` where
    # `classname` is the wrapper's OWN parameter (ditaa's whole test_stringutils.py:
    # `def run_java_class(classname, timeout=10): subprocess.run(["java", "-cp",
    # str(EXECUTABLE), classname], ...)`). Before this, base/flags both failed to
    # resolve at all, so run_java_class was never registered as a learned wrapper --
    # at the call site `run_java_class("org.foo.Bar")`, its own arg was then treated AS
    # the real argv directly (the un-learned "run(*args) style" fallback), producing
    # argv=['org.foo.Bar'] with "java"/"-cp"/the executable silently missing entirely: a
    # confidently WRONG example, not a skip. Scoped conservatively: only matches if the
    # own-parameter reference(s) are a contiguous TAIL of the list (nothing fixed comes
    # after them) -- this fits the existing additive this_base + pos_strs model exactly
    # (the call site's own positional args get appended after this_base in the same
    # order); any other arrangement is left unresolved rather than guessed."""
    for stmt in ast.walk(target):
        if not (isinstance(stmt, ast.Call) and stmt.args and isinstance(stmt.args[0], ast.List)):
            continue
        elts = stmt.args[0].elts
        tail_start = next(
            (i for i, e in enumerate(elts) if isinstance(e, ast.Name) and e.id in own_param_names),
            None,
        )
        if tail_start is None:
            continue
        if any(
            not (isinstance(e, ast.Name) and e.id in own_param_names) for e in elts[tail_start:]
        ):
            continue  # a fixed/other element follows an own-param ref -- don't guess
        out = resolve_list_literal(ast.List(elts=elts[:tail_start], ctx=ast.Load()))
        if out is not None:
            return out, None
    return None, None


def _is_args_passthrough(node) -> bool:
    """True for the right-hand side of `[prefix...] + <this>` where `<this>` is the
    wrapper's own caller-supplied argv continuation: a bare Name (gomplate/bedtools2's
    `args` keyword param) OR `list(<Name>)` (quickjs's `def _run(*args, ...): cmd =
    [str(EXECUTABLE)] + list(args)` -- *args is a tuple, wrapped in list() before the
    concatenation). Either way the actual VALUES are the caller's own positional/args=
    argv, already resolved separately by _find_run_call -- only the SHAPE matters here,
    never the bound name, so no attempt is made to match it against the vararg name."""
    if isinstance(node, ast.Name):
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "list"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
    ):
        return True
    return False


def _discover_wrapper_kwarg_flags(tree: ast.Module, path: Path) -> dict[str, dict]:
    """Map a runner NAME (as used at call sites, e.g. 'run_duckdb') -> {"base": [...],
    "flags": {kwarg: flag}} for keyword arguments _find_run_call's fixed ARGS_KW/STDIN_KW
    sets don't cover, plus the wrapper's own fixed base argv elements (e.g. a scratch
    database path the wrapper always prepends). Sized via duckdb: `run_duckdb(sql=...)`
    -- 4005 of 4015 total run_duckdb(...) calls use this exact keyword, none of it
    captured by the existing generic keyword sets. Checks the function itself first
    (matching wrappers that DIRECTLY shell out), then falls back to a returned inner
    closure (the fixture-factory shape) since the keyword semantics live on whichever
    function actually builds the command -- never the outer fixture's own (different)
    parameter list. The base-argv resolution needs BOTH scopes when the target is a
    nested closure (its free variables, like duckdb's `executable`/`temp_db`, are bound in
    the OUTER fixture's scope), so vars_map merges the outer node's locals, the outer
    node's OWN parameters resolved via _track_scratch_path_fixtures (temp_db -> 'test.db'),
    and the inner target's own locals."""
    result: dict[str, dict] = {}
    trees = [tree]
    for helper_name in _HELPER_FILENAMES:
        hp = path.parent / helper_name
        if not hp.exists() or hp == path:
            continue
        try:
            trees.append(ast.parse(hp.read_text(encoding="utf-8", errors="replace")))
        except SyntaxError:
            continue
    # EXECUTABLE-FIXTURE PARAMETER NAMES (2026-07-17): a wrapper can take the executable
    # as a FIXTURE parameter (lua's run_lua_cmd(lua_exec), cheat's run_cheat(binary_path,
    # ...)) rather than resolving a path expression itself -- computed once across all
    # trees (the fixture is usually in conftest.py, the wrapper using it may be in either)
    # via the same _fixture_return_const executable-detection _track_fixtures already
    # does, then passed to _extract_wrapper_base_argv so a bare reference to one of these
    # PARAMETER NAMES resolves to the 'executable' placeholder too.
    exec_param_names = {
        name for t in trees for name, val in _track_fixtures(t).items() if val == "executable"
    }
    # SCRATCH-DIR-YIELDING FIXTURE NAMES (2026-07-17): needed by _extract_wrapper_base_argv's
    # suffix-extraction to resolve a wrapper-LOCAL scratch var like ditaa's
    # `output_file = temp_dir / "output.svg"` -- `temp_dir` is the OUTER fixture's own
    # parameter (a free variable inside the inner closure), not a files_map/vars_map entry,
    # so the same {"tmp_path","tmpdir"} | custom-scratch-dir-fixture reasoning
    # _track_local_scratch_vars applies to TEST bodies is applied here to a WRAPPER body.
    scratch_bases = {"tmp_path", "tmpdir"}
    for t in trees:
        scratch_bases |= _discover_custom_scratch_dir_fixtures(t)
    # Build the full candidate list (node + its own tree's scratch/module-path context)
    # up front so the fixed-point loop below can re-scan every candidate on each pass --
    # same CHAINED-WRAPPER need as _discover_wrapper_names/_discover_wrapper_return_shapes:
    # a nested closure can call an ALREADY-DISCOVERED wrapper (cheat's run_binary's `_run`
    # calls `run_cheat(binary_path, args)`) rather than shelling out directly, so
    # _shells_out_own_body must be re-checked against the GROWING result set, not just
    # the static RUN_NAMES, on subsequent passes. Found via cheat's real corpus: run_binary
    # is correctly recognized as a run NAME (via _discover_wrapper_names' own fixed point)
    # but without this, its BASE is never found -- every recovered example silently missed
    # the executable placeholder entirely (argv=['--version'] instead of ['executable',
    # '--version']), a confidently-wrong result the aggregate recovery count doesn't
    # reveal (the test still counts as 'resolved').
    candidates: list[tuple[ast.FunctionDef, dict, dict]] = []
    for t in trees:
        scratch_fixtures = _track_scratch_path_fixtures(t)
        module_path_exprs = {
            stmt.targets[0].id: stmt.value
            for stmt in t.body
            if isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        }
        for node in ast.walk(t):
            if isinstance(node, ast.FunctionDef):
                candidates.append((node, scratch_fixtures, module_path_exprs))

    changed = True
    while changed:
        changed = False
        known_names = set(result.keys())
        for node, scratch_fixtures, module_path_exprs in candidates:
            if node.name in result:
                continue
            is_nested_closure = _shells_out_own_body(node, known_names)
            target = node if is_nested_closure else _find_returned_inner_closure(node)
            if target is None:
                continue
            flags = _extract_kwarg_flag_map(target)
            outer_vars = _track_vars(node)
            outer_params_resolved = {
                a.arg: scratch_fixtures[a.arg] for a in node.args.args if a.arg in scratch_fixtures
            }
            extra_vars = {**outer_vars, **outer_params_resolved, **_track_vars(target)}
            base, suffix = _extract_wrapper_base_argv(
                target, extra_vars, module_path_exprs, exec_param_names, scratch_bases
            )
            if not (flags or base):
                # DELEGATE WITH SEPARATE PARAMS (2026-07-17): cheat's run_binary closure
                # is `return run_cheat(binary_path, args)` -- binary_path and args passed
                # as SEPARATE positional arguments, not concatenated into one list at all
                # (run_cheat does that internally). Not a passthrough of args alone (that's
                # _discover_wrapper_return_shapes' job) and not an inline concat (that's
                # the BinOp case above) -- the callee (run_cheat) already has its own
                # resolved base+flags contract, so if the sole return is a bare call to an
                # ALREADY-known wrapper, inherit its entire contract directly: calling
                # run_binary(["--version"]) really does end up running the exact same
                # base+flags run_cheat itself would build.
                body = target.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body = body[1:]
                if (
                    len(body) == 1
                    and isinstance(body[0], ast.Return)
                    and isinstance(body[0].value, ast.Call)
                    and isinstance(body[0].value.func, ast.Name)
                    and body[0].value.func.id in result
                ):
                    inherited = result[body[0].value.func.id]
                    flags, base, suffix = inherited["flags"], inherited["base"], inherited["suffix"]
            if flags or base:
                result[node.name] = {"base": base or [], "flags": flags, "suffix": suffix or []}
                changed = True
    return result


def _discover_fixture_wrapper_aliases(
    tree: ast.Module, path: Path, known_names: set
) -> dict[str, str]:
    """A @pytest.fixture whose body is just `return <name>` -- no Call at all -- exposes an
    ALIAS for an already-known runner under the fixture's own name, e.g. (found in xh's
    conftest.py):

        def run_xh(*args, ...): ...subprocess.run(['./executable', *args])...  # real impl
        _run_xh_func = run_xh                    # captured before the name gets shadowed
        @pytest.fixture
        def xh():
            return _run_xh_func

    A test taking `xh` as a parameter then calls it directly (`xh('--print=B', ...)`).
    `_discover_wrapper_names`/`_shells_out` only look for a direct subprocess/known-runner
    CALL inside a function body -- a bare `return <name>` has no Call node to match, so
    "xh" was never added to extra_run_names even though "run_xh" was (from the plain
    function def). Resolves one hop of simple module-level `alias = name` assignment
    (`_run_xh_func = run_xh`) so the fixture's returned name reaches a known runner, then
    registers the FIXTURE's own name as an additional alias. Same file + sibling helper
    modules as _discover_wrapper_names; never guesses past one assignment hop.

    Returns alias name -> its REAL target name (2026-07-17, dropbear's whole test
    suite: `def run_cmd(): return run_binary` where run_binary is a well-learned
    wrapper with a real base/flags/suffix contract) -- previously only a bare set of
    alias NAMES, discarding which target each aliases. Without the target, callers
    could mark "run_cmd" as a VALID run-name (so _find_run_call doesn't skip its call
    nodes) but had no way to propagate run_binary's actual LEARNED base contract to
    run_cmd's own name in kwarg_flags -- is_learned_wrapper stayed False at every
    run_cmd(...) call site, so the caller's own args became the WHOLE argv, missing
    the executable path entirely: confidently wrong, not a skip."""
    alias_of: dict[str, str] = {}

    def _scan_module(t: ast.Module):
        for node in ast.walk(t):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Name)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                alias_of[node.targets[0].id] = node.value.id

    trees = [tree]
    for helper_name in _HELPER_FILENAMES:
        hp = path.parent / helper_name
        if not hp.exists() or hp == path:
            continue
        try:
            trees.append(ast.parse(hp.read_text(encoding="utf-8", errors="replace")))
        except SyntaxError:
            continue
    for t in trees:
        _scan_module(t)

    found: dict[str, str] = {}
    for t in trees:
        for node in ast.walk(t):
            if not isinstance(node, ast.FunctionDef):
                continue
            is_fx = False
            for d in node.decorator_list:
                tgt = d.func if isinstance(d, ast.Call) else d
                if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                    isinstance(tgt, ast.Name) and tgt.id == "fixture"
                ):
                    is_fx = True
            if not is_fx:
                continue
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]  # skip a leading docstring
            if len(body) != 1 or not isinstance(body[0], ast.Return):
                continue
            ret = body[0].value
            if not isinstance(ret, ast.Name):
                continue
            target = alias_of.get(ret.id, ret.id)
            if target in known_names:
                found[node.name] = target
    return found


@dataclass
class Example:
    test: str
    argv: list = field(default_factory=list)
    stdin: str | None = None  # decoded text; None = no stdin
    env: dict = field(default_factory=dict)
    expect_rc: int | None = None
    # NONZERO RC (2026-07-17): `assert result.returncode != 0` -- a real, common "must fail"
    # shape (bedtools2's whole test_sortandnaming_* family: sort-order/naming-conflict error
    # cases). Distinct from expect_rc (an EXACT value): the test only ever claims "some
    # failure", never which one -- recording it as expect_rc=1 (or any specific code) would
    # be a guess the real test doesn't make. Scoped to the literal `!= 0` shape only; `!= N`
    # for a specific nonzero N is a different, rarer claim left unresolved rather than
    # conflated with this one.
    expect_rc_nonzero: bool = False
    # RC MEMBERSHIP (2026-07-17): `assert result.returncode in [0, 1]` -- a real, common
    # "either success or this specific known failure is acceptable" shape (calcurse: 72
    # occurrences of this exact top-level pattern). Distinct from expect_rc (exact) and
    # expect_rc_nonzero (any nonzero): the test claims membership in a SPECIFIC small set
    # of literal ints, no more and no less -- recording expect_rc=0 would be too strict (a
    # correct candidate returning 1 would wrongly fail), recording expect_rc_nonzero would
    # be wrong the other direction (0 is explicitly allowed). Scoped to a List/Tuple of
    # int constants only -- never guessed past that.
    expect_rc_in: list = field(default_factory=list)
    expect_stdout: str | None = None  # exact match (from golden or literal)
    expect_stderr: str | None = None  # exact match (reference-enriched: the real stderr)
    expect_in: list = field(default_factory=list)  # substrings asserted present (AND: all required)
    # OR-GROUPS (2026-07-16): `assert A in out or B in out` means "at least one of these",
    # a claim expect_in's AND semantics can't represent -- naively adding both to expect_in
    # would wrongly demand BOTH. Each entry here is one OR-group: a list of alternatives
    # where at least one must be present. Precisely sized before building (per this corpus's
    # own established discipline): 172/627 (27.4%) of a real tool's (stgit) skipped tests
    # have this exact top-level `assert X or Y` shape -- the single largest pattern found
    # in the whole skip-rate investigation chain.
    expect_in_any: list = field(default_factory=list)
    # NEGATIVE ASSERTIONS (2026-07-16): `assert "unexpected argument" not in output` -- the
    # semantic mirror of expect_in (must NOT appear, vs must appear). Unlike expect_in_any,
    # this needed no AND/OR design decision: it's always a simple universal negation. Sized
    # before building: 77/520 (14.8%) of a real tool's (codesnap) skipped tests have this
    # exact top-level `assert X not in Y` shape.
    expect_not_in: list = field(default_factory=list)
    files: dict = field(default_factory=dict)  # filename -> content for file-arg tests
    ci: bool = False  # contains check is case-insensitive
    # (test compared against .lower()/.casefold())
    source: str = ""  # test file:line


@dataclass
class Coverage:
    examples: list
    n_tests: int
    n_examples: int
    skipped: list  # test names we couldn't pin down


# --- small constant / path evaluators -------------------------------------


def _const(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for e in node.elts:
            v = _const(e)
            if v is _UNK:
                return _UNK
            out.append(v)
        return out
    if isinstance(node, ast.Call):
        # str(x) / bytes(...) wrappers around constants
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "str" and node.args:
            v = _const(node.args[0])
            return _UNK if v is _UNK else str(v)
    if isinstance(node, ast.JoinedStr):  # f-strings -> only if all literal
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                return _UNK
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        # STRING/BYTES REPETITION (2026-07-17): `"x" * 1000` -- a very common
        # test-data-generation idiom for large-file content (dust's whole test suite:
        # `temp_files.create("large.txt", "x" * 10000)`), previously invisible to
        # _const at all (no Mult handling whatsoever). Either operand order is valid
        # Python (`"x"*N` or `N*"x"`); only fires when one side is a literal
        # str/bytes and the other a literal non-bool int, matching Python's own
        # repetition semantics exactly -- never guesses past that.
        left, right = _const(node.left), _const(node.right)
        if (
            isinstance(left, (str, bytes))
            and isinstance(right, int)
            and not isinstance(right, bool)
        ):
            return left * right
        if isinstance(right, (str, bytes)) and isinstance(left, int) and not isinstance(left, bool):
            return right * left
        return _UNK
    return _UNK


_UNK = object()


def _resolve_fstring_with_vars(node: ast.AST, vars_map: dict) -> str | None:
    """Resolve an f-string to a literal string when every interpolated {expr} part is
    either itself a literal constant, OR a bare local variable already bound to a
    resolvable constant via _track_vars (`f"stat {missing}"` where
    `missing = "/tmp/some/path"` earlier in the function). Never guesses -- returns None
    the moment any part can't be resolved this way, same discipline as _const()."""
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(str(v.value))
            continue
        if not isinstance(v, ast.FormattedValue):
            return None
        c = _const(v.value)
        if c is _UNK and isinstance(v.value, ast.Name) and v.value.id in vars_map:
            c = vars_map[v.value.id]
        if c is _UNK or isinstance(c, (list, dict)):
            return None
        parts.append(str(c))
    return "".join(parts)


def _argv_strs(value):
    """Coerce an extracted list into a list[str] argv, or None if not usable."""
    if value is _UNK or value is None:
        return None
    if not isinstance(value, list):
        return None
    out = []
    for v in value:
        if isinstance(v, bool):
            return None
        if isinstance(v, (str, int, float)):
            out.append(str(v))
        else:
            return None
    return out


class _PathResolver:
    """Resolves module-level path vars like
    RESOURCES = Path(__file__).parent.parent / "test_resources" / "test_function"
    so golden references can be read from disk."""

    def __init__(self, test_file: Path):
        self.test_file = test_file
        self.vars: dict[str, Path] = {}

    def learn(self, tree: ast.Module):
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    p = self.eval_path(node.value)
                    if p is not None:
                        self.vars[tgt.id] = p

    def eval_path(self, node) -> Path | None:
        # Path(__file__) ...
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Path"
            and node.args
        ):
            a = node.args[0]
            if isinstance(a, ast.Name) and a.id == "__file__":
                return self.test_file
            c = _const(a)
            if isinstance(c, str):
                return Path(c)
            return None
        if isinstance(node, ast.Attribute):  # .parent
            base = self.eval_path(node.value)
            if base is None:
                return None
            if node.attr == "parent":
                return base.parent
            return None
        if isinstance(node, ast.Name):
            return self.vars.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            base = self.eval_path(node.left)
            rhs = _const(node.right)
            if base is not None and isinstance(rhs, str):
                return base / rhs
            return None
        return None

    def resolve_read(self, node) -> str | None:
        """If node is `(<path>).read_text()` / `.read_bytes()`, return file text."""
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            return None
        if node.func.attr not in ("read_text", "read_bytes"):
            return None
        p = self.eval_path(node.func.value)
        if p is None or not p.exists():
            return None
        try:
            data = p.read_bytes()
            return data.decode("utf-8", "replace")
        except Exception:
            return None

    def resolve_file_arg(self, node) -> tuple[str, str] | None:
        """If node (optionally `str(...)`-wrapped) is a path expression this resolver can
        evaluate to a REAL, existing on-disk file (e.g. `RESOURCES / "intervals.bed"`, a
        real fixture shipped alongside the test, NOT a write_text-staged scratch file --
        that case is _track_files/_file_arg's job), return (basename, content) so the
        oracle can stage it exactly like any other file argument.

        Found via bedtools2/gomplate/run's remaining skips after fix 15+16: `run_x(["-i",
        str(RESOURCES / "intervals.bed"), ...])` -- the path is a REAL shipped input file,
        not a tracked local variable, so the existing files_map-only _file_arg had no way
        to see it. Reading real disk content (not guessing) keeps the same 'never
        confidently wrong' guarantee _file_arg already provides for the write_text case."""
        target = node
        if (
            isinstance(target, ast.Call)
            and isinstance(target.func, ast.Name)
            and target.func.id == "str"
            and len(target.args) == 1
        ):
            target = target.args[0]
        p = self.eval_path(target)
        if p is None or not p.is_file():
            return None
        try:
            data = p.read_bytes()
        except OSError:
            return None
        return p.name, data.decode("utf-8", "replace")


# --- per-test extraction ----------------------------------------------------

# pipe/consumer commands whose arg-lists must NOT be mistaken for the reimpl's
# argv (e.g. subprocess to `head -n 5` in a broken-pipe test).
_CONSUMER_CMDS = {
    "head",
    "tail",
    "grep",
    "cat",
    "sort",
    "wc",
    "sed",
    "awk",
    "tr",
    "less",
    "more",
    "tee",
    "xxd",
    "od",
    "cut",
    "uniq",
}


def _track_files(
    func: ast.FunctionDef, vmap: dict | None = None, content_fixtures: dict | None = None
) -> dict:
    """Map file-arg variables to (basename, content), following the common pattern
    `p = tmp_path / "in.tex"; p.write_text(content)` then `run(..., str(p))`.
    Resolves a content VARIABLE via vmap (content="..."; p.write_text(content)).
    Without this the reference observation runs against a MISSING file (wrong oracle).

    `content_fixtures` (2026-07-17, from _discover_content_to_file_fixtures) covers a
    DIFFERENT fixture-helper shape than the existing `tf = temp_files.create("test.tex",
    content)` case just below: quickjs's `script = temp_js_file(some_js_source)` --
    content comes FIRST (no name at all, using the fixture's own default) or as a second
    positional/keyword arg, resolved against the fixture's discovered default basename
    rather than a literal at the call site."""
    vmap = vmap or {}
    content_fixtures = content_fixtures or {}
    names: dict[str, str] = {}
    files: dict[str, tuple] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            v = node.targets[0].id
            val = node.value
            if isinstance(val, ast.BinOp) and isinstance(val.op, ast.Div):
                c = _const(val.right)
                if isinstance(c, str):
                    # (fix 42, 2026-07-17) if the LHS is itself a previously-resolved
                    # chained path (e.g. `year_dir`, already in vmap via
                    # _track_temp_files_path_vars as "logs/y2026") the real on-disk
                    # location is that PREFIX + this segment, not just this segment's
                    # own basename -- caps-log's `log_file = year_dir / "d2026_03_25.md"`
                    # then `log_file.write_text(...)`. Falls back to the plain basename
                    # (the tmp_path/tmpdir scratch-root case, where the base is never in
                    # vmap) when the LHS isn't a known chained var.
                    base = vmap.get(val.left.id) if isinstance(val.left, ast.Name) else None
                    if isinstance(base, str):
                        names[v] = c if base == "." else f"{base}/{c}"
                    else:
                        names[v] = c.rsplit("/", 1)[-1]
            elif (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr
                in ("create", "write_file", "make_file", "add_file", "make", "add")
                and len(val.args) >= 2
            ):
                # `tf = temp_files.create("test.tex", content)` fixture helper -> file+content
                nm = _const(val.args[0])
                ct = _resolve(val.args[1], vmap)
                content = (
                    ct.decode("utf-8", "replace")
                    if isinstance(ct, bytes)
                    else (ct if isinstance(ct, str) else None)
                )
                if isinstance(nm, str) and content is not None:
                    files[v] = (nm.rsplit("/", 1)[-1], content)
            elif (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Name)
                and val.func.id in content_fixtures
                and val.args
            ):
                # `script = temp_js_file(js_source)` / `temp_js_file(js_source, "x.js")` --
                # content-first fixture-factory call; name is whatever the call passes
                # (positional 2nd arg or name= keyword) or the fixture's own default.
                ct = _resolve(val.args[0], vmap)
                content = (
                    ct.decode("utf-8", "replace")
                    if isinstance(ct, bytes)
                    else (ct if isinstance(ct, str) else None)
                )
                nm = None
                if len(val.args) >= 2:
                    nm = _const(val.args[1])
                else:
                    for kw in val.keywords:
                        if kw.arg == "name":
                            nm = _const(kw.value)
                if not isinstance(nm, str):
                    nm = content_fixtures[val.func.id]
                if content is not None:
                    files[v] = (nm.rsplit("/", 1)[-1], content)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("write_bytes", "write_text")
            and isinstance(node.func.value, ast.Name)
            and node.args
        ):
            v = node.func.value.id
            c = _resolve(node.args[0], vmap)
            content = (
                c.decode("utf-8", "replace")
                if isinstance(c, bytes)
                else (c if isinstance(c, str) else None)
            )
            if content is not None and v in names:
                files[v] = (names[v], content)
    return files


def _file_arg(a, files_map: dict, resolver=None, temp_files_names: set | None = None):
    """If arg node `a` is `str(v)` / `v` / an f-string wrapping EXACTLY one tracked file
    var (`f'@{v}'`) for a tracked file var, return (arg_text, basename, content) -- the
    text to place in argv, the real on-disk filename to stage, and its content. For the
    plain cases arg_text == basename; for the f-string case they differ (e.g. arg_text
    '@binary_test.txt', basename 'binary_test.txt') so a 3-tuple is needed where a
    2-tuple (basename doubling as arg_text) used to suffice.

    Found sampling xh's test_data_binary_from_file: `test_file = RESOURCES /
    'binary_test.txt'; test_file.write_text('binary content\\n'); run([..., f'@{test_file}'])`
    -- _track_files already resolves the write_text-staged content (files_map has it), but
    the ONLY existing call shapes here were `str(v)`/bare `v`; an f-string reference was
    invisible, so the file never got staged even though its content was already known.
    Routing through _file_arg (not the generic _resolve() f-string branch) keeps file
    staging and argv text in sync -- resolving the text alone without staging the file
    would produce a confidently WRONG example (the oracle would run the real CLI against
    a file that doesn't exist), which is worse than not extracting it at all.

    `resolver` (a _PathResolver) covers a REAL shipped input file referenced directly by
    path expression -- `str(RESOURCES / "intervals.bed")` -- with no local write_text
    staging at all, found via bedtools2's whole test_annotate_* family. Tried only after
    the tracked-var lookup fails, and only for exactly `str(<path-expr>)` or a bare
    BinOp/Attribute path expression (never a bare ast.Name -- that's the tracked-var case
    above, already handled)."""
    # TEMP-FILES OBJECT .path() CALL (2026-07-17): `str(temp_files.path())` /
    # `str(temp_files.path("name"))`, INCLUDING a further `/ "literal"` division
    # chained onto a no-arg call (caps-log's whole test suite, 635 occurrences:
    # `tf.path() / "logs"`) -- `temp_files` a fixture yielding a custom object
    # wrapping a real tempfile.mkdtemp() scratch dir (dust/caps-log/samtools/htop/
    # gdal all share this class shape). No name/division given resolves to "." --
    # the scratch root itself, semantically identical to every other tmp_path-
    # relative basename already relativizing cleanly to determinex_local_oracle's
    # fresh per-call rundir; a name (or division chain) resolves to that literal
    # path (matching wherever a sibling .create(name, ...) staged real content
    # under the same name).
    if temp_files_names:
        resolved = _resolve_temp_files_path_chain(a, temp_files_names)
        if resolved is not None:
            hit = files_map.get(resolved)
            content = hit[1] if hit is not None else ""
            return resolved, resolved, content
    target = None
    if (
        isinstance(a, ast.Call)
        and isinstance(a.func, ast.Name)
        and a.func.id == "str"
        and len(a.args) == 1
        and isinstance(a.args[0], ast.Name)
    ):
        target = a.args[0].id
    elif isinstance(a, ast.Name):
        target = a.id
    if target:
        # A fixture returning a REAL file path (e.g. sox's `monkey_wav`) is resolved
        # eagerly in extract_file and merged straight into files_map before this
        # function ever runs -- see fixture_file_contents there -- so the plain
        # files_map.get(target) lookup above already covers it, no separate check needed.
        hit = files_map.get(target)
        if hit is not None:
            basename, content = hit
            return basename, basename, content
        return None
    # INLINE SCRATCH/OUTPUT PATH (2026-07-17): `str(tmp_path / "angle_dist.xvg")` used
    # DIRECTLY as a positional arg -- an OUTPUT path the tool under test creates itself,
    # never a real input needing content. _track_scratch_path_fixtures already covers this
    # exact reasoning for a SEPARATE fixture that returns such a path; found via gromacs's
    # whole `run_gmx(..., "-od", str(tmp_path / "x.xvg"), ...)` family that this same
    # BinOp(Div) shape can appear INLINE at the call site instead. Since
    # determinex_local_oracle.py's _run_reimpl already runs every Example in a fresh
    # per-call uuid rundir, a bare relative basename lands in a fresh, empty location
    # with zero oracle-side changes -- nothing to stage, just resolve arg_text to the
    # literal basename. Scoped to the identical tmp_path/tmpdir base convention (never a
    # real, fixed content path like RESOURCES, which resolver.resolve_file_arg already
    # covers above -- checked first since RESOURCES paths need their real content staged).
    scratch_check = a
    if (
        isinstance(scratch_check, ast.Call)
        and isinstance(scratch_check.func, ast.Name)
        and scratch_check.func.id == "str"
        and len(scratch_check.args) == 1
    ):
        scratch_check = scratch_check.args[0]
    if (
        isinstance(scratch_check, ast.BinOp)
        and isinstance(scratch_check.op, ast.Div)
        and isinstance(scratch_check.left, ast.Name)
        and scratch_check.left.id in ("tmp_path", "tmpdir")
    ):
        rhs = _const(scratch_check.right)
        if isinstance(rhs, str):
            return rhs, rhs, ""
    if resolver is not None and isinstance(a, (ast.Call, ast.BinOp, ast.Attribute)):
        hit = resolver.resolve_file_arg(a)
        if hit is not None:
            basename, content = hit
            return basename, basename, content
    if isinstance(a, ast.JoinedStr):
        file_names: list[str] = []
        for v in a.values:
            if (
                isinstance(v, ast.FormattedValue)
                and isinstance(v.value, ast.Name)
                and v.value.id in files_map
            ):
                file_names.append(v.value.id)
        if len(file_names) != 1:
            return None
        var_name = file_names[0]
        basename, content = files_map[var_name]
        text_parts = []
        for v in a.values:
            if isinstance(v, ast.Constant):
                text_parts.append(str(v.value))
            elif (
                isinstance(v, ast.FormattedValue)
                and isinstance(v.value, ast.Name)
                and v.value.id == var_name
            ):
                text_parts.append(basename)
            else:
                return None  # some other, unresolvable interpolation -- never guess
        return "".join(text_parts), basename, content
    return None


def _track_vars(func: ast.FunctionDef | ast.Module) -> dict:
    """Map local variables assigned a constant (str/bytes/int) so `stdin=input_tex`
    where `input_tex = "..."` resolves -- a VERY common pattern that otherwise leaves
    stdin uncaptured (the reference then runs with no input -> wrong oracle target).
    Also accepts a whole Module (not just a FunctionDef) to resolve MODULE-LEVEL
    constants like `EXECUTABLE = "../executable"` referenced directly in a bare
    subprocess.run([EXECUTABLE, ...]) call -- ast.walk works identically over either
    root, so this is reused rather than writing a second constant-tracking pass."""
    vmap: dict = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            c = _const(node.value)
            if isinstance(c, (str, bytes, int, float, list)) and not isinstance(c, bool):
                vmap[node.targets[0].id] = c
    return vmap


def _track_local_fstring_vars(func: ast.FunctionDef, vars_map: dict) -> dict:
    """A second pass over local assignments, for f-strings _track_vars's constant-only
    _const() can't touch: `filename = f"test.{extension}"` where `extension` is a
    @pytest.mark.parametrize value, not a literal. Found sampling codesnap's
    test_output_supported_formats(self, extension): the f-string result then feeds
    `run_command(["-o", filename, ...])` -- argv resolution fails not because of the
    parametrize value itself (fix 8 already handles that), but because it's one indirection
    further away, behind a LOCAL VARIABLE assignment _track_vars never looks inside for
    JoinedStr. Reuses _resolve_fstring_with_vars (already used for f-strings written
    directly in an assertion) against the CALLER's vars_map, which by the time this runs
    already includes the current parametrize case's substitution -- so `extension` is
    available for the lookup. Returns only the additional bindings, never overwrites an
    existing one, and never guesses past what _resolve_fstring_with_vars itself resolves."""
    out: dict = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.JoinedStr)
        ):
            name = node.targets[0].id
            if name in vars_map or name in out:
                continue
            resolved = _resolve_fstring_with_vars(node.value, vars_map)
            if resolved is not None:
                out[name] = resolved
    return out


def _fixture_return_const(node: ast.FunctionDef, module_path_exprs: dict | None = None):
    """A @pytest.fixture body's returned/yielded constant (resolving its own locals)."""
    local = _track_vars(node)
    module_path_exprs = module_path_exprs or {}
    local_path_exprs: dict[str, ast.AST] = {}
    for stmt in ast.walk(node):
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            local_path_exprs[stmt.targets[0].id] = stmt.value

    def is_exec_ref(val) -> bool:
        # EXECUTABLE-PATH FIXTURE (2026-07-17): `def binary_path(): return
        # Path(__file__).parent.parent.parent / "executable"` (or a one-indirection-away
        # `return EXECUTABLE` naming a local/module-level path expr) -- yj/cheat/lua's
        # whole skip-rate problem (92-99% skip corpus-wide) traces to this exact shape:
        # the executable is exposed through a FIXTURE, either used directly as a bare argv
        # list element (lua's `run_lua([lua_exec, "-e", ...])`) or passed BY NAME as a
        # wrapper's first param (cheat's `run_cheat(binary_path, args)`). A Path expression
        # isn't a _const()-resolvable literal, so this fixture was completely invisible
        # before -- resolves to the SAME 'executable' placeholder string
        # _is_executable_path_expr's other call sites already use (the oracle's own
        # _drop_binary_placeholder convention), so it flows through every existing
        # consumer of the `fixtures` dict (argv resolution, wrapper base-argv discovery)
        # with zero further plumbing.
        if _is_executable_path_expr(val):
            return True
        inner = val
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "str"
            and len(inner.args) == 1
        ):
            inner = inner.args[0]
        if isinstance(inner, ast.Name):
            if inner.id in local_path_exprs:
                return _is_executable_path_expr(local_path_exprs[inner.id])
            if inner.id in module_path_exprs:
                return _is_executable_path_expr(module_path_exprs[inner.id])
        return False

    for n in reversed(list(ast.walk(node))):
        val = None
        if isinstance(n, ast.Return) and n.value is not None:
            val = n.value
        elif (
            isinstance(n, ast.Expr) and isinstance(n.value, ast.Yield) and n.value.value is not None
        ):
            val = n.value.value
        if val is not None:
            c = _const(val)
            if c is _UNK and isinstance(val, ast.Name) and val.id in local:
                c = local[val.id]
            if isinstance(c, (str, bytes, int, float, list)) and not isinstance(c, bool):
                return c
            if is_exec_ref(val):
                return "executable"
    # CANDIDATE-PROBE LOOP (2026-07-17): `def yj_binary(): candidates = [
    # Path("../executable"), Path("./executable"), Path(__file__).parent... /
    # "executable"]; for path in candidates: if path.resolve().exists(): return
    # path.resolve(); raise FileNotFoundError(...)` -- a filesystem PROBE at
    # fixture-resolution time (whichever candidate ACTUALLY exists on disk depends
    # on cwd, unknowable via pure AST analysis), found via yj's whole conftest.py
    # (12/299 examples, the worst-recovering tool sampled this session). But EVERY
    # candidate is executable-path-shaped (matches _is_executable_path_expr,
    # including its new Path("literal/executable") case above) -- regardless of
    # WHICH one the real filesystem picks, the semantic answer is always "the
    # executable placeholder", so the loop's existence-probing doesn't need to be
    # traced at all once every candidate agrees. Scoped to a for-loop whose iterable
    # is a List literal (or a local Name resolving to one) with an `if
    # ...exists(): return ...` inside it -- never guesses if any candidate isn't
    # executable-shaped or the loop body doesn't return.
    for n in ast.walk(node):
        if not isinstance(n, ast.For):
            continue
        candidates = n.iter
        if isinstance(candidates, ast.Name) and candidates.id in local_path_exprs:
            candidates = local_path_exprs[candidates.id]
        if not (isinstance(candidates, ast.List) and candidates.elts):
            continue
        if not all(_is_executable_path_expr(e) for e in candidates.elts):
            continue
        has_conditional_return = any(
            isinstance(stmt, ast.If) and any(isinstance(s, ast.Return) for s in ast.walk(stmt))
            for stmt in n.body
        )
        if has_conditional_return:
            return "executable"
    return None


def _track_fixtures(tree: ast.Module) -> dict:
    """Map @pytest.fixture functions that return a constant -> value, so test args
    that are fixtures (sample_tex, etc.) resolve. Fixtures hold most test data."""
    fx: dict = {}
    module_path_exprs = {
        stmt.targets[0].id: stmt.value
        for stmt in tree.body
        if isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        v = _fixture_return_const(node, module_path_exprs)
        if v is not None:
            fx[node.name] = v
    return fx


def _track_fixture_real_file_paths(tree: ast.Module) -> dict[str, ast.AST]:
    """Map a @pytest.fixture's name -> the raw path-expression AST it returns, for a REAL,
    fixed, shipped file (not the 'executable' placeholder -- _track_fixtures already
    covers that case, and not a constant _fixture_return_const's plain-value branch
    already handles): `def monkey_wav(): return Path(__file__).parent.parent.parent /
    'src' / 'monkey.wav'`, referenced elsewhere as `str(monkey_wav)`.

    Found via sox's whole test_cli_options.py: `run_sox('-r', 'invalid', str(monkey_wav),
    '/tmp/out.wav')` -- monkey_wav is a bare Name (a fixture, not a files_map-tracked
    write_text var, not a RESOURCES-style path expression written directly at the call
    site), so neither _file_arg's existing tracked-var check nor its resolver-based
    RESOURCES-path check could ever see it. Returns the unevaluated EXPRESSION (not the
    resolved path) because evaluating it needs a resolver anchored to the file the
    fixture itself is DEFINED in -- callers evaluate it via the test file's own resolver,
    which is safe here since a conftest-defined fixture and the test file importing it
    always share the same parent directory in this corpus's convention (so `Path(__file__)
    .parent` resolves identically either way)."""
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if not is_fx:
            continue
        for n in reversed(list(ast.walk(node))):
            val = None
            if isinstance(n, ast.Return) and n.value is not None:
                val = n.value
            elif (
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Yield)
                and n.value.value is not None
            ):
                val = n.value.value
            if val is None:
                continue
            # Only a genuine path-BUILDING expression (Path(...)/... chain) -- never a
            # bare Name/constant (those are _fixture_return_const's job) and never
            # something _is_executable_path_expr already claims (that fixture belongs in
            # the exec_param_names set instead, not here).
            if (
                isinstance(val, ast.BinOp)
                and isinstance(val.op, ast.Div)
                and not _is_executable_path_expr(val)
            ):
                out[node.name] = val
            break
    return out


def _track_module_level_path_exprs(tree: ast.Module) -> dict[str, ast.AST]:
    """Map a MODULE-LEVEL constant name -> the raw path-expression AST it's assigned,
    for a bare `NAME = Path(__file__)... / 'file'` constant (not behind a fixture --
    that's _track_fixture_real_file_paths's job) referenced directly at a call site as
    `str(NAME)`, e.g. sox's whole test_util_coverage.py: `MONKEY_WAV =
    Path(__file__).parent.parent.parent / 'src' / 'monkey.wav'` then `run_binary([...,
    str(MONKEY_WAV), ...])`.

    Distinct from the ubiquitous `RESOURCES = Path(...) / 'test_resources' / ...`
    convention: RESOURCES is always used as a BASE further divided at the call site
    (`str(RESOURCES / 'input.mp4')`), which the resolver's BinOp path-expression
    handling already covers -- MONKEY_WAV is instead the COMPLETE file reference,
    used bare. _file_arg's str(Name)/bare-Name branch only ever checks files_map and
    hard-returns None on a miss, never falling through to the resolver for a name
    that isn't a fixture -- this is invisible without a dedicated eager-resolution
    pass, the same reasoning fix 22 already applies to fixture-returned paths.

    Also unwraps a `str(...)`-WRAPPED assignment (2026-07-17, fix 38): gdal's whole
    conftest.py declares `BYTE_TIF = str(REPO_ROOT / "autotest/gcore/data/byte.tif")`
    -- str() applied at the ASSIGNMENT itself, not just at usage sites -- which the
    original bare-BinOp check missed entirely (`isinstance(node.value, ast.BinOp)`
    was False for a Call wrapping a BinOp)."""
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        val = node.value
        if (
            isinstance(val, ast.Call)
            and isinstance(val.func, ast.Name)
            and val.func.id == "str"
            and len(val.args) == 1
        ):
            val = val.args[0]
        if (
            isinstance(val, ast.BinOp)
            and isinstance(val.op, ast.Div)
            and not _is_executable_path_expr(val)
        ):
            out[node.targets[0].id] = val
    return out


def _track_resource_path_vars(func: ast.FunctionDef, resolver: _PathResolver) -> dict[str, tuple]:
    """Map a TEST-LOCAL variable assigned from a REAL, on-disk resolver-resolvable path
    expression (`input_file = RESOURCES / "simple_box.txt"`) -> (basename, content), for
    the case where the golden-file reference is one assignment removed from the call
    site rather than written inline. Found via ditaa's `run_ditaa` whole test suite (499
    call sites, ~90% of the tool's own tests): every call is `run_ditaa(input_file,
    output_file, ...)` where `input_file` was assigned on an earlier line, never
    `run_ditaa(str(RESOURCES / "simple_box.txt"), ...)` inline.

    A THIRD variant of the same underlying gap fixes 22/28 already closed for two other
    scopes: fix 22 covers a FIXTURE's return value, fix 28 covers a bare MODULE-level
    constant referenced complete (`MONKEY_WAV`) or as an inline further-divided base
    (`str(RESOURCES / 'x')`) -- this covers a plain local Assign inside the TEST body
    itself, resolved eagerly per-test (the resolver is already available there) rather
    than needing a new tool-wide eager pass. Only ever resolves to a REAL FILE THAT
    EXISTS ON DISK (via resolver.resolve_file_arg, the exact same method _file_arg
    already calls for the inline case) -- never guesses a path that doesn't exist."""
    out: dict[str, tuple] = {}
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        hit = resolver.resolve_file_arg(node.value)
        if hit is not None:
            out[node.targets[0].id] = hit
    return out


def _resolve(node, vmap: dict):
    """_const, but also resolve a bare Name via the local-var map, `str(Name)` wrapping
    such a Name, or an f-string used INLINE (e.g. `run_command([f"--{flag}", ...])`,
    `flag` a parametrize value) -- the same _resolve_fstring_with_vars used for
    local-var-assigned f-strings (_track_local_fstring_vars) and in-assertion f-strings
    (_resolve_in_snippet), just at a third AST position: directly as an argv list
    element.

    The `str(Name)` case (2026-07-17) was the dominant driver of ffmpeg's ~50% skip
    rate: `output = tmp_path / "out.mkv"` resolves fine into vmap via
    _track_local_scratch_vars, but the call site almost always wraps it --
    `run_ffmpeg(..., str(output), "-y")` (738 occurrences across 26 ffmpeg test files
    alone) -- and _const() has no vmap access to unwrap a Name inside str(), while
    _file_arg's own str(Name) branch only ever checks files_map and hard-returns None
    on a miss without falling through to vmap. Mirrors the bare-Name case exactly."""
    c = _const(node)
    if c is _UNK and isinstance(node, ast.Name) and node.id in vmap:
        return vmap[node.id]
    if (
        c is _UNK
        and isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in vmap
    ):
        return str(vmap[node.args[0].id])
    if c is _UNK and isinstance(node, ast.JoinedStr):
        f = _resolve_fstring_with_vars(node, vmap)
        if f is not None:
            return f
    return c


def _resolve_list(list_node, files_map: dict, vmap: dict, used_files: dict, resolver=None):
    """Resolve every element of an argv LIST literal: literals, vars, and
    str(file_var)/file_var (-> basename + stage file). Returns argv list or None
    if any element is unresolvable. Handles run(["--print", str(tex_file)])."""
    if not isinstance(list_node, ast.List):
        return None
    out = []
    for e in list_node.elts:
        fa = _file_arg(e, files_map, resolver)
        if fa is not None:
            arg_text, basename, content = fa
            out.append(arg_text)
            used_files[basename] = content
            continue
        c = _resolve(e, vmap)
        if isinstance(c, (str, int, float)) and not isinstance(c, bool):
            out.append(str(c))
        else:
            return None
    return out


def _resolve_list_concat(
    node, files_map: dict, vmap: dict, used_files: dict, resolver=None
) -> list | None:
    """Resolve a `[prefix...] + <continuation>` expression used INLINE as a call argument
    (not behind an assignment -- that's fix 15's _extract_wrapper_base_argv job). Found
    via lua's `run_lua_cmd` fixture: `return run_lua([lua_exec] + args, stdin=stdin,
    env=env)` -- the concatenation is the argument expression itself, never bound to a
    local var first. `lua_exec` is a fixture resolving to 'executable' (see
    _fixture_return_const's executable-fixture case), reachable here via vmap the same
    way any other fixture-bound Name already is. Recurses on the left side so a chain of
    concatenations (`[a] + [b] + args`) resolves too. Returns None (never guesses) the
    moment either side fails."""
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
        return None
    if isinstance(node.left, ast.List):
        left = _resolve_list(node.left, files_map, vmap, used_files, resolver)
    else:
        left = _resolve_list_concat(node.left, files_map, vmap, used_files, resolver)
        if left is None:
            fa = _file_arg(node.left, files_map, resolver)
            if fa is not None:
                arg_text, basename, content = fa
                used_files[basename] = content
                left = [arg_text]
            else:
                c = _resolve(node.left, vmap)
                if isinstance(c, list):
                    left = _argv_strs(c)
                elif isinstance(c, (str, int, float)) and not isinstance(c, bool):
                    left = [str(c)]
    if left is None:
        return None
    right_node = node.right
    if (
        isinstance(right_node, ast.Call)
        and isinstance(right_node.func, ast.Name)
        and right_node.func.id == "list"
        and len(right_node.args) == 1
    ):
        right_node = right_node.args[0]
    right_val = _resolve(right_node, vmap) if isinstance(right_node, ast.Name) else None
    right = _argv_strs(right_val) if isinstance(right_val, list) else None
    if right is None:
        return None
    return left + right


def _find_run_call(
    func: ast.FunctionDef,
    files_map: dict | None = None,
    vars_map: dict | None = None,
    extra_run_names: set | None = None,
    kwarg_flags: dict | None = None,
    resolver=None,
    temp_files_names: set | None = None,
):
    """Return (argv, stdin, env, files) for the run-helper call. Prefer calls whose
    func name is a known runner (RUN_NAMES, or per-file auto-discovered via
    _discover_wrapper_names); never treat a pipe-consumer command's arg list
    (head/grep/...) as the reimpl argv."""
    files_map = files_map or {}
    vars_map = vars_map or {}
    kwarg_flags = kwarg_flags or {}
    temp_files_names = temp_files_names or set()
    run_names = RUN_NAMES | (extra_run_names or set())
    # rank: named runner first, bare-list candidate last
    named = []
    other = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            fn = node.func
            nm = (
                fn.id
                if isinstance(fn, ast.Name)
                else (fn.attr if isinstance(fn, ast.Attribute) else "")
            )
            (named if nm in run_names else other).append((nm, node))
    for name, node in named + other:
        looks_run = name in run_names or any(
            isinstance(k, ast.keyword) and k.arg in (STDIN_KW | ARGS_KW) for k in node.keywords
        )
        if not looks_run:
            continue
        argv = None
        stdin = None
        env = {}
        used_files: dict = {}
        # a wrapper with a LEARNED calling convention (_discover_wrapper_kwarg_flags found
        # its own `cmd = [base...]` + per-keyword `.extend()` pattern, e.g. duckdb's
        # run_duckdb) builds argv by APPENDING each recognized keyword's contribution to
        # its own fixed base -- never by one keyword wholesale REPLACING the whole argv.
        # Without this distinction, `run_duckdb(args=["--csv"], sql="...")` silently lost
        # both the base (["executable", "test.db"]) and the sql-derived ["-c", ...] the
        # moment the generic ARGS_KW branch below did `argv = [...]`, because that branch
        # was designed for the FUNDAMENTALLY DIFFERENT `run(args=[...])` shape where args
        # IS the entire invocation -- a real, confidently-wrong-example bug caught by hand
        # -checking output, not by the aggregate recovery count alone. Computed BEFORE the
        # positional-args loop below (not after) because a POSITIONAL list argument (e.g.
        # bedtools2's `run_bedtools(["annotate", ...])`, a required-positional `args` param
        # with no default) resolves and short-circuits the loop before base could ever be
        # consulted otherwise -- the exact same silent-base-loss bug as args=, just via the
        # positional path instead of the keyword path.
        this_wrapper = kwarg_flags.get(name)
        is_learned_wrapper = this_wrapper is not None
        this_kwarg_flags = (this_wrapper or {}).get("flags", {})
        this_base = (this_wrapper or {}).get("base", [])
        this_suffix = (this_wrapper or {}).get("suffix", [])
        # positional argv: first positional that is a list, else collect strs
        pos_strs = []
        # a positional List literal that FAILS to resolve (e.g. `run_x([..., str(RESOURCES
        # / "simple.sh")])` where the file-path element isn't a _file_arg-recognized shape)
        # must abort this candidate entirely, never silently fall through to a base-only
        # argv -- found via esubaalew__run's test_file_execution_simple: without this guard
        # the real `["--lang", "bash", "--file", ...]` list failed to resolve, then the
        # this_base fallback below silently produced argv=['executable'] (missing every
        # real argument) instead of leaving the test correctly unresolved. Confidently
        # wrong is worse than skipped.
        unresolvable_list_seen = False
        for a in node.args:
            if isinstance(a, ast.List):  # argv given as a list literal
                lst = _resolve_list(a, files_map, vars_map, used_files, resolver)
                if lst is not None:
                    # any positional args BEFORE this list literal (e.g. cheat's
                    # `run_cheat(binary_path, ["-h"])` -- binary_path resolves to
                    # 'executable' via a fixture, THEN a list literal follows) must be
                    # PREPENDED, never silently dropped just because a list showed up
                    # later in the call's positional args -- found via cheat's whole test
                    # suite, a real bug distinct from is_learned_wrapper's base handling.
                    argv = pos_strs + ((this_base + lst) if is_learned_wrapper else lst)
                    break
                unresolvable_list_seen = True
                continue
            if isinstance(a, ast.BinOp) and isinstance(a.op, ast.Add):
                # `run_lua([lua_exec] + args, ...)` -- lua's run_lua_cmd fixture-factory
                # builds the concatenation INLINE as the call argument itself, never
                # behind an assignment (that's fix 15's _extract_wrapper_base_argv job).
                # lua_exec resolves via the executable-fixture mechanism (_fixture_return_
                # const), reachable here through vars_map like any other fixture-bound Name.
                lst = _resolve_list_concat(a, files_map, vars_map, used_files, resolver)
                if lst is not None:
                    argv = pos_strs + lst
                    break
                unresolvable_list_seen = True
                continue
            fa = _file_arg(a, files_map, resolver, temp_files_names)
            if fa is not None:  # file-arg: pass arg text + stage content
                arg_text, basename, content = fa
                # "." (temp_files.path() with no name -- the scratch root ITSELF,
                # not a real file) must never be staged: the fresh per-call rundir
                # already IS "." by definition, and writing an empty file literally
                # named "." would try to write to a directory, not create anything.
                if basename != ".":
                    used_files[basename] = content
                pos_strs.append(arg_text)
                continue
            c = _resolve(a, vars_map)
            if isinstance(c, list):
                strs = _argv_strs(c)
                if strs is not None:
                    argv = pos_strs + ((this_base + strs) if is_learned_wrapper else strs)
                    break
                unresolvable_list_seen = True
                continue
            elif isinstance(c, (str, int, float)) and not isinstance(c, bool):
                pos_strs.append(str(c))
            else:
                # A positional arg WAS given but couldn't be resolved at all (e.g. a bare
                # Name built via runtime control flow: `args = [...]; if cond:
                # args.extend([...]); run_command(args)`). Must abort this candidate the
                # same way an unresolvable List/BinOp does -- NOT silently fall through to
                # the this_base-only fallback below, which can't distinguish "no
                # positional arg was given at all" from "one was given but unresolvable"
                # without this flag. Found via a real regression: once run_command
                # gained a learned base (["./executable"]), a genuinely-unresolvable
                # control-flow-built argv started resolving to argv=['./executable'] --
                # confidently wrong, silently missing every real argument -- instead of
                # staying correctly skipped.
                unresolvable_list_seen = True
        if unresolvable_list_seen and argv is None:
            continue
        if argv is None and pos_strs:
            # this_suffix (2026-07-17): tokens the wrapper appends AFTER its own
            # positional-parameter slot (ditaa's `output_file`/'--svg' following
            # `input_file` in run_ditaa_svg) -- see _extract_wrapper_base_argv's
            # extract_suffix for the full reasoning.
            argv = (
                (this_base + pos_strs + this_suffix) if is_learned_wrapper else pos_strs
            )  # run(*args) style
        if argv is None and not pos_strs and this_base:
            pos_strs = list(this_base)
        for k in node.keywords:
            if is_learned_wrapper and k.arg in ARGS_KW:
                # NOTE (2026-07-17): argv may ALREADY be finalized from pos_strs by the
                # "run(*args) style" block above (this_base + pos_strs, a real POSITIONAL
                # arg was also given at the call site) -- appending to pos_strs alone
                # afterward would be silently discarded since argv is a separate list by
                # then. Mirror the append into argv too when that's happened, found via
                # the exact same bug class as the this_kwarg_flags passthrough below.
                v = _resolve(k.value, vars_map)
                if isinstance(v, list) and all(
                    isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in v
                ):
                    extra = [str(x) for x in v]
                    pos_strs.extend(extra)
                    if argv is not None:
                        argv.extend(extra)
            elif k.arg in ARGS_KW:
                if isinstance(k.value, ast.List):
                    lst = _resolve_list(k.value, files_map, vars_map, used_files, resolver)
                    argv = lst if lst is not None else _argv_strs(_resolve(k.value, vars_map))
                else:
                    argv = _argv_strs(_resolve(k.value, vars_map))
            elif k.arg in STDIN_KW:
                v = _resolve(k.value, vars_map)
                if isinstance(v, bytes):
                    stdin = v.decode("utf-8", "replace")
                elif isinstance(v, str):
                    stdin = v
            elif k.arg == "env":
                v = _const(k.value)
                if isinstance(k.value, ast.Dict):
                    d = {}
                    for kk, vv in zip(k.value.keys, k.value.values):
                        ck, cv = _const(kk), _const(vv)
                        if isinstance(ck, str) and isinstance(cv, (str, int)):
                            d[ck] = str(cv)
                    env = d
            elif k.arg in this_kwarg_flags:
                # a wrapper-learned keyword (e.g. duckdb's sql= -> ["-c", sql]) --
                # _discover_wrapper_kwarg_flags read this mapping from the runner's own
                # `if <kwname>: cmd.extend([<flag>, <kwname>])` body, so it's appended
                # to the base argv exactly like the wrapper itself does, never replacing it.
                # Mirrored into argv directly too (2026-07-17, ditaa) -- argv may already
                # be finalized from pos_strs (a real positional arg was ALSO given, e.g.
                # ditaa's `run_ditaa(input_file, output_file, extra_args=[...])`), in which
                # case pos_strs and argv are two separate list objects by this point and an
                # append to pos_strs alone would be silently lost.
                v = _resolve(k.value, vars_map)
                if this_kwarg_flags[k.arg] == _KWARG_PASSTHROUGH:
                    # ditaa's extra_args=[...] -- the kwarg's own list value is spliced
                    # in verbatim (`cmd.extend(extra_args)`), no fixed flag prefix.
                    strs = _argv_strs(v) if isinstance(v, list) else None
                    if strs is not None:
                        pos_strs.extend(strs)
                        if argv is not None:
                            argv.extend(strs)
                elif this_kwarg_flags[k.arg] == _KWARG_APPEND_PASSTHROUGH:
                    # yj's flags="-h" -- the kwarg's own SINGLE value appended
                    # directly (`cmd.append(flags)`), no fixed flag prefix and no
                    # list to splice (distinct from _KWARG_PASSTHROUGH above). The
                    # real wrapper only appends when `flags` is truthy (`if
                    # flags:`) -- an explicit flags="" call must match that and
                    # append nothing, not a spurious empty-string argv token.
                    if v and isinstance(v, (str, int, float)) and not isinstance(v, bool):
                        extra = [str(v)]
                        pos_strs.extend(extra)
                        if argv is not None:
                            argv.extend(extra)
                elif isinstance(v, (str, int, float)) and not isinstance(v, bool):
                    extra = [this_kwarg_flags[k.arg], str(v)]
                    pos_strs.extend(extra)
                    if argv is not None:
                        argv.extend(extra)
        if argv is None and pos_strs:
            argv = pos_strs
        # never mistake a pipe-consumer command (head/grep/...) for the argv
        if argv and argv[0] in _CONSUMER_CMDS:
            continue
        if argv is not None:
            return argv, stdin, env, used_files
    return None, None, {}, {}


def _resolve_in_snippet(compare: ast.Compare, vars_map: dict, loop_vars: dict) -> tuple:
    """Resolve a single `snippet in stream` OR `snippet not in stream`-shaped Compare to
    (resolved_strings, is_ci). Shared by the plain top-level In/NotIn branches and the
    BoolOp(Or)/BoolOp(And) handling so the resolution logic (const, for-loop literal
    expansion, f-string-with-variable) lives in exactly one place instead of being
    duplicated. The In-vs-NotIn distinction only matters to the CALLER (which list it
    appends the result to) -- the snippet-resolution logic itself is identical either way.
    Returns ([], False) if unresolvable -- never guesses."""
    if len(compare.ops) != 1 or not isinstance(compare.ops[0], (ast.In, ast.NotIn)):
        return [], False
    left, right = compare.left, compare.comparators[0]
    ci = _is_lower_call(right)
    snip = _const(left)
    if snip is _UNK and isinstance(left, ast.Name) and left.id in loop_vars:
        out = []
        for item in loop_vars[left.id]:
            if isinstance(item, bytes):
                out.append(item.decode("utf-8", "replace"))
            elif isinstance(item, str):
                out.append(item)
        return out, ci
    # a bare Name can also be a @pytest.mark.parametrize argument (`assert flag in out`) --
    # vars_map carries the per-case substitution the same way _find_run_call's argv
    # resolution already does; resolved here as a single concrete string, distinct from
    # loop_vars' list-of-alternatives shape above.
    if snip is _UNK and isinstance(left, ast.Name) and left.id in vars_map:
        v = vars_map[left.id]
        if isinstance(v, (str, bytes)):
            snip = v
    if snip is _UNK and isinstance(left, ast.JoinedStr):
        snip = _resolve_fstring_with_vars(left, vars_map)
    if isinstance(snip, bytes):
        return [snip.decode("utf-8", "replace")], ci
    if isinstance(snip, str):
        return [snip], ci
    return [], ci


def _find_expectations(
    func: ast.FunctionDef,
    resolver: _PathResolver,
    assertion_helpers: dict | None = None,
    wrapper_shapes: dict | None = None,
    extra_vars: dict | None = None,
):
    rc = None
    rc_nonzero = False
    rc_in: list = []
    exact = None
    contains = []
    not_in: list = []
    in_any: list = []
    ci = False
    assertion_helpers = assertion_helpers or {}
    # LOCAL-VARIABLE RESOLUTION (2026-07-16): _find_run_call has had this kind of local
    # binding-tracking for argv/stdin all along (_track_vars); _find_expectations never
    # shared any of it and only matched DIRECT attribute shapes (X.returncode, X.stdout).
    # Real test code introduces indirection three separate ways, each found by validating
    # against real solar/jq test source before trusting any of it: (1) tuple-unpacked
    # wrapper results (`code, out = run_exe(...)`), (2) decode-to-local-variable written
    # directly in a test body (not just inside an assertion helper -- that case was already
    # handled narrowly), (3) a for-loop iteration variable over a literal list used in an
    # `in` check (`for needle in [...]: assert needle in out`). result_roles/loop_vars give
    # _is_rc_expr/_is_out_expr/the In-branch below the same resolving power _find_run_call
    # already had, instead of adding another narrow one-off pattern.
    result_roles = _track_result_roles(func, wrapper_shapes or {})
    loop_vars = _track_loop_literal_lists(func)
    # F-STRING-WITH-VARIABLE (2026-07-16): sized before building, per this thread's own
    # discipline -- 96/627 (15.3%) of stgit's skips and 197/791 (24.9%) of lazygit's skips
    # match `assert f"stat {missing}" in out` where `missing` is a plain local variable, not
    # a literal. _const()'s existing JoinedStr handling only accepts LITERAL constant parts
    # (`f"a{1}b"` works, `f"a{x}b"` doesn't) -- it has no variable lookup at all. vars_map
    # (the same _track_vars local-constant-binding map _find_run_call already relies on)
    # lets a bare-Name interpolated part resolve if IT was itself bound to a constant.
    # PARAMETRIZE-AWARE (2026-07-16): extra_vars carries the current @pytest.mark.parametrize
    # case's substitution (e.g. {"flag": "-h"}) so `assert flag in out` resolves per-case,
    # the same way _find_run_call's argv resolution already does via vars_map.
    vars_map = {**_track_vars(func), **(extra_vars or {})}
    for node in ast.walk(func):
        # A custom assertion helper is USUALLY called as a bare statement (assert_err(proc,
        # 2, [...])) -- the helper does its own internal asserting and returns nothing
        # meaningful, so the call is an ast.Expr, not wrapped in an outer `assert` keyword.
        # Confirmed against real jq test source before trusting this shape.
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in assertion_helpers
        ):
            helper_rc, helper_contains = _resolve_assertion_helper_call(
                node.value, assertion_helpers[node.value.func.id]
            )
            if helper_rc is not None:
                rc = helper_rc
            contains.extend(helper_contains)
            continue
        if not isinstance(node, ast.Assert):
            continue
        t = node.test
        if isinstance(t, ast.Compare) and len(t.ops) == 1:
            op = t.ops[0]
            left, right = t.left, t.comparators[0]
            if isinstance(op, ast.Eq):
                # rc?  result.returncode == N  /  result.code == N  /  a tuple-unpacked
                # local variable bound to the rc position (see result_roles above)
                if _is_rc_expr(left, result_roles):
                    c = _const(right)
                    if isinstance(c, int):
                        rc = c
                elif _is_rc_expr(right, result_roles):
                    c = _const(left)
                    if isinstance(c, int):
                        rc = c
                else:
                    # exact stdout: result.stdout(.decode()) == golden/const, or a
                    # tuple-unpacked/decoded local variable bound to the stdout role. A
                    # `.strip()`-wrapped comparison is a WEAKER claim (tolerates surrounding
                    # whitespace) -- record it as `contains`, never `exact`, so the recorded
                    # expectation is never stricter than what the real test verifies.
                    is_out_l, stripped_l = _is_out_expr_maybe_stripped(left, result_roles)
                    is_out_r, stripped_r = _is_out_expr_maybe_stripped(right, result_roles)
                    if is_out_l:
                        val = _golden_or_const(right, resolver)
                        if stripped_l:
                            if isinstance(val, str) and val:
                                contains.append(val)
                        else:
                            exact = val
                    elif is_out_r:
                        val = _golden_or_const(left, resolver)
                        if stripped_r:
                            if isinstance(val, str) and val:
                                contains.append(val)
                        else:
                            exact = val
            elif isinstance(op, ast.In):
                # RC MEMBERSHIP (2026-07-17): `assert result.returncode in [0, 1]` -- found
                # via calcurse (72 occurrences of this exact top-level shape): "either
                # success or this specific known failure" is a real, common tolerance claim,
                # distinct from both expect_rc (exact) and expect_rc_nonzero (any nonzero).
                # Checked BEFORE the generic string-`in` path below, since `_resolve_in_snippet`
                # only ever resolves string snippets and would otherwise just silently produce
                # zero items for a list of ints, leaving the test skipped with the real
                # expectation invisible. Scoped to a List/Tuple of int constants only.
                if _is_rc_expr(left, result_roles):
                    vals = _const(right)
                    if isinstance(vals, list) and vals and all(isinstance(v, int) for v in vals):
                        rc_in = vals
                        continue
                items, snip_ci = _resolve_in_snippet(t, vars_map, loop_vars)
                if snip_ci:
                    ci = True
                contains.extend(items)
            elif isinstance(op, ast.NotIn):
                # `assert "unexpected argument" not in output.lower()` -- found via
                # codesnap-rs__codesnap (77/520 = 14.8% of its skips have this exact
                # top-level shape, precisely sized before building). A NEGATIVE claim: the
                # snippet must NOT appear anywhere. Semantically the mirror image of `in`,
                # not squeezable into expect_in (which means "must appear") -- needs its own
                # field, but unlike the OR-group case, this is always a simple universal
                # negation with no AND/OR ambiguity to design around.
                items, snip_ci = _resolve_in_snippet(t, vars_map, loop_vars)
                if snip_ci:
                    ci = True
                not_in.extend(items)
            elif isinstance(op, ast.NotEq):
                # `assert result.returncode != 0` -- a real "must fail" shape (found via
                # bedtools2's whole test_sortandnaming_* family: 15/15 of that file's
                # remaining skips share exactly this rc check). Scoped to literally `!= 0`
                # on either side -- the test never claims WHICH nonzero code, so anything
                # else (`!= 1`, `!= "some string"`) is left unresolved rather than guessed.
                other = (
                    right
                    if _is_rc_expr(left, result_roles)
                    else (left if _is_rc_expr(right, result_roles) else None)
                )
                if other is not None and _const(other) == 0:
                    rc_nonzero = True
        elif isinstance(t, ast.BoolOp):
            # `assert A or B` (real shape, found via ariga__atlas/stacked-git__stgit:
            # `b'squash' in out.lower() or b'patch' in out.lower()`) is an OR-semantics
            # claim -- at least one branch must hold -- which `contains`'s AND-semantics
            # can't safely represent (adding both would wrongly demand BOTH; a genuinely
            # correct reimplementation satisfying only ONE branch would then wrongly fail
            # an expectation the real test never imposed). `assert A and B` is exactly
            # equivalent to two separate asserts and flattens safely into `contains`.
            # Scoped deliberately to the shape actually observed: every branch must itself
            # be a simple `snippet in stream` Compare that resolves to EXACTLY one string
            # -- never guess a partial or mixed-shape group. Precisely sized before
            # building (172/627 = 27.4% of stgit's skips have this exact top-level shape).
            branch_items: list = []
            branch_ci = False
            all_resolved = True
            for value in t.values:
                if not (
                    isinstance(value, ast.Compare)
                    and len(value.ops) == 1
                    and isinstance(value.ops[0], ast.In)
                ):
                    all_resolved = False
                    break
                items, snip_ci = _resolve_in_snippet(value, vars_map, loop_vars)
                if len(items) != 1:
                    all_resolved = False
                    break
                branch_ci = branch_ci or snip_ci
                branch_items.append(items[0])
            if all_resolved and len(branch_items) >= 2:
                if branch_ci:
                    ci = True
                if isinstance(t.op, ast.And):
                    contains.extend(branch_items)
                elif isinstance(t.op, ast.Or):
                    in_any.append(branch_items)
        elif (
            isinstance(t, ast.Call)
            and isinstance(t.func, ast.Name)
            and t.func.id in assertion_helpers
        ):
            # a custom assertion helper: assert_err(proc, 2, ["Unknown option", ...]) --
            # resolve rc/contains from the CALL SITE's arguments using the helper's own
            # parameter-role mapping (see _analyze_assertion_helper).
            helper_rc, helper_contains = _resolve_assertion_helper_call(
                t, assertion_helpers[t.func.id]
            )
            if helper_rc is not None:
                rc = helper_rc
            contains.extend(helper_contains)
    return rc, exact, contains, ci, in_any, not_in, rc_nonzero, rc_in


# ---------------------------------------------------------------------------
# Custom assertion-helper resolution (2026-07-16)
# ---------------------------------------------------------------------------
# Same principle as wrapper-name auto-discovery, applied to the OTHER half of a test: many
# real suites factor repeated assertion shapes into a helper (`assert_err(proc, rc, subs)`)
# instead of inlining `assert proc.returncode == rc` + a loop of `assert s in proc.stderr`.
# _find_expectations only recognized inline ast.Compare assertions -- a call to such a helper
# is an ast.Call, invisible to it entirely. Fixed by statically analyzing the helper's OWN
# body once (which of its parameters plays the "expected rc" role, which plays the "list of
# required substrings" role), then, at each call site, resolving the actual arguments passed
# for those parameter positions the same way an inline assertion's constants are resolved.
def _stream_attr(node: ast.AST) -> str | None:
    """If `node` is `X.stderr`/`X.stdout`/`X.out`, or `X.stderr.decode(...)` etc., return the
    stream name ("stderr"/"stdout"/"out"); else None."""
    n = node
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "decode":
        n = n.func.value
    if isinstance(n, ast.Attribute) and n.attr in ("stderr", "stdout", "out"):
        return n.attr
    return None


def _analyze_assertion_helper(helper: ast.FunctionDef) -> dict:
    """Figure out which of `helper`'s parameters play the rc-comparison / substring-list
    roles, by finding the same comparison shapes _find_expectations recognizes inline,
    but INSIDE the helper's own body. Returns {} if the helper doesn't match this shape at
    all (e.g. it's an unrelated function that also happened to get scanned).

    Tracks one level of local-variable indirection (`err = proc.stderr.decode(...)` then
    `assert s in err`) -- confirmed necessary against a real corpus case (jq's assert_err
    decodes to a local `err` before looping; a direct-attribute-only check missed it
    entirely, a real bug caught by validating against real data before trusting this)."""
    params = [a.arg for a in helper.args.args]
    stream_vars: dict[str, str] = {}  # local var name -> "stderr"/"stdout"/"out"
    for node in ast.walk(helper):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            stream = _stream_attr(node.value)
            if stream:
                stream_vars[node.targets[0].id] = stream
    result: dict = {}
    for node in ast.walk(helper):
        if (
            isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
        ):
            left, right = node.test.left, node.test.comparators[0]
            if _is_result_rc(left) and isinstance(right, ast.Name) and right.id in params:
                result["rc_param"] = right.id
            elif _is_result_rc(right) and isinstance(left, ast.Name) and left.id in params:
                result["rc_param"] = left.id
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and isinstance(node.iter, ast.Name)
            and node.iter.id in params
        ):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Assert)
                    and isinstance(sub.test, ast.Compare)
                    and len(sub.test.ops) == 1
                    and isinstance(sub.test.ops[0], ast.In)
                ):
                    l, r = sub.test.left, sub.test.comparators[0]
                    if not (isinstance(l, ast.Name) and l.id == node.target.id):
                        continue
                    is_stream = _stream_attr(r) is not None or (
                        isinstance(r, ast.Name) and r.id in stream_vars
                    )
                    if is_stream:
                        result["contains_param"] = node.iter.id
    if result:
        result["_params"] = params
    return result


def _discover_assertion_helpers(tree: ast.Module, path: Path) -> dict:
    """Per-file/per-directory auto-discovered assertion-helper role mappings, mirroring
    _discover_wrapper_names's own-file + sibling-helper-module scan."""
    out: dict = {}

    def scan(t: ast.Module) -> None:
        for node in ast.walk(t):
            if isinstance(node, ast.FunctionDef):
                mapping = _analyze_assertion_helper(node)
                if mapping:
                    out[node.name] = mapping

    scan(tree)
    for helper_name in _HELPER_FILENAMES:
        hp = path.parent / helper_name
        if not hp.exists() or hp == path:
            continue
        try:
            scan(ast.parse(hp.read_text(encoding="utf-8", errors="replace")))
        except SyntaxError:
            continue
    return out


def _resolve_assertion_helper_call(call: ast.Call, mapping: dict) -> tuple:
    """Given a call site `assert_err(proc, 2, ["a", "b"])` and the helper's role mapping
    (which parameter position is the rc, which is the substring list), resolve the actual
    constant values passed at THIS call site for those roles."""
    rc = None
    contains: list = []
    # positional-only resolution: sufficient for every real case seen (helpers taking their
    # rc/substrings by keyword at the call site would need keyword matching too, but no
    # observed case in the corpus does this -- add keyword support if one turns up). Resolve
    # by scanning call.args positionally against the helper's own parameter list, captured
    # at analysis time in mapping["_params"] (see _analyze_assertion_helper).
    params = mapping.get("_params") or []
    for i, arg in enumerate(call.args):
        if i >= len(params):
            break
        pname = params[i]
        if pname == mapping.get("rc_param"):
            c = _const(arg)
            if isinstance(c, int):
                rc = c
        elif pname == mapping.get("contains_param"):
            c = _const(arg)
            if isinstance(c, list):
                for item in c:
                    if isinstance(item, bytes):
                        contains.append(item.decode("utf-8", "replace"))
                    elif isinstance(item, str):
                        contains.append(item)
    return rc, contains


# ---------------------------------------------------------------------------
# Shared local-variable resolution for _find_expectations (2026-07-16)
# ---------------------------------------------------------------------------
# _find_run_call has had local-binding resolution for argv/stdin all along (_track_vars).
# _find_expectations never shared any of it and only matched DIRECT attribute shapes.
# Found via a real solar test (`code, out = run_exe(...)`) that _find_run_call resolved
# fine (its args don't care how the return value gets used) but _find_expectations missed
# entirely, since `code`/`out` are bare Names, not `X.returncode`/`X.stdout` attributes.
def _analyze_run_wrapper_return_shape(wrapper: ast.FunctionDef) -> dict | None:
    """If `wrapper` returns a tuple (`return proc.returncode, proc.stdout`), figure out
    which position is the rc and which is the stdout/stderr stream, by inspecting what each
    tuple element actually IS. Returns None if the wrapper doesn't return a plain tuple
    literal (a single CompletedProcess-like object already goes through the direct
    attribute-access path -- this is only for the tuple-unpacking shape)."""
    shape: dict = {}
    for node in ast.walk(wrapper):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            for i, elt in enumerate(node.value.elts):
                if _is_result_rc(elt):
                    shape.setdefault("rc_pos", i)
                    continue
                stream = _stream_attr(elt)
                if stream == "stderr":
                    shape.setdefault("stderr_pos", i)
                elif stream in ("stdout", "out"):
                    shape.setdefault("stdout_pos", i)
    return shape or None


def _discover_wrapper_return_shapes(tree: ast.Module, path: Path) -> dict:
    """Per-file/per-directory: for every function that shells out (_shells_out, same
    detection _discover_wrapper_names uses), record its tuple return shape if it has one.

    CHAINED WRAPPERS (2026-07-17): a delegating wrapper (lua's `run_lua_cmd`, whose
    closure is just `return run_lua([lua_exec] + args, ...)`) never builds a tuple
    LITERAL itself -- it passes through whatever the wrapper it calls returns -- so the
    direct _analyze_run_wrapper_return_shape scan (which only recognizes `return a, b, c`
    tuple literals) never finds a shape for it, even after _discover_wrapper_names learns
    run_lua_cmd IS a run name. Without this, `code, out, err = run_lua_cmd(...)` in a test
    body has no rc/stdout/stderr role mapping and every assertion against out/err/code
    stays unresolved. Fixed the same way as the run-name discovery: a second, fixed-point
    pass where a function whose sole return is `return <call>(...)` to an ALREADY-shaped
    name inherits that exact shape (it's a pure passthrough, not a transformation)."""
    shapes: dict = {}
    candidates: list[ast.FunctionDef] = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    ]
    for helper_name in _HELPER_FILENAMES:
        hp = path.parent / helper_name
        if not hp.exists() or hp == path:
            continue
        try:
            htree = ast.parse(hp.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        candidates.extend(node for node in ast.walk(htree) if isinstance(node, ast.FunctionDef))

    for node in candidates:
        if _shells_out(node):
            shape = _analyze_run_wrapper_return_shape(node)
            if shape:
                shapes[node.name] = shape

    changed = True
    while changed:
        changed = False
        for node in candidates:
            if node.name in shapes:
                continue
            is_nested_closure = _shells_out_own_body(node)
            target = node if is_nested_closure else _find_returned_inner_closure(node)
            if target is None:
                target = node
            body = target.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            if len(body) != 1 or not isinstance(body[0], ast.Return):
                continue
            ret = body[0].value
            if (
                isinstance(ret, ast.Call)
                and isinstance(ret.func, ast.Name)
                and ret.func.id in shapes
            ):
                shapes[node.name] = shapes[ret.func.id]
                changed = True
    return shapes


def _track_result_roles(func: ast.FunctionDef, wrapper_shapes: dict) -> dict:
    """Map local variable names to the role they play ("rc" / "stdout" / "stderr"),
    covering the two indirection shapes found against real test source: (1) a tuple-unpack
    from a known wrapper call (`code, out = run_exe(...)`) resolved via that wrapper's
    return-shape mapping, and (2) a direct decode/attribute assignment written straight in
    the test body (`err = proc.stderr.decode(...)`) -- the same shape _analyze_assertion_
    helper already handled, but for helper bodies only; this generalizes it to any function."""
    roles: dict = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            if _is_result_rc(node.value):
                roles[target.id] = "rc"
                continue
            stream = _stream_attr(node.value)
            if stream:
                roles[target.id] = "stdout" if stream in ("stdout", "out") else stream
        elif (
            isinstance(target, ast.Tuple)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            shape = wrapper_shapes.get(node.value.func.id)
            if not shape:
                continue
            names = [e.id for e in target.elts if isinstance(e, ast.Name)]
            for i, name in enumerate(names):
                if shape.get("rc_pos") == i:
                    roles[name] = "rc"
                elif shape.get("stdout_pos") == i:
                    roles[name] = "stdout"
                elif shape.get("stderr_pos") == i:
                    roles[name] = "stderr"
    return roles


def _track_loop_literal_lists(func: ast.FunctionDef) -> dict:
    """Map a for-loop's iteration variable name to the literal list of values it iterates
    over (`for needle in ["a", "b"]:` -> {"needle": ["a", "b"]}), so an `assert needle in
    out` inside the loop body can be expanded to every literal the loop actually checks,
    instead of being silently unresolvable (needle is a bare Name, not itself a constant)."""
    out: dict = {}
    for node in ast.walk(func):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            c = _const(node.iter)
            if isinstance(c, list):
                out[node.target.id] = c
    return out


def _is_rc_expr(node: ast.AST, result_roles: dict) -> bool:
    return _is_result_rc(node) or (isinstance(node, ast.Name) and result_roles.get(node.id) == "rc")


def _is_out_expr(node: ast.AST, result_roles: dict) -> bool:
    return _is_result_out(node) or (
        isinstance(node, ast.Name) and result_roles.get(node.id) == "stdout"
    )


_STRIP_METHODS = {"strip", "rstrip", "lstrip"}


def _is_out_expr_maybe_stripped(node: ast.AST, result_roles: dict) -> tuple:
    """Same check as _is_out_expr, but also peels one `.strip()`/`.rstrip()`/`.lstrip()`
    call off first (`p.stdout.strip() == "expected"` -- found to be a real, sizeable pattern
    against real atlas test source: 158 skipped tests in one tool alone use this shape).
    Returns (is_out, was_stripped). was_stripped matters semantically, not just for whether
    a match is found: `X.strip() == "expected"` is a WEAKER claim than `X == "expected"` --
    the real test tolerates surrounding whitespace atlas's own reference binary produces, so
    recording it as an EXACT match would make the extracted expectation stricter than what
    the test actually verifies (a correct reimplementation that adds a trailing newline would
    then wrongly fail an expectation the real test never imposed). The caller routes a
    was_stripped=True match into `contains` instead of `exact` specifically to avoid this."""
    n = node
    if (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _STRIP_METHODS
    ):
        n = n.func.value
        return _is_out_expr(n, result_roles), True
    return _is_out_expr(n, result_roles), False


def _is_lower_call(node):
    """True if node is X.lower() / X.casefold() — marks a case-insensitive check."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("lower", "casefold")
    )


def _is_result_rc(node):
    return isinstance(node, ast.Attribute) and node.attr in RESULT_ATTRS


def _is_result_out(node):
    # result.stdout / result.out / result.stdout.decode()
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "decode"
    ):
        node = node.func.value
    return isinstance(node, ast.Attribute) and node.attr in ("stdout", "out")


def _golden_or_const(node, resolver: _PathResolver):
    g = resolver.resolve_read(node)
    if g is not None:
        return g
    c = _const(node)
    if isinstance(c, bytes):
        return c.decode("utf-8", "replace")
    if isinstance(c, str):
        return c
    return None


def _parametrize_cases(node: ast.FunctionDef) -> list[dict] | None:
    """`@pytest.mark.parametrize("name", [v1, v2, ...])` binds `name` to a different
    concrete value per collected test item -- pytest expands ONE FunctionDef into N
    real test items (e.g. test_batch_flag[-b] / test_batch_flag[--batch]), each with
    its own argv once the placeholder is substituted. Untreated, the bare `Name` node
    for the parametrize arg never resolves (`flag` in `run([flag, ...])`), so every
    parametrized case fell through as unresolvable-argv (major real skip source in
    the hwatch corpus: parametrized flag-variant suites). Returns a list of
    {argname: value} substitution dicts, or None if not parametrized / not a single
    simple string-name + constant-list shape (never guesses on multi-arg or
    non-constant parametrize -- falls back to the pre-existing skip behavior).
    """
    cases = None
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        fn = dec.func
        is_parametrize = isinstance(fn, ast.Attribute) and fn.attr == "parametrize"
        if not is_parametrize or len(dec.args) < 2:
            continue
        name_node, values_node = dec.args[0], dec.args[1]
        argname = _const(name_node)
        if not isinstance(argname, str) or "," in argname:
            continue  # single-name only -- no "a,b" multi-param shape
        if not isinstance(values_node, (ast.List, ast.Tuple)):
            continue
        values = []
        ok = True
        for elt in values_node.elts:
            v = _const(elt)
            if v is _UNK or isinstance(v, (list, dict)):
                ok = False
                break
            values.append(v)
        if not ok or not values:
            continue
        this_cases = [{argname: v} for v in values]
        # multiple parametrize decorators stack (cartesian product) in real pytest;
        # keep it simple and merge only when shapes agree, otherwise bail (no guess).
        if cases is None:
            cases = this_cases
        else:
            cases = [{**a, **b} for a in cases for b in this_cases]
    return cases


def _track_run_fixtures(
    tree: ast.Module, extra_run_names: set, kwarg_flags: dict | None = None, resolver=None
) -> dict:
    """Map @pytest.fixture functions that themselves INVOKE the executable (return a
    CompletedProcess-like result) -> (argv, stdin, env, files). A common idiom hoists an
    expensive/shared invocation (e.g. `--help`) into a session-scoped fixture so many
    assertions don't each re-run the executable:

        @pytest.fixture(scope="session")
        def help_long():
            return run_cmd(["--help"])

        def test_help_exit_code_zero(help_long):
            assert help_long.returncode == 0

    Found sampling lazygit's test_help_output.py: 45/47 tests in the file take such a
    fixture as their only run-related parameter, and NONE of them contain any run-call of
    their own -- _find_run_call(test_node, ...) walks the TEST's body, which has nothing
    to find. The expectation side needs no change at all: _is_result_rc/_is_result_out
    match on attribute name alone (`.returncode`/`.stdout`), not on how the base name was
    bound, so `help_long.returncode == 0` was ALREADY recognized as rc=0 -- argv
    resolution was the only blocker. Reuses _find_run_call itself (it doesn't care
    whether the FunctionDef it's given is a test or a fixture, only that it contains a
    qualifying Call) rather than writing a second call-finding routine."""
    fixture_nodes: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_fx = False
        for d in node.decorator_list:
            tgt = d.func if isinstance(d, ast.Call) else d
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "fixture") or (
                isinstance(tgt, ast.Name) and tgt.id == "fixture"
            ):
                is_fx = True
        if is_fx:
            fixture_nodes.append(node)

    fx: dict = {}
    for node in fixture_nodes:
        vars_map = _track_vars(node)
        files_map = _track_files(node, vars_map)
        argv, stdin, env, files = _find_run_call(
            node, files_map, vars_map, extra_run_names, kwarg_flags, resolver
        )
        if argv is not None:
            fx[node.name] = (argv, stdin, env, files)

    # CHAINED FIXTURES (2026-07-17): a second fixture can depend on a first and project
    # one field out of it instead of invoking anything itself --
    #     @pytest.fixture
    #     def help_result(): return run_cmd(["--help"])
    #     @pytest.fixture
    #     def help_text(help_result): return help_result.stdout
    # `help_text`'s own body has no run-call at all (_find_run_call finds nothing), so it
    # never entered `fx` above even though tests depend on IT, not help_result directly --
    # 82/87 tests in one real xh file were blocked on exactly this. Which specific field
    # is projected doesn't matter for OUR purposes (argv resolution) -- a test using
    # help_text still ran the SAME command as help_result. The expectation side already
    # doesn't care how the test's local name was bound (_is_result_rc/_is_result_out match
    # on attribute name alone), so registering help_text with the identical (argv, stdin,
    # env, files) tuple is correct: `assert flag in help_text` and `assert flag in
    # help_result.stdout` end up checking the exact same real captured output. Iterates to
    # a fixed point (bounded by fixture count) so a chain three-or-more deep also resolves,
    # never guesses past a body that is exactly `return <own-param>.<attr>`.
    changed = True
    while changed:
        changed = False
        for node in fixture_nodes:
            if node.name in fx:
                continue
            params = {a.arg for a in node.args.args}
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            if len(body) != 1 or not isinstance(body[0], ast.Return):
                continue
            ret = body[0].value
            if (
                isinstance(ret, ast.Attribute)
                and isinstance(ret.value, ast.Name)
                and ret.value.id in params
                and ret.value.id in fx
            ):
                fx[node.name] = fx[ret.value.id]
                changed = True
    return fx


def extract_file(path: Path) -> Coverage:
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return Coverage([], 0, 0, [])
    resolver = _PathResolver(path)
    # LEARN CONFTEST.PY FIRST, THEN THE TEST FILE ITSELF (2026-07-17, fix 39b --
    # caught by a real corpus-wide regression, not assumed): a test file can define
    # its OWN module-level constant with the SAME NAME as one in conftest.py --
    # ditaa's whole test_svg.py: `RESOURCES = Path(__file__).parent.parent /
    # "test_resources" / "test_svg"` (a test-file-SPECIFIC subdirectory), while
    # conftest.py separately defines `RESOURCES = WORKSPACE / "test-resources"` (a
    # different, generic path). Real Python scoping means the test file's own
    # module-level name is the ONLY one ever visible inside it -- conftest.py's
    # same-named global is a completely separate variable in a different module,
    # never merged as a bare name (only pytest FIXTURES are injected explicitly).
    # _PathResolver.learn() does a naive dict overwrite with no precedence logic at
    # all, so calling it on conftest.py AFTER the test file (fix 39's original
    # ordering) let conftest's WRONG value silently win, breaking resolution for
    # every test in the file referencing the collided name -- test_svg.py's own
    # 30/31 resolved examples (fix 30's real, tested, verified recovery) dropped to
    # 12/31 the moment fix 39 shipped. Caught by re-checking every previously-fixed
    # tool after a resolver change, not by trusting the new fix's own tests alone.
    conf = path.parent / "conftest.py"
    if conf.exists():
        try:
            resolver.learn(ast.parse(conf.read_text(encoding="utf-8", errors="replace")))
        except SyntaxError:
            pass
    resolver.learn(tree)
    # Fixtures (this file + sibling conftest.py) hold most test data; resolve them so
    # `run(stdin=sample_tex)` / `create("x.tex", sample_tex)` capture the real input.
    fixtures = _track_fixtures(tree)
    # MODULE-LEVEL CONSTANTS (2026-07-17): `EXECUTABLE = "../executable"` at module scope,
    # referenced directly in a bare `subprocess.run([EXECUTABLE, ...])` call with no
    # wrapper function or fixture at all (found via dirble's test_help_output/
    # test_version_output/test_no_arguments_error/test_invalid_url -- the whole tool has
    # NO conftest.py). _track_vars already resolves constant-valued Name assignments via a
    # plain ast.walk, which works identically over the MODULE root (not just a function
    # body) -- reused here rather than writing a second constant-tracking pass. Merged
    # as the LOWEST-priority layer (fixtures and per-test locals still shadow it, matching
    # normal Python scoping) so this never overrides a same-named fixture or local var.
    module_vars = _track_vars(tree)
    content_fixtures = _discover_content_to_file_fixtures(tree)
    fixture_path_exprs = _track_fixture_real_file_paths(tree)
    module_path_exprs = _track_module_level_path_exprs(tree)
    scratch_bases = {"tmp_path", "tmpdir"} | _discover_custom_scratch_dir_fixtures(tree)
    temp_file_factories = _discover_temp_file_factory_fixtures(tree)
    temp_files_object_names = _discover_temp_files_object_fixtures(tree)
    scratch_class_names = _discover_temp_files_context_manager_classes(tree)
    conf = path.parent / "conftest.py"
    if conf.exists():
        try:
            conf_tree = ast.parse(conf.read_text(encoding="utf-8", errors="replace"))
            # NOTE: resolver.learn(conf_tree) already happened EARLIER, before
            # resolver.learn(tree) -- see that block's comment (fix 39b) for why
            # the ORDER matters (a test file's own module-level constant must win
            # over a same-named conftest.py global). Not repeated here.
            fixtures.update(_track_fixtures(conf_tree))
            module_vars = {**_track_vars(conf_tree), **module_vars}
            content_fixtures = {**_discover_content_to_file_fixtures(conf_tree), **content_fixtures}
            fixture_path_exprs = {**_track_fixture_real_file_paths(conf_tree), **fixture_path_exprs}
            module_path_exprs = {**_track_module_level_path_exprs(conf_tree), **module_path_exprs}
            scratch_bases |= _discover_custom_scratch_dir_fixtures(conf_tree)
            temp_file_factories |= _discover_temp_file_factory_fixtures(conf_tree)
            temp_files_object_names |= _discover_temp_files_object_fixtures(conf_tree)
            scratch_class_names |= _discover_temp_files_context_manager_classes(conf_tree)
        except SyntaxError:
            pass
    # FIXTURE RETURNING A REAL FILE PATH (2026-07-17): resolved ONCE here (not threaded
    # as a new _file_arg parameter through _resolve_list/_resolve_list_concat/
    # _find_run_call, all of which would need the same plumbing) -- each fixture name is
    # evaluated via the resolver and, if it's a real existing file, merged directly into
    # `fixtures` as a plain basename STRING. `str(monkey_wav)` then resolves through the
    # ALREADY-existing bare-Name/vmap path exactly like any other fixture-bound constant,
    # and the real content is staged the same way _track_files stages any other file --
    # see the merge into files_map below.
    # MODULE-LEVEL PATH CONSTANT (2026-07-17): same reasoning, a plain module-level
    # `NAME = Path(...) / 'file'` (sox's MONKEY_WAV) rather than a fixture's return
    # value -- resolved the same eager way and merged into the SAME dict, since a bare
    # module-level Name and a bare fixture-parameter Name flow through the identical
    # files_map lookup at the call site.
    fixture_file_contents: dict[str, tuple[str, str]] = {}
    for fx_name, expr in {**module_path_exprs, **fixture_path_exprs}.items():
        hit = resolver.resolve_file_arg(expr)
        if hit is not None:
            fixture_file_contents[fx_name] = hit
    # FIXTURE RETURNING A BASE DIRECTORY (2026-07-18): `examples_dir` fixture returns
    # `Path(__file__).parent.parent.parent / "examples"` -- a DIRECTORY, not a single
    # file, meant to be further divided AT THE CALL SITE (`str(examples_dir / "language"
    # / "go.go")`, scc's whole test suite). The loop above only stages fixtures that
    # resolve to a real FILE (resolve_file_arg requires .is_file()); a directory-valued
    # fixture correctly produces no hit there, but the call-site expression rooted at the
    # fixture's bare Name still needs the resolver's eval_path to know what that name
    # means. resolver.vars (populated by learn() for MODULE-level constants only) never
    # sees fixture return values at all, so `examples_dir` as the base of a BinOp/Div
    # chain was structurally invisible. Registering each fixture_path_exprs entry's
    # EVALUATED path directly into resolver.vars lets eval_path's existing bare-Name
    # lookup (`self.vars.get(node.id)`) resolve it exactly like a module constant would
    # -- same safety argument fixture_path_exprs itself already relies on (a
    # conftest-defined fixture and the importing test file share the same parent
    # directory in this corpus's convention, so Path(__file__) resolves identically).
    for fx_name, expr in fixture_path_exprs.items():
        if fx_name in resolver.vars:
            continue
        p = resolver.eval_path(expr)
        if p is not None:
            resolver.vars[fx_name] = p
    extra_run_names = _discover_wrapper_names(tree, path)
    fixture_aliases = _discover_fixture_wrapper_aliases(tree, path, RUN_NAMES | extra_run_names)
    extra_run_names |= set(fixture_aliases)
    kwarg_flags = _discover_wrapper_kwarg_flags(tree, path)
    # ALIAS INHERITS TARGET'S LEARNED CONTRACT (2026-07-17): "run_cmd" (`def
    # run_cmd(): return run_binary`) was already a valid run-NAME via fixture_aliases,
    # but is_learned_wrapper at run_cmd's OWN call sites stayed False unless run_cmd
    # itself also has a kwarg_flags entry -- dropbear's whole test suite calls
    # run_cmd(...), never run_binary(...) directly, so run_binary's real, well-learned
    # base/flags/suffix contract needs copying under the alias's own name too.
    for alias_name, target_name in fixture_aliases.items():
        if alias_name not in kwarg_flags and target_name in kwarg_flags:
            kwarg_flags[alias_name] = kwarg_flags[target_name]
    assertion_helpers = _discover_assertion_helpers(tree, path)
    wrapper_shapes = _discover_wrapper_return_shapes(tree, path)
    run_fixtures = _track_run_fixtures(tree, extra_run_names, kwarg_flags, resolver)
    examples: list[Example] = []
    skipped: list[str] = []
    n_tests = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        base_vars = {**module_vars, **fixtures, **_track_vars(node)}  # local vars shadow fixtures
        cases = _parametrize_cases(node) or [{}]  # [{}] == the non-parametrized case
        n_tests += len(cases)
        # a test parameter naming exactly ONE run-invoking fixture stands in for a direct
        # run-call in the test's own body (see _track_run_fixtures) -- two or more such
        # params (e.g. comparing help_long vs help_short) means comparing TWO invocations,
        # a different shape this Example model can't express; correctly left unresolved
        # rather than guessing which one is "the" argv.
        param_names = [a.arg for a in node.args.args]
        fixture_hits = [run_fixtures[p] for p in param_names if p in run_fixtures]
        fallback = fixture_hits[0] if len(fixture_hits) == 1 else None
        # `with TempFiles() as tf:` inside THIS test's own body (gdal's whole test
        # suite, 355 occurrences/44 files) -- a per-test LOCAL variable binding,
        # not a tool-wide fixture parameter name, so it's computed per-test and
        # merged with the fixture-based names just for this test's own resolution.
        test_temp_files_names = temp_files_object_names | _track_with_block_scratch_objects(
            node, scratch_class_names
        )
        for case in cases:
            vars_map = {**base_vars, **case}
            # a local var assigned an f-string that references a parametrize value
            # (`filename = f"test.{extension}"`) is one indirection further than
            # _track_vars's constant-only pass reaches; resolve it now that `case` (and
            # therefore `extension`) is known, so argv/expectation resolution below sees it.
            vars_map = {**vars_map, **_track_local_fstring_vars(node, vars_map)}
            # `output_file = temp_dir / "output.png"` then passed BARE (no str() wrap) to
            # run_ditaa(input_file, output_file) -- a local scratch-output path assigned
            # first, referenced later, resolved the same way any other local constant is.
            vars_map = {**vars_map, **_track_local_scratch_vars(node, scratch_bases)}
            # `input_file = temp_audio_file(".wav")` -- a CALL to a temp-file-factory
            # fixture (sox's whole test suite), each call site getting its own distinct
            # scratch basename.
            vars_map = {**vars_map, **_track_temp_file_factory_vars(node, temp_file_factories)}
            # `dst = str(tf.path("copy.tif"))` -- gdal's whole test suite assigns a
            # temp-files-object .path() result to a local var FIRST, referenced bare
            # later, never inline at the call site.
            vars_map = {**vars_map, **_track_temp_files_path_vars(node, test_temp_files_names)}
            case_suffix = "[" + ",".join(str(v) for v in case.values()) + "]" if case else ""
            # `temp_files.create("large.txt", "x" * 10000)` -- a CUSTOM OBJECT
            # fixture's own .create() method staging real content (dust's whole
            # test suite, same class shape confirmed in caps-log/samtools/htop/gdal
            # too); resolved per-test since name/content can reference parametrize
            # values via vars_map, unlike the eagerly-resolved fixture-level dicts above.
            temp_files_created = _track_temp_files_object_creates(
                node, test_temp_files_names, vars_map
            )
            # `input_file = RESOURCES / "simple_box.txt"` -- a TEST-LOCAL var assigned
            # from a real, on-disk resolver-resolvable path expression, referenced BARE
            # later (ditaa's whole run_ditaa suite, 499 call sites) -- a third variant of
            # the fix 22/28 gap, this one local to the test body rather than a fixture
            # return value or a module-level constant.
            files_map = {
                **fixture_file_contents,
                **_track_files(node, vars_map, content_fixtures),
                **temp_files_created,
                **_track_resource_path_vars(node, resolver),
            }
            # a tracked file var's basename is also usable as a plain string (e.g. an
            # f-string reference in an ASSERTION, `assert f"@{test_file}" in stdout` --
            # the ARGV side already stages the file correctly via _file_arg; this just
            # lets the same variable resolve for expectation-side snippet checks too).
            vars_map = {**vars_map, **{v: bn for v, (bn, _content) in files_map.items()}}
            argv, stdin, env, files = _find_run_call(
                node,
                files_map,
                vars_map,
                extra_run_names,
                kwarg_flags,
                resolver,
                test_temp_files_names,
            )
            if argv is None and fallback is not None:
                argv, stdin, env, files = fallback
            elif argv is not None and temp_files_created:
                # dust's whole test suite: files staged via .create() are almost
                # never individually referenced in argv (the tool is invoked with
                # str(temp_files.path()) -- "." -- scanning the WHOLE directory),
                # so _find_run_call's used_files (only argv-REFERENCED files) alone
                # would miss them entirely. Merge them in unconditionally whenever
                # this test called .create() at all -- they need to exist in the
                # rundir regardless of whether any single one is named in argv.
                files = {
                    **(files or {}),
                    **{bn: content for bn, content in temp_files_created.values()},
                }
            if argv is None:
                skipped.append(node.name + case_suffix)
                continue
            # _find_expectations runs PER CASE (not once for the whole function) so a
            # parametrize substitution referenced directly in an assertion (`assert flag
            # in out`) resolves to that case's concrete value, not just the argv.
            rc, exact, contains, ci, in_any, not_in, rc_nonzero, rc_in = _find_expectations(
                node, resolver, assertion_helpers, wrapper_shapes, extra_vars=vars_map
            )
            if (
                rc is None
                and exact is None
                and not contains
                and not in_any
                and not not_in
                and not rc_nonzero
                and not rc_in
            ):
                skipped.append(node.name + case_suffix)
                continue
            examples.append(
                Example(
                    test=node.name + case_suffix,
                    argv=argv,
                    stdin=stdin,
                    env=env,
                    expect_rc=rc,
                    expect_rc_nonzero=rc_nonzero,
                    expect_rc_in=rc_in,
                    expect_stdout=exact,
                    expect_in=contains,
                    expect_in_any=in_any,
                    expect_not_in=not_in,
                    ci=ci,
                    files=files,
                    source=f"{path.name}:{node.lineno}",
                )
            )
    return Coverage(examples, n_tests, len(examples), skipped)


@dataclass
class InputProbe:
    """A recoverable test INPUT (no expectation) -- the reference fills the expectation."""

    test: str
    argv: list = field(default_factory=list)
    stdin: str | None = None
    env: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    source: str = ""


def extract_inputs_file(path: Path) -> list:
    """Every recoverable run-call INPUT in one test file (expectation NOT required)."""
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    resolver = _PathResolver(path)
    resolver.learn(tree)
    fixtures = _track_fixtures(tree)
    conf = path.parent / "conftest.py"
    if conf.exists():
        try:
            fixtures.update(
                _track_fixtures(ast.parse(conf.read_text(encoding="utf-8", errors="replace")))
            )
        except SyntaxError:
            pass
    extra_run_names = _discover_wrapper_names(tree, path)
    out: list = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        vars_map = {**fixtures, **_track_vars(node)}
        files_map = _track_files(node, vars_map)
        argv, stdin, env, files = _find_run_call(node, files_map, vars_map, extra_run_names)
        if argv is None:
            continue
        out.append(
            InputProbe(
                test=node.name,
                argv=argv,
                stdin=stdin,
                env=env or {},
                files=files or {},
                source=f"{path.name}:{node.lineno}",
            )
        )
    return out


def extract_inputs(test_dir: Path) -> list:
    """All recoverable test INPUTS under test_dir (deduped by (argv, stdin, sorted files))."""
    seen: set = set()
    out: list = []
    for path in sorted(Path(test_dir).rglob("test_*.py")):
        for ip in extract_inputs_file(path):
            key = (tuple(ip.argv), ip.stdin, tuple(sorted((ip.files or {}).items())))
            if key in seen:
                continue
            seen.add(key)
            out.append(ip)
    return out


def extract_dir(test_dir: Path) -> Coverage:
    all_ex: list[Example] = []
    all_sk: list[str] = []
    n_tests = 0
    for p in sorted(test_dir.rglob("test_*.py")):
        cov = extract_file(p)
        all_ex.extend(cov.examples)
        all_sk.extend(cov.skipped)
        n_tests += cov.n_tests
    return Coverage(all_ex, n_tests, len(all_ex), all_sk)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Determinex I/O-example extractor")
    ap.add_argument("test_dir", help="dir containing test_*.py (+ resolvable goldens)")
    ap.add_argument("--out", help="write examples JSON here")
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args(argv)
    cov = extract_dir(Path(a.test_dir))
    print(
        f"tests seen: {cov.n_tests}   examples extracted: {cov.n_examples}   "
        f"skipped: {len(cov.skipped)}   "
        f"({100 * cov.n_examples / max(cov.n_tests, 1):.0f}% coverage)"
    )
    exact = sum(1 for e in cov.examples if e.expect_stdout is not None)
    print(
        f"  with exact-stdout golden: {exact}   with rc: "
        f"{sum(1 for e in cov.examples if e.expect_rc is not None)}   "
        f"with contains: {sum(1 for e in cov.examples if e.expect_in)}"
    )
    for e in cov.examples[: a.show]:
        exp = f"rc={e.expect_rc}" if e.expect_rc is not None else ""
        ex = " EXACT" if e.expect_stdout is not None else ""
        ind = f" in={e.expect_in[:1]}" if e.expect_in else ""
        sd = f" stdin={e.stdin!r}" if e.stdin else ""
        print(f"  {e.test:46} argv={e.argv}{sd} {exp}{ex}{ind}")
    if a.out:
        Path(a.out).write_text(
            json.dumps([asdict(e) for e in cov.examples], indent=2), encoding="utf-8"
        )
        print(f"wrote {cov.n_examples} examples -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
