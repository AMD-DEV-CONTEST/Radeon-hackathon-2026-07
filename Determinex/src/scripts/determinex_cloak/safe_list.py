"""
determinex_cloak/safe_list.py — Safe-list construction (Component 1: StdlibManifest).

Builds the frozenset of names that are never proprietary:
  stdlib modules, builtins, third-party packages from requirements files,
  and a hardcoded always-safe set of framework/protocol names.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _ROOT / "data"
_STDLIB_MANIFEST = _DATA_DIR / "stdlib_312.txt"

# Framework/protocol names that are never proprietary regardless of safe-list
_ALWAYS_SAFE: frozenset[str] = frozenset(
    {
        # pytest fixtures and markers
        "pytest",
        "fixture",
        "mark",
        "parametrize",
        "raises",
        "warns",
        "approx",
        "capsys",
        "capfd",
        "capfdbinary",
        "monkeypatch",
        "tmpdir",
        "tmp_path",
        "request",
        "session",
        "module",
        "function",
        "class_",
        # django ORM / views
        "models",
        "views",
        "urls",
        "forms",
        "admin",
        "signals",
        "migrations",
        "apps",
        "CharField",
        "IntegerField",
        "BooleanField",
        "DateField",
        "DateTimeField",
        "FloatField",
        "TextField",
        "EmailField",
        "URLField",
        "SlugField",
        "UUIDField",
        "ForeignKey",
        "ManyToManyField",
        "OneToOneField",
        "AutoField",
        "BigAutoField",
        "Model",
        "View",
        "Form",
        "HttpResponse",
        "HttpRequest",
        "HttpResponseRedirect",
        "QuerySet",
        "Manager",
        "objects",
        "DoesNotExist",
        "MultipleObjectsReturned",
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        # numpy / pandas / scipy / matplotlib
        "np",
        "pd",
        "plt",
        "sp",
        "sns",
        "scipy",
        "numpy",
        "pandas",
        "matplotlib",
        "ndarray",
        "DataFrame",
        "Series",
        "Index",
        "MultiIndex",
        "Panel",
        "array",
        "zeros",
        "ones",
        "empty",
        "full",
        "arange",
        "linspace",
        "logspace",
        "reshape",
        "transpose",
        "concatenate",
        "stack",
        "hstack",
        "vstack",
        "dstack",
        "sum",
        "mean",
        "std",
        "var",
        "min",
        "max",
        "median",
        "percentile",
        "dot",
        "matmul",
        "cross",
        "outer",
        "inner",
        "trace",
        "det",
        "inv",
        "solve",
        "fft",
        "ifft",
        "rfft",
        "irfft",
        "fftfreq",
        "fftshift",
        # typing
        "Optional",
        "Union",
        "List",
        "Dict",
        "Tuple",
        "Set",
        "FrozenSet",
        "Any",
        "Callable",
        "Generator",
        "Iterator",
        "Iterable",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "MutableSequence",
        "MutableSet",
        "ClassVar",
        "Final",
        "TypeVar",
        "Generic",
        "Protocol",
        "overload",
        "TYPE_CHECKING",
        "cast",
        "no_type_check",
        "runtime_checkable",
        "dataclass_transform",
        "NamedTuple",
        "TypedDict",
        "Literal",
        "Annotated",
        "get_type_hints",
        "get_origin",
        "get_args",
        "is_typeddict",
        # abc
        "ABC",
        "ABCMeta",
        "abstractmethod",
        "abstractproperty",
        "abstractclassmethod",
        "abstractstaticmethod",
        # dataclasses
        "dataclass",
        "field",
        "fields",
        "asdict",
        "astuple",
        "replace",
        "make_dataclass",
        "InitVar",
        "KW_ONLY",
        # contextlib
        "contextmanager",
        "asynccontextmanager",
        "suppress",
        "nullcontext",
        "closing",
        "ExitStack",
        "AsyncExitStack",
        "redirect_stdout",
        "redirect_stderr",
        # pathlib
        "Path",
        "PurePath",
        "PosixPath",
        "WindowsPath",
        "PurePosixPath",
        "PureWindowsPath",
        # logging
        "Logger",
        "Handler",
        "Formatter",
        "Filter",
        "LogRecord",
        "LoggerAdapter",
        "StreamHandler",
        "FileHandler",
        "NullHandler",
        "RotatingFileHandler",
        # common structural argument names
        "self",
        "cls",
        "args",
        "kwargs",
        "mcs",
        # stdlib exceptions (comprehensive)
        "Exception",
        "BaseException",
        "ArithmeticError",
        "BufferError",
        "LookupError",
        "ValueError",
        "TypeError",
        "AttributeError",
        "KeyError",
        "IndexError",
        "NotImplementedError",
        "RuntimeError",
        "StopIteration",
        "StopAsyncIteration",
        "FileNotFoundError",
        "PermissionError",
        "OSError",
        "IOError",
        "FileExistsError",
        "IsADirectoryError",
        "NotADirectoryError",
        "InterruptedError",
        "BlockingIOError",
        "ChildProcessError",
        "ProcessLookupError",
        "TimeoutError",
        "ConnectionError",
        "BrokenPipeError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "ImportError",
        "ModuleNotFoundError",
        "NameError",
        "UnboundLocalError",
        "ZeroDivisionError",
        "OverflowError",
        "FloatingPointError",
        "MemoryError",
        "RecursionError",
        "SystemError",
        "ReferenceError",
        "GeneratorExit",
        "KeyboardInterrupt",
        "SystemExit",
        "AssertionError",
        "UnicodeError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeTranslateError",
        "SyntaxError",
        "IndentationError",
        "TabError",
        "EOFError",
        "Warning",
        "UserWarning",
        "DeprecationWarning",
        "SyntaxWarning",
        "RuntimeWarning",
        "FutureWarning",
        "PendingDeprecationWarning",
        "ImportWarning",
        "UnicodeWarning",
        "BytesWarning",
        "ResourceWarning",
        # common structural names used in tests
        "setUp",
        "tearDown",
        "setUpClass",
        "tearDownClass",
        "setUpModule",
        "tearDownModule",
        "main",
        "setup",
        "teardown",
        "conftest",
        # singleton values
        "True",
        "False",
        "None",
        "Ellipsis",
        "NotImplemented",
        # common variable names that carry no proprietary meaning
        "result",
        "results",
        "output",
        "outputs",
        "response",
        "responses",
        "error",
        "errors",
        "exception",
        "value",
        "values",
        "item",
        "items",
        "key",
        "keys",
        "data",
        "name",
        "names",
        "path",
        "paths",
        "msg",
        "message",
        "config",
        "params",
        "context",
        "ctx",
        "filename",
        "filepath",
        "dirname",
        "basename",
        "verbose",
        "debug",
        "encoding",
        "timeout",
        "default",
        "callback",
        "handler",
        "logger",
        "formatter",
        "level",
        # requests / httpx / aiohttp
        "requests",
        "httpx",
        "aiohttp",
        "Session",
        "Response",
        "Request",
        "status_code",
        "content",
        "text",
        "json",
        "headers",
        "cookies",
        "params",
        # sqlalchemy
        "Column",
        "Integer",
        "String",
        "Boolean",
        "Float",
        "Text",
        "DateTime",
        "Date",
        "Time",
        "Numeric",
        "LargeBinary",
        "Enum",
        "JSON",
        "ARRAY",
        "relationship",
        "backref",
        "Table",
        "MetaData",
        "Base",
        "create_engine",
        "sessionmaker",
        "declarative_base",
        "func",
        "and_",
        "or_",
        "not_",
        "case",
        "literal",
        # setuptools / packaging
        "find_packages",
        "Extension",
        "Command",
        "version",
        "author",
        "description",
        "url",
        "license",
        "packages",
        "install_requires",
        "extras_require",
        "python_requires",
    }
)

# Framework API override hooks — preserved by design (semantic anchoring pivot, 2026-05-11).
# These are public framework protocol names that appear in private code as method overrides.
# Obfuscating them destroys the model's framework-semantic signal without protecting
# any proprietary business logic (all names are in open-source framework documentation).
# Evidence: B-Cloaked resolved 3 django instances; D-Cloaked resolved 0, with identical
# obfuscated inputs — the diff is framework-semantic reasoning capability under obfuscation.
FRAMEWORK_KEEP_LIST: frozenset[str] = frozenset(
    {
        # Django ORM — model lifecycle hooks
        "save",
        "delete",
        "clean",
        "full_clean",
        "validate_unique",
        "validate_constraints",
        "get_absolute_url",
        "natural_key",
        "from_natural_key",
        "pre_save",
        "post_save",
        "pre_delete",
        "post_delete",
        # Django views — class-based view protocol
        "dispatch",
        "setup",
        "get_queryset",
        "get_object",
        "get_context_data",
        "get_form",
        "get_form_class",
        "get_form_kwargs",
        "form_valid",
        "form_invalid",
        "get_success_url",
        "get_initial",
        "get_prefix",
        "get_extra_form_kwargs",
        "render_to_response",
        "get_template_names",
        # Django signals
        "connect",
        "disconnect",
        "send",
        "send_robust",
        # Django admin
        "get_list_display",
        "get_list_filter",
        "get_search_fields",
        "get_readonly_fields",
        "get_fieldsets",
        "get_inlines",
        "save_model",
        "delete_model",
        "save_formset",
        # scikit-learn estimator protocol
        "fit",
        "transform",
        "fit_transform",
        "inverse_transform",
        "predict",
        "predict_proba",
        "predict_log_proba",
        "score",
        "get_params",
        "set_params",
        "decision_function",
        "sample",
        "partial_fit",
        # Flask view / blueprint
        "before_request",
        "after_request",
        "teardown_request",
        "before_app_request",
        "after_app_request",
        "errorhandler",
        "app_errorhandler",
        # Matplotlib / artist protocol
        "draw",
        "get_window_extent",
        "contains",
        "set_figure",
        # Sphinx extension protocol
        "build_finished",
        "build_inited",
        "env_before_read_docs",
        "source_read",
        "doctree_read",
        "doctree_resolved",
        # pytest hook protocol (beyond setUp/tearDown already in _ALWAYS_SAFE)
        "pytest_configure",
        "pytest_runtest_setup",
        "pytest_runtest_call",
        "pytest_runtest_teardown",
        "pytest_collection_modifyitems",
        "pytest_generate_tests",
        "pytest_fixture_setup",
        # astropy / sympy — numeric/algebraic protocol
        "evalf",
        "doit",
        "simplify",
        "expand",
        "factor",
        "collect",
        "subs",
        "xreplace",
        "rewrite",
        "as_real_imag",
        "to_Quantity",
        "decompose",
        "to",
        "cgs",
        "si",
    }
)


def _load_stdlib_names() -> frozenset[str]:
    """Load Python 3.12 stdlib module names from static manifest."""
    names: set[str] = set()
    if _STDLIB_MANIFEST.exists():
        for line in _STDLIB_MANIFEST.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
                names.add(line.split(".")[0])
    return frozenset(names)


def _load_builtin_names() -> frozenset[str]:
    """All names from Python builtins module."""
    import builtins

    return frozenset(dir(builtins))


def _load_repo_package_names(repo_path: Path) -> frozenset[str]:
    """
    Parse requirements files in the repo to build a safe-list of third-party packages.
    Scans: requirements*.txt, setup.cfg, pyproject.toml
    Returns top-level import names.
    """
    names: set[str] = set()

    _PKG_REMAP = {
        "scikit-learn": "sklearn",
        "scikit_learn": "sklearn",
        "pillow": "PIL",
        "beautifulsoup4": "bs4",
        "pyyaml": "yaml",
        "python-dateutil": "dateutil",
        "python_dateutil": "dateutil",
        "pyzmq": "zmq",
        "mysqlclient": "MySQLdb",
        "psycopg2-binary": "psycopg2",
        "psycopg2_binary": "psycopg2",
        "opencv-python": "cv2",
        "opencv_python": "cv2",
    }

    def _add(raw: str) -> None:
        raw = raw.strip()
        raw = re.split(r"[\[;>=<!~]", raw)[0].strip()
        if not raw or raw.startswith(("#", "-r", "-e", "-c", "http", "git+")):
            return
        import_name = raw.replace("-", "_").lower()
        for candidate in (
            raw,
            import_name,
            _PKG_REMAP.get(raw.lower(), ""),
            _PKG_REMAP.get(import_name, ""),
        ):
            if candidate:
                names.add(candidate)
                names.add(candidate.split(".")[0])

    for req_file in repo_path.glob("requirements*.txt"):
        try:
            for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                _add(line)
        except Exception:
            pass

    setup_cfg = repo_path / "setup.cfg"
    if setup_cfg.exists():
        try:
            content = setup_cfg.read_text(encoding="utf-8", errors="ignore")
            in_req = False
            for line in content.splitlines():
                if re.match(r"\s*install_requires\s*=", line):
                    in_req = True
                    continue
                if in_req:
                    if line.startswith("[") or (line.strip() and not line[0].isspace()):
                        break
                    _add(line)
        except Exception:
            pass

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"([A-Za-z][A-Za-z0-9_\-\.]+)"', content):
                _add(m.group(1))
        except Exception:
            pass

    return frozenset(n for n in names if n)


def _build_safe_list(repo_path: Path) -> frozenset[str]:
    stdlib = _load_stdlib_names()
    builtins = _load_builtin_names()
    pkgs = _load_repo_package_names(repo_path)
    return stdlib | builtins | pkgs | _ALWAYS_SAFE | FRAMEWORK_KEEP_LIST
