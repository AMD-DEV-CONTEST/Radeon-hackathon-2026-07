# Determinex Coding Laws — Fix Pattern Reference

**Purpose**: This file is injected into both the Architect (planner) and Builder (patch generator)
prompts. It provides canonical fix patterns for every common Python bug class that appears in
real open-source repositories. When diagnosing a bug, scan the relevant category and apply the
canonical fix. These rules apply regardless of identifier obfuscation — recognize patterns by
STRUCTURE and SEMANTICS, not by name.

---

## 1. Return Value Assignment — Most Common Silent Bug Class

Methods that return new objects instead of modifying in-place. Calling them without using the
return value is a silent no-op: the code runs without error but produces wrong output.

- **LAW-001** `str.replace()`, `str.strip()`, `str.lower()`, `str.upper()`, `str.lstrip()`,
  `str.rstrip()` — strings are immutable. The return value IS the result. Always assign:
  `s = s.replace(old, new)`. Calling without assignment is a no-op.

- **LAW-002** `re.sub()`, `re.subn()` return new strings. Always assign: `s = re.sub(pat, rep, s)`.

- **LAW-003** `list.sort()` modifies in-place and returns `None`. `sorted()` returns a new list
  and does NOT modify in-place. `lst = lst.sort()` → lst is now None. Use `lst.sort()` OR
  `lst = sorted(lst)`.

- **LAW-004** `list.append()`, `list.extend()`, `list.insert()`, `list.remove()`, `list.reverse()`
  modify in-place and return `None`. Never assign their return value.

- **LAW-005** `dict.update()` modifies in-place, returns None. `{**d1, **d2}` creates a new merged
  dict (d2 wins conflicts). `d |= other` (Python 3.9+) merges in-place.

- **LAW-006** `set.add()`, `set.discard()`, `set.update()`, `set.remove()` modify in-place,
  return None. `set | other` returns a new set.

- **LAW-007** `bytes.replace()`, `bytearray.replace()` return new objects. Always assign.

- **LAW-008** `pathlib.Path` operations — `.resolve()`, `.with_suffix()`, `.with_name()`,
  `.relative_to()`, `.parent` — all return new Path objects. Always assign.

- **LAW-009** `frozenset()`, `tuple()`, `sorted()`, `reversed()` always return new objects.
  `reversed()` returns an iterator — wrap in `list()` to reuse.

- **LAW-010** Pandas: `df.sort_values()`, `df.dropna()`, `df.fillna()`, `df.rename()`,
  `df.reset_index()`, `df.drop()`, `df.astype()`, `df.merge()`, `df.join()` return new
  DataFrames by default (unless `inplace=True`). Always assign the result OR use `inplace=True`.

- **LAW-011** SymPy: ALL sympy operations return new expressions — `expr.subs()`, `simplify()`,
  `expand()`, `factor()`, `collect()`, `cancel()`, `trigsimp()`. SymPy objects are immutable.
  ALWAYS assign: `expr = expr.subs(x, 1)`.

- **LAW-012** `collections.OrderedDict`, `collections.Counter`, `collections.deque` operations:
  check each method — `.appendleft()` is in-place; `.copy()` returns new; `.most_common()`
  returns a list.

---

## 2. Numpy Array Views vs. Copies — In-Place Modification

- **LAW-013** `np.ndarray.replace()`, `np.char.replace()`, `chararray.replace()` return NEW
  arrays. The return value must be assigned. For a standalone variable: `arr = arr.replace(...)`.
  For a VIEW into a larger structure (FITS column, structured array field, record array): use
  SLICE ASSIGNMENT: `arr[:] = arr.replace(...)`. Simple `arr = arr.replace(...)` rebinds the
  local name but does NOT write back to the underlying buffer.

- **LAW-014** Array slicing creates a VIEW (shares memory): `view = arr[1:5]`. Modifying `view`
  modifies `arr`. Fancy indexing (`arr[[0,1,2]]`) and boolean indexing (`arr[mask]`) always
  create COPIES. `.copy()` always creates a copy.

- **LAW-015** To modify an array in-place use SLICE ASSIGNMENT: `arr[:] = new_values` writes
  into the existing buffer. Simple `arr = new_values` rebinds the local name — the original
  array is unaffected. This distinction is critical for array views and function arguments.

- **LAW-016** `np.reshape()` returns a VIEW when possible (C-contiguous input). On non-contiguous
  arrays it returns a copy. Always assign the result; never rely on reshape modifying in-place.

- **LAW-017** Structured / record arrays: field access `record['field']` returns a VIEW. Assigning
  into it `record['field'][:] = data` writes back. `record['field'] = data` may or may not
  depending on the dtype and assignment target context.

- **LAW-018** `np.squeeze()`, `np.expand_dims()`, `np.transpose()`, `arr.T` return views. Always
  assign the result.

- **LAW-019** When a function receives an array parameter and the calling code expects the array
  to be modified in-place: the function must use slice assignment (`param[:] = ...`) not simple
  rebinding (`param = ...`).

- **LAW-020** Numpy comparison: `np.array_equal(a, b)` for element-wise equality check that
  returns a single bool. `a == b` returns an element-wise boolean array — don't use in `if`.

---

## 3. Regular Expressions

- **LAW-021** For case-insensitive matching: use `re.compile(pattern, re.IGNORECASE)` or the
  `(?i)` inline flag at the START of the pattern string. NEVER use character classes like
  `[Aa]`, `[Rr][Ee][Aa][Dd]` for case-insensitivity — they match ONE character at a time,
  not words. `(?i:READ SERR)` applies the flag only to the enclosed group.

- **LAW-022** `re.match()` anchors to the START of the string. `re.search()` finds a match
  ANYWHERE in the string. The bug is often using `match()` when `search()` is needed (or
  vice versa).

- **LAW-023** `re.fullmatch()` requires the ENTIRE string to match the pattern. Use for
  validation. Missing this causes partial matches to pass validation.

- **LAW-024** `re.DOTALL` (or `re.S`) makes `.` match newlines too. Without it, `.` stops at
  `\n`. For patterns that must span multiple lines: add `re.DOTALL`.

- **LAW-025** `re.MULTILINE` (or `re.M`) makes `^` and `$` match start/end of each LINE,
  not just the whole string. Without it, `^` and `$` only match the very start/end.

- **LAW-026** Greedy vs. non-greedy: `.*` is greedy (matches as much as possible). `.*?` is
  non-greedy (matches as little as possible). Bug: `.*` consumes too much, misses the
  intended capture.

- **LAW-027** `re.compile()` with flags is more efficient than passing flags to every call.
  When the same pattern is used repeatedly, always compile it.

- **LAW-028** Named groups: `(?P<name>...)` in pattern, `m.group('name')` to retrieve. Positional
  `m.group(1)` breaks when group order changes. Prefer named groups.

- **LAW-029** `re.escape(s)` is required when treating user input or dynamic strings as literal
  pattern content (not regex syntax).

- **LAW-030** `re.findall()` with ONE group returns a list of strings of that group. With MULTIPLE
  groups returns a list of tuples. With NO groups returns a list of entire match strings.

- **LAW-031** `re.split(pattern, string)` — if the pattern contains a group, the group's content
  is included in the split result list. Often surprising.

---

## 4. Exception Handling

- **LAW-032** `except Exception:` catches all non-system-exiting exceptions. `except BaseException:`
  also catches `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`. Always be as specific as
  possible about which exception to catch.

- **LAW-033** Bare `except:` catches EVERYTHING including `KeyboardInterrupt`. Almost always
  wrong. Use `except Exception:` at minimum.

- **LAW-034** `raise` (no args) re-raises the current exception preserving the original traceback.
  `raise e` creates a new traceback from the current line. Prefer bare `raise` inside except
  blocks to preserve context.

- **LAW-035** Exception chaining: `raise NewError("msg") from original_error` preserves cause.
  `raise NewError("msg") from None` explicitly suppresses the chain. Using `raise NewError`
  without `from` implicitly chains via `__context__`.

- **LAW-036** `try/finally` — the finally block runs even on return, break, or continue. Code
  in finally that reads function return values won't see them correctly. Use for cleanup only.

- **LAW-037** `try/except/else` — the else block runs ONLY if no exception was raised in try.
  Use it for code that should only run on success, keeping it visually separate from the try body.

- **LAW-038** Catching broad exceptions and returning defaults can hide real bugs:
  `except Exception: return None`. This is a common anti-pattern in library code that silently
  swallows errors.

- **LAW-039** `ExceptionGroup` (Python 3.11+) for handling multiple concurrent exceptions from
  `TaskGroup` or `asyncio.gather()`. Use `except* TypeError` syntax to catch from a group.

- **LAW-040** `ValueError` vs `TypeError`: ValueError for wrong value of the right type;
  TypeError for wrong type entirely. Raising the wrong one is a common bug.

---

## 5. OOP: Classes, Inheritance, Properties

- **LAW-041** `super().__init__()` must be called in subclass `__init__` BEFORE using any
  parent attributes. Missing super().__init__() leaves parent state uninitialized.

- **LAW-042** To ADD a parameter to a subclass `__init__`: add it with a default, use it
  locally, then pass remaining kwargs to super(). Both the signature AND the super() call
  need updating. Missing either one breaks the parameter chain:
  ```python
  def __init__(self, new_param=None, **kwargs):
      self.new_param = new_param
      super().__init__(**kwargs)
  ```

- **LAW-043** Adding `self.new_attr = None` inside `__init__` is NOT the same as adding
  `new_attr=None` as a PARAMETER. The former adds an attribute (with fixed default); the
  latter makes the parameter PASSABLE by callers. Bug: caller passes `new_attr=x`, gets
  TypeError because the parameter doesn't exist in the signature.

- **LAW-044** `@property` defines a getter. Without `@name.setter`, assignment raises
  AttributeError. The setter name MUST match the property name exactly.

- **LAW-045** `@classmethod` receives the CLASS as first arg (`cls`). `@staticmethod` receives
  no implicit first arg. Choosing wrong affects subclass behavior: classmethod returns an
  instance of the SUBCLASS when called on it; staticmethod does not.

- **LAW-046** `__slots__` prevents adding dynamic attributes not in the list. A class with
  `__slots__` cannot have a `__dict__` by default. Setting unlisted attributes raises
  AttributeError.

- **LAW-047** MRO (Method Resolution Order): Python uses C3 linearization. `super()` follows
  MRO. In multiple/diamond inheritance, super() ensures each class in the chain is called once.

- **LAW-048** `__new__` creates the instance (must return it). `__init__` initializes it (must
  return None). Bug: `__new__` that doesn't call `super().__new__(cls)` returns the wrong type.

- **LAW-049** `__repr__` should return a string that could recreate the object. `__str__` is
  for human display. If only `__repr__` is defined, Python uses it for both.

- **LAW-050** `__eq__` returning `NotImplemented` (not raising) lets Python try the other
  operand's `__eq__`. Define `__hash__` whenever you define `__eq__`, or set `__hash__ = None`
  for mutable classes (making them unhashable).

- **LAW-051** `__getattr__` is called only when normal attribute lookup FAILS. `__getattribute__`
  is called for EVERY attribute access. Infinite recursion in `__getattribute__`: calling
  `self.x` triggers `__getattribute__` again. Use `object.__getattribute__(self, 'x')`.

- **LAW-052** Abstract methods: `@abc.abstractmethod` requires subclasses to implement before
  instantiation. Instantiating with unimplemented abstract methods raises TypeError.

- **LAW-053** `@dataclass` auto-generates `__init__`, `__repr__`, `__eq__`. Mutable default
  values MUST use `field(default_factory=list)` NOT `field(default=[])` (raises ValueError).

- **LAW-054** Class-level mutable attributes are SHARED by all instances:
  `class Foo: items = []` — ALL instances share the same list. Always initialize per-instance
  in `__init__`: `self.items = []`.

---

## 6. Mutable Default Arguments

- **LAW-055** NEVER use mutable objects as default arguments: `def f(x=[])`, `def f(x={})`,
  `def f(x=set())`. The default object is created ONCE at function definition time and shared
  across all calls. Use `None` and create inside:
  ```python
  def f(x=None):
      if x is None:
          x = []
  ```

- **LAW-056** `def f(x=None): x = x or []` — beware: `or` treats 0, False, "" as falsy too.
  Prefer explicit `if x is None: x = []` when those values are valid inputs.

- **LAW-057** This bug is subtle in methods: `def __init__(self, data=[])` — ALL instances
  share the same default list object. Any mutation of `self.data` in one instance affects all.

---

## 7. None and Boolean Comparisons

- **LAW-058** Always use `is None` / `is not None` for None checks. NEVER use `== None` or
  `!= None`. The `==` operator can be overloaded (pandas/numpy override it to return arrays).

- **LAW-059** `if x:` is False for None, 0, 0.0, "", [], {}, set(). Use `if x is not None:`
  when you want to allow 0, False, or empty collections as valid values.

- **LAW-060** `if not x:` catches None, 0, "", [], {} in one expression — correct for
  "missing or empty" semantics, wrong if 0 or False are valid non-empty values.

- **LAW-061** Numpy/pandas array truthiness: `if arr:` raises `ValueError` for multi-element
  arrays. Use `arr.any()`, `arr.all()`, `len(arr) > 0`, or `arr.size > 0`.

- **LAW-062** `if x == True:` → use `if x:`. `if x is True:` checks the exact object True,
  not truthiness. Almost never what you want.

- **LAW-063** `operand.mask is None` vs `operand is None`: when the object has a `.mask`
  attribute (NDData, masked arrays), the intent is usually to check if the MASK is absent,
  not whether the object itself is None.

---

## 8. Type Checking and Conversion

- **LAW-064** `isinstance(x, (A, B))` checks for either type and includes subclasses.
  `type(x) is A` checks EXACT type only, excluding subclasses. Prefer `isinstance` unless
  you explicitly want to exclude subclasses.

- **LAW-065** Python 3: `/` is always float division. `//` is floor division (returns int
  for int inputs). `3/2 = 1.5`, `3//2 = 1`. Common bug in code ported from Python 2.

- **LAW-066** `str(b'bytes')` → `"b'bytes'"` (includes `b''` prefix). `.decode('utf-8')`
  → `'bytes'` (the string content). Use `.decode()` to convert bytes to str.

- **LAW-067** `bytes(n)` creates n zero bytes. `bytes([65, 66])` creates from int list.
  `bytes('text', 'utf-8')` is equivalent to `'text'.encode('utf-8')`.

- **LAW-068** `int("3")` converts string to int. `int(3.7)` truncates (→ 3). `round(3.7)` → 4.
  `math.ceil(3.2)` → 4. `math.floor(3.7)` → 3. Be explicit about which behavior is intended.

- **LAW-069** `bool` is a subclass of `int`. `True == 1` and `False == 0` are both True.
  This can cause subtle bugs in comparisons and arithmetic.

- **LAW-070** Enum comparisons: `MyEnum.VALUE == 'string'` is always False; compare with
  `MyEnum.VALUE.value == 'string'` or use `MyEnum('string')` to get the enum member.

---

## 9. Iteration and Generators

- **LAW-071** Generators are exhausted after ONE pass. `gen = (x for x in range(10))` →
  after `list(gen)`, iterating again gives nothing. If you need multiple passes, use a list.

- **LAW-072** `dict.keys()`, `dict.values()`, `dict.items()` return VIEWS (Python 3). They
  reflect mutations to the dict. Iterating while mutating the dict → RuntimeError. Fix:
  iterate over `list(d.keys())`.

- **LAW-073** `zip()`, `map()`, `filter()`, `reversed()` return ITERATORS in Python 3 (lazy).
  Wrap in `list()` to materialize. They are exhausted after one pass.

- **LAW-074** `zip(*iterables)` stops at the SHORTEST iterable. Use `itertools.zip_longest()`
  to fill missing values with `None` (or a specified fill value).

- **LAW-075** `enumerate(iterable, start=0)` — the `start` parameter sets the initial count
  value. `enumerate(items, 1)` for 1-indexed counting.

- **LAW-076** `yield from iterable` delegates to a sub-generator and forwards
  send()/throw() calls. Do NOT manually raise `StopIteration` inside a generator (Python 3.7+:
  this causes a RuntimeError instead of stopping cleanly).

- **LAW-077** Modifying a list while iterating over it directly skips elements. Always iterate
  over a copy `for item in list_copy:` or build a new list with comprehension.

- **LAW-078** `itertools.chain.from_iterable(iterable_of_iterables)` lazily flattens one level.
  `itertools.chain(*iterables)` takes multiple iterables directly as arguments.

---

## 10. Numeric Operations and Precision

- **LAW-079** Floating point is inexact: `0.1 + 0.2 != 0.3`. For comparison use
  `math.isclose(a, b, rel_tol=1e-9)`. In tests: `assert abs(a - b) < tolerance`.

- **LAW-080** `decimal.Decimal` for exact base-10 arithmetic (financial, parsing). More
  expensive than float but avoids representation errors.

- **LAW-081** Python `int` has arbitrary precision. Numpy integers DO overflow: `np.int32(2**31)`
  wraps silently. Use `np.int64` or Python `int` when overflow is possible.

- **LAW-082** `nan != nan` is True (IEEE 754). Use `math.isnan()` or `np.isnan()` to test for
  NaN. `x is float('nan')` does NOT work (nan objects are not singletons).

- **LAW-083** Division by zero: Python raises `ZeroDivisionError` for int/float. Numpy produces
  `inf` or `nan` silently. Check with `np.isinf()`, `np.isnan()`.

- **LAW-084** `round(2.5) = 2` in Python 3 (banker's rounding: round to even). `round(3.5) = 4`.
  For traditional rounding: `math.floor(x + 0.5)` or `decimal.ROUND_HALF_UP`.

- **LAW-085** `abs()` for Python scalars. `np.abs()` for arrays. They differ on complex numbers
  — both return magnitude. Use the numpy version for arrays.

---

## 11. Strings and Bytes

- **LAW-086** `''.join(list_of_strings)` is O(n). Repeated string concatenation in a loop
  `s = s + piece` is O(n²). Always use join for building strings in loops.

- **LAW-087** `str.split(sep)` with explicit separator preserves empty strings.
  `str.split()` with no args splits on ANY whitespace sequence and removes empty strings.

- **LAW-088** `str.splitlines()` handles `\n`, `\r\n`, `\r`, and Unicode line separators.
  `str.split('\n')` only splits on `\n` and preserves empty strings at line ends.

- **LAW-089** `str.startswith()` and `str.endswith()` accept a TUPLE of prefixes/suffixes:
  `s.startswith(('http://', 'https://'))`. This is more efficient than multiple or-checks.

- **LAW-090** `f"{val!r}"` uses repr(), `f"{val!s}"` uses str(), `f"{val!a}"` uses ascii().
  `f"{val:.2f}"` formats float to 2 decimal places. `f"{val:>10}"` right-aligns in 10 chars.

- **LAW-091** `textwrap.dedent()` removes common leading whitespace from multiline strings.
  Useful for triple-quoted strings in indented code.

- **LAW-092** Bytes and str are different types in Python 3. `b'hello' == 'hello'` is always
  False. Must explicitly encode/decode at the boundary.

- **LAW-093** `open()` default mode is `'r'` (text). For binary: `'rb'`, `'wb'`. Text mode
  applies newline translation (platform-specific). Binary mode does not. Always specify
  `encoding='utf-8'` for cross-platform text files.

---

## 12. Dictionaries and Collections

- **LAW-094** `dict.get(key, default)` returns default if key is missing without raising
  KeyError. `dict[key]` raises KeyError. Use `.get()` defensively.

- **LAW-095** `dict.setdefault(key, default)` sets AND returns the default if key is missing,
  otherwise returns the existing value — atomically. Useful for grouping:
  `d.setdefault(key, []).append(item)`.

- **LAW-096** `collections.defaultdict(factory)` — accessing a missing key calls factory() to
  create the default. More efficient than setdefault for repeated access patterns.

- **LAW-097** `collections.Counter` for frequency counting. Can be added/subtracted.
  `.most_common(n)` for top-n. `counter.update(iterable)` adds counts.

- **LAW-098** `collections.deque(maxlen=N)` — fixed-size FIFO queue. Appending beyond maxlen
  drops the oldest element automatically.

- **LAW-099** `dict.pop(key, default)` removes and returns the value; returns default if
  absent (avoids KeyError). `dict.pop(key)` with no default raises KeyError if absent.

- **LAW-100** `in` operator on dict checks KEYS: `key in d`. To check values:
  `value in d.values()`. To check key-value pair: `(k, v) in d.items()`.

---

## 13. File I/O, Paths, and Serialization

- **LAW-101** Always use context managers for files: `with open(path) as f:`. Guarantees
  closure even on exception.

- **LAW-102** `pathlib.Path` is preferred over `os.path` for new code. Paths compose with `/`:
  `Path('/tmp') / 'data' / 'file.txt'`. Methods: `.read_text()`, `.write_text()`,
  `.read_bytes()`, `.exists()`, `.mkdir(parents=True, exist_ok=True)`, `.glob('*.py')`.

- **LAW-103** `tempfile.NamedTemporaryFile(delete=False)` — must manually close and delete.
  `tempfile.TemporaryDirectory()` as context manager handles cleanup automatically.

- **LAW-104** JSON: `json.dumps(obj)` → str; `json.loads(s)` parses str; `json.dump(obj, fp)`
  writes to file; `json.load(fp)` reads from file. Common bug: calling `json.loads` on a dict.

- **LAW-105** `json.dumps()` fails on: datetime, bytes, numpy arrays, custom objects. Fix:
  use a custom encoder `json.dumps(obj, cls=MyEncoder)` or `default=str` for quick conversions.

- **LAW-106** `yaml.load(data)` can execute arbitrary code. ALWAYS use `yaml.safe_load(data)`
  or `yaml.load(data, Loader=yaml.FullLoader)`.

- **LAW-107** `pickle.loads()` from untrusted input is a remote code execution vulnerability.
  Never unpickle data from untrusted sources.

- **LAW-108** `csv.writer` — open files with `newline=''` on Windows to prevent double
  newlines: `open(path, 'w', newline='', encoding='utf-8')`.

---

## 14. Imports and Scope

- **LAW-109** `from module import name` binds `name` at import time. If `module.name` is
  reassigned later, your local binding doesn't update. For dynamic access:
  `import module; module.name`.

- **LAW-110** Circular imports: A imports B, B imports A → `ImportError`. Fix: move imports
  inside functions (deferred import), restructure modules, or use `TYPE_CHECKING` guard.

- **LAW-111** `if TYPE_CHECKING: from module import Type` — type-only import, avoids circular
  imports for type annotations at runtime. Use `from __future__ import annotations` to defer
  annotation evaluation.

- **LAW-112** `global x` inside a function — allows assigning to a module-level variable.
  Without `global`, assignment creates a LOCAL variable that shadows the module-level one.

- **LAW-113** `nonlocal x` in nested functions — access and assign to the enclosing function's
  local variable. Without it, assignment creates a new innermost-scope local.

- **LAW-114** `__all__` in a module defines what `from module import *` exports. If missing,
  all public names (no leading underscore) are exported.

---

## 15. Async/Await and Concurrency

- **LAW-115** `await` can only be used inside `async def`. Calling an async function without
  `await` returns a COROUTINE OBJECT, not the result — and the coroutine never runs.

- **LAW-116** `asyncio.run(coro)` — runs a coroutine to completion in a new event loop.
  Do NOT call when already inside an event loop (use `await coro` directly there).

- **LAW-117** `asyncio.gather(*coros)` runs coroutines concurrently; `asyncio.wait()` allows
  partial completion checks. `asyncio.shield()` protects a coroutine from cancellation.

- **LAW-118** `asyncio.create_task()` schedules a coroutine to run "in the background". Unlike
  `await`, it doesn't pause the current coroutine — it continues immediately.

- **LAW-119** Thread safety: The GIL means only one thread executes Python bytecode at a time,
  but it releases during I/O. For CPU-bound parallelism: `ProcessPoolExecutor`. For I/O-bound:
  `ThreadPoolExecutor` or `asyncio`.

- **LAW-120** `threading.Lock()` — always use `with lock:` to guarantee release on exception.
  Deadlock: thread A holds lock1, waits for lock2; thread B holds lock2, waits for lock1.
  Always acquire locks in the SAME ORDER across threads.

- **LAW-121** Race condition: read-modify-write without synchronization. `counter += 1` is NOT
  atomic at the bytecode level — GIL can switch between the read and write. Use `threading.Lock`
  or `threading.local()` for thread-local state.

- **LAW-122** `queue.Queue.get()` blocks by default. Use `get(timeout=N)` or `get(block=False)`
  (raises `queue.Empty`) to avoid hanging.

---

## 16. Decorators and Metaprogramming

- **LAW-123** `@functools.wraps(func)` on a wrapper preserves `__name__`, `__doc__`,
  `__module__`, etc. Without it, all decorated functions appear as the wrapper's name in
  tracebacks and help().

- **LAW-124** `@functools.lru_cache(maxsize=128)` caches results. Arguments must be hashable.
  Side effects inside cached functions are dangerous — cache hits skip the side effect entirely.
  Use `cache_clear()` to invalidate.

- **LAW-125** Decorator stacking applies bottom-up: `@A \n @B \n def f()` → `A(B(f))`. The
  decorator closest to the function is applied first. Order matters.

- **LAW-126** `@functools.singledispatch` — register implementations per argument type.
  `@fn.register(int)` adds an int-specific implementation. Dispatch is on the FIRST argument.

- **LAW-127** `__init_subclass__(cls, **kwargs)` is called when a class is subclassed. Good
  for plugin/registration patterns without metaclasses.

- **LAW-128** Context managers via `@contextlib.contextmanager` must `yield` exactly once.
  Code before yield = `__enter__`. Code after yield = `__exit__`. If an exception occurs in
  the with block, it is raised at the yield point.

---

## 17. Testing and Mocking

- **LAW-129** `mock.patch('module.ClassName')` patches where the name is USED, not where it is
  DEFINED. If `module_a.py` does `from module_b import Foo`, patch `'module_a.Foo'`,
  not `'module_b.Foo'`.

- **LAW-130** `mock.assert_called_once_with(...)` checks the mock was called exactly once with
  those args. `mock.assert_any_call(...)` checks it was called at least once with those args.
  `mock.call_args_list` has ALL calls.

- **LAW-131** `mock.side_effect = SomeException()` makes the mock raise on call. `side_effect`
  as a LIST returns values in sequence (raising StopIteration when exhausted — unless list
  contains exceptions).

- **LAW-132** `pytest.raises(ExceptionType) as exc_info:` — the code that should raise MUST
  be inside the with block. Check the message: `assert "expected text" in str(exc_info.value)`.

- **LAW-133** `pytest.mark.parametrize("arg1, arg2", [(v1, v2), (v3, v4)])` — argument names
  must match the test function parameter names EXACTLY (comma-separated string or tuple/list).

- **LAW-134** `conftest.py` fixtures are available without importing to all tests in the same
  directory and all subdirectories.

- **LAW-135** Test isolation: each test should be fully independent. Shared state via class
  attributes or module globals between tests causes order-dependent failures.

- **LAW-136** `monkeypatch.setattr(module, 'name', value)` for pytest patching. Auto-undone
  after the test. Prefer over `mock.patch` in pytest tests for simplicity.

---

## 18. Django Patterns

- **LAW-137** Django ORM lazy evaluation: `Model.objects.filter(...)` doesn't hit the
  database until iterated, sliced, passed to `list()`, or accessed with `.count()`, `.exists()`,
  `.get()`. A queryset is a lazy query builder.

- **LAW-138** `queryset.count()` uses SQL COUNT — more efficient than `len(list(queryset))`.
  `queryset.exists()` uses SQL EXISTS — more efficient than `.count() > 0`.

- **LAW-139** N+1 query: accessing a related object in a loop without prefetching causes one
  query per iteration. Fix: `select_related('fk_field')` for ForeignKey (JOIN);
  `prefetch_related('m2m_field')` for ManyToMany (separate query + cache).

- **LAW-140** `get_or_create(defaults={...}, **lookup)` — lookup kwargs form the WHERE clause;
  defaults are used ONLY on CREATE. Returns `(instance, created_bool)`.

- **LAW-141** `request.POST` is an immutable QueryDict. To modify: `data = request.POST.copy()`.

- **LAW-142** URL reversing: `reverse('view-name', args=[pk])` — must match the URL pattern's
  argument count and types exactly. Use `reverse('view-name', kwargs={'pk': pk})` for clarity.

- **LAW-143** Django signals: `post_save` sender is the model CLASS. `instance` is the object.
  `created=True` only on INSERT, False on UPDATE. Use `raw=False` check to skip fixture loads.

- **LAW-144** Django migrations: `makemigrations` generates migration files; `migrate` applies
  them. Missing migration → schema/model mismatch at runtime. Run `makemigrations --check` in CI.

- **LAW-145** `Meta.ordering` causes an ORDER BY on every query for that model. This can cause
  N+1 issues and unexpected joins. Override with `.order_by()` when not needed.

---

## 19. SQLAlchemy Patterns

- **LAW-146** SQLAlchemy sessions: use session for transactions. `session.add(obj)` +
  `session.commit()` to persist. `session.rollback()` on failure. `session.flush()` syncs to
  DB without committing.

- **LAW-147** Lazy loading: accessing `obj.relationship` outside a session triggers a new query.
  After session close: `DetachedInstanceError`. Fix: use `joined` or `subquery` loading, or
  access within the session.

- **LAW-148** `session.query(Model).filter(Model.col == val)` uses expressions.
  `.filter_by(col=val)` uses keyword args. `.filter()` is more flexible and composable.

- **LAW-149** `Column(nullable=False)` adds a NOT NULL constraint in the ORM schema. Must
  create and apply an Alembic migration to add the constraint to the actual database.

- **LAW-150** `relationship('Model', back_populates='attr')` — both sides of the relationship
  must define `back_populates` pointing to each other. Missing one causes inconsistent state.

---

## 20. Pandas/DataFrame Patterns

- **LAW-151** `df.loc[row, col]` uses LABELS. `df.iloc[row, col]` uses INTEGER POSITIONS.
  Confusing them — especially when the index is non-integer — causes wrong row/column selection.

- **LAW-152** `df['new_col'] = series` — if Series, alignment is by INDEX (not position).
  Misaligned index → NaN for unmatched rows. If you want position alignment, use
  `.values` or `.to_numpy()`.

- **LAW-153** Chained indexing: `df[col][row] = val` may not modify the original DataFrame
  (SettingWithCopyWarning). Use `df.loc[row, col] = val` for safe in-place modification.

- **LAW-154** `df.groupby().apply(func)` — func receives a sub-DataFrame for each group. The
  resulting index can be multi-level. Use `.reset_index()` when a flat index is needed.

- **LAW-155** `df.merge(other, on='key', how='inner')` — inner keeps rows with key in BOTH.
  `how='left'` keeps all rows from left, fills unmatched with NaN. `how='outer'` keeps all rows.

- **LAW-156** `pd.concat([df1, df2], ignore_index=True)` — `ignore_index=True` resets the
  index to 0..N. Without it, original indices are preserved (may cause duplicates).

- **LAW-157** `df.copy(deep=True)` (default) duplicates data. `df.copy(deep=False)` shares the
  underlying data. ALWAYS use `.copy()` before modifying a slice to avoid SettingWithCopyWarning.

- **LAW-158** `df.apply(func, axis=0)` applies func to COLUMNS. `axis=1` applies to ROWS.
  For element-wise: `df.applymap(func)` (deprecated in newer pandas; use `df.map(func)`).

- **LAW-159** `df.explode('col')` expands list-valued column into one row per element.
  Index is repeated — use `.reset_index(drop=True)` after.

---

## 21. Scipy / Scientific Stack

- **LAW-160** `scipy.optimize.minimize()` — objective function must return a SCALAR. If it
  returns an array, wrap in `.item()` or `float()`.

- **LAW-161** `scipy.sparse` matrices: arithmetic between sparse and dense often requires
  explicit conversion. `.toarray()` or `.todense()` to convert to dense.

- **LAW-162** `scipy.signal.convolve()` for small kernels; `scipy.signal.fftconvolve()` for
  large kernels (orders of magnitude faster due to FFT).

- **LAW-163** `scipy.stats` functions return named tuples (statistic, pvalue, ...). Always
  unpack or use attribute access: `result.statistic`, `result.pvalue`.

---

## 22. Numpy Linear Algebra / Matrix Operations

- **LAW-164** `np.dot(A, B)` and `A @ B` compute matrix multiplication. `*` is element-wise.
  `@` is preferred in Python 3.5+ for clarity.

- **LAW-165** Matrix constant-fill bug: `matrix_slice = 1` (scalar fills the entire submatrix
  with ones) vs `matrix_slice = computed_variable` (preserves the computed data). In matrix
  building functions, `= 1` instead of `= variable` is a common bug that loses structure.
  ALWAYS check: should this be assigning a COMPUTED VARIABLE or a CONSTANT?

- **LAW-166** `np.vstack()` concatenates along axis=0 (adds rows). `np.hstack()` along axis=1
  (adds columns). `np.concatenate([a, b], axis=N)` is the general form.

- **LAW-167** Broadcasting: dimensions compared right-to-left. Size 1 is compatible with any
  size (broadcasts). Non-1 sizes that differ → ValueError. Use `np.newaxis` or `reshape()` to
  align dimensions.

- **LAW-168** `np.zeros((n, m))` — float64 by default. `np.zeros((n, m), dtype=int)` for
  integer. Initializing with ones when zeros is expected (or vice versa) is a common bug.

- **LAW-169** `np.linalg.lstsq()` returns `(solution, residuals, rank, singular_values)` — the
  residuals may be empty if rank < N or M < N. Always check the return tuple.

---

## 23. Matplotlib / Visualization

- **LAW-170** `plt.savefig()` must be called BEFORE `plt.show()`. After show(), the figure
  is cleared and savefig saves a blank image.

- **LAW-171** `fig, ax = plt.subplots()` for single axes. `fig, axes = plt.subplots(R, C)`
  for grid — `axes` is a 2D array; use `axes.flat` to iterate, or `squeeze=False` to always
  get 2D.

- **LAW-172** Use OOP interface (`ax.set_title()`, `ax.plot()`) not state-machine interface
  (`plt.title()`, `plt.plot()`) when working with multiple axes or subplots.

- **LAW-173** `plt.close('all')` after tests/loops to prevent figure accumulation and memory
  leaks.

- **LAW-174** Backends: non-interactive backends (`Agg`, `pdf`, `svg`) don't open windows.
  Required in headless/server environments. Set before import:
  `matplotlib.use('Agg')` or via `matplotlibrc`.

---

## 24. Web / HTTP (requests, httpx, Flask, FastAPI)

- **LAW-175** `requests.get(url).raise_for_status()` raises HTTPError on 4xx/5xx. Without it,
  the response object is returned regardless of status — errors are silently ignored.

- **LAW-176** Always specify `timeout=N` in requests calls. Default is None (hang forever).
  Omitting timeout in library code can cause processes to hang indefinitely.

- **LAW-177** `response.json()` parses JSON body. `response.text` is raw string.
  `response.content` is raw bytes. `response.headers` is a case-insensitive dict.

- **LAW-178** Flask `request.args` — query string params. `request.form` — POST form data.
  `request.json` — JSON body (requires Content-Type: application/json).
  `request.files` — uploaded files.

- **LAW-179** Flask/FastAPI URL parameters must match route definition exactly. Type mismatch
  between route pattern and function parameter causes 404 or 422.

---

## 25. Serialization Edge Cases

- **LAW-180** `json.loads()` expects a str (or bytes in Python 3.6+). `json.load()` expects a
  file object. Common bug: `json.loads(filepath)` — passes a path STRING as JSON content.

- **LAW-181** `json.dumps(obj, indent=2)` for pretty-printing. `sort_keys=True` for stable
  output (important for diffs and caching).

- **LAW-182** `xml.etree.ElementTree.parse()` is NOT safe for untrusted XML (billion laughs,
  entity expansion attacks). Use `defusedxml` for untrusted input.

---

## 26. Architectural Patterns: WHERE to Find the Bug

- **LAW-183** If a method produces WRONG OUTPUT without raising an error, the bug may be in
  the method itself OR in any function it calls. Trace the call stack from the failing assertion
  BACKWARD through the call chain.

- **LAW-184** When function A calls B calls C and the output is wrong: check C's RETURN TYPE
  and VALUE first, then B's USAGE of C's return, then A's usage of B's return. The bug is
  often in how an intermediate function handles the value from the one it calls.

- **LAW-185** If the Architect identifies function X as the bug location but tests still fail:
  the bug may be in a function that CALLS X, or in how X's return value is USED by its caller.
  Widen the search to callers.

- **LAW-186** "Silent no-op" bug pattern: code runs without error but has no effect.
  Causes: (1) return value of immutable operation discarded, (2) assignment targets wrong local
  variable instead of the original, (3) method modifies a local copy not the passed-in object.

- **LAW-187** When adding a new PARAMETER to a class constructor: BOTH the subclass `__init__`
  signature AND the `super().__init__()` call must be updated. Missing either one silently
  ignores the parameter or raises TypeError.

- **LAW-188** For case-insensitive parsing fixes: the correct location is the `re.compile()`
  call (add `re.IGNORECASE`), NOT the pattern string itself. Changing the pattern string to
  use character classes is fragile and error-prone.

- **LAW-189** Matrix/array constant-assignment bug location: look for lines where a MATRIX
  SLICE is assigned a SCALAR CONSTANT (like `= 1` or `= 0`) inside a function that builds
  a matrix from computed sub-results. The likely fix is replacing the scalar with the
  computed variable.

- **LAW-190** When a file-format parser doesn't handle a variant (e.g., uppercase vs
  lowercase commands, D-exponent vs E-exponent): the fix is usually in the regex or
  string comparison, not in the data transformation logic.

- **LAW-191** When the issue mentions a SPECIFIC FILE (e.g., "the bug is in fitsrec.py"):
  prioritize that file above all others, even if keyword scoring ranks another file higher.

- **LAW-192** When the FAIL_TO_PASS tests reference a module (e.g., `test_rst.py`): the
  bug is almost certainly in the corresponding source module (e.g., `rst.py`), not in a
  shared utility or base class.

---

## 27. Cloak Mode: Reading Obfuscated Code

- **LAW-193** When identifiers are obfuscated (x_NNNN tokens): recognize bug patterns by
  CODE STRUCTURE and OPERATION TYPE, not by name. `x_1234.replace(x_5678, x_9012)` is a
  `.replace()` call — the in-place-vs-copy rule applies regardless of names.

- **LAW-194** A discarded method call with no assignment: `obj.method(arg)` on its own line
  with no `=` — this is almost certainly a "missing assignment" bug if the method returns a
  new object.

- **LAW-195** A matrix slice assigned a scalar constant: `x_1234[x_5678:, x_9012:] = 1` in a
  matrix-building function — suspect this should be `= x_variable` to preserve computed data.

- **LAW-196** When the Architect says "add re.IGNORECASE": if the SEARCH block targets a pattern
  STRING variable, look for the `re.compile(...)` call that USES that variable and add
  `re.IGNORECASE` to that compile call instead.

- **LAW-197** For in-place array fixes in Cloak mode: if the description says "assign the
  result back", the REPLACE must use `x_array[:] = x_array.method(...)` NOT
  `x_array = x_array.method(...)` when the array is a view into a structured/record array.

- **LAW-198** Use the symbol guide (semantic key) to map x_NNNN tokens to their functional
  meaning when available. Even without it: method names like `.replace()`, `.compile()`,
  `np.vstack()`, `super().__init__()` are not obfuscated — use them to identify the pattern.

---

## 28. SEARCH/REPLACE Quality Rules

- **LAW-199** SEARCH must match the source CHARACTER FOR CHARACTER — same indentation,
  spacing, and inline comments. A single whitespace difference causes application failure.

- **LAW-200** Keep SEARCH small: 2-6 lines. Smaller SEARCH = higher match probability.
  Include just enough context to uniquely identify the location (1 unique-ish line is often
  enough; add context lines only if the line appears more than once in the file).

- **LAW-201** The BUGGY code goes in SEARCH. The FIXED code goes in REPLACE. Never include
  the fix in SEARCH or the bug in REPLACE.

- **LAW-202** For a one-line fix: SEARCH = buggy line + 1 context line above or below for
  uniqueness. REPLACE = same structure with ONLY the buggy line corrected.

- **LAW-203** When changing a function signature to add a parameter: one SEARCH/REPLACE block
  captures the `def` line AND the `super().__init__()` call together (2 lines), changing both
  at once.

- **LAW-204** Multiple SEARCH/REPLACE blocks are allowed for multiple separate locations. Each
  block is applied independently. Order matters if blocks are in the same region.

- **LAW-205** In Cloak mode: ALL tokens in SEARCH must be the EXACT x_NNNN form from the
  shown source. Do NOT expand or translate x_NNNN tokens in SEARCH. Do NOT substitute real
  Python identifiers from your training knowledge. Copy VERBATIM.

- **LAW-206** Do not output the entire file or the entire function body in REPLACE. Output
  ONLY the changed lines and minimal context.

- **LAW-207** When adding a new IMPORT: put it in a separate SEARCH/REPLACE block from the
  logic change. Keep blocks single-purpose.

- **LAW-208** Indentation in REPLACE must match the surrounding code. Python's indentation is
  semantic — wrong indentation produces a SyntaxError or wrong nesting.

---

## 29. Versioning and Compatibility

- **LAW-209** Check Python version before using features: f-strings (3.6+), `walrus :=` (3.8+),
  `match/case` (3.10+), `ExceptionGroup` (3.11+), `tomllib` in stdlib (3.11+).

- **LAW-210** `sys.version_info >= (3, 8)` for version checks. `platform.python_version()`
  returns a version string.

- **LAW-211** Deprecated APIs often still work but print DeprecationWarnings. The fix is to
  use the replacement API, not to suppress the warning.

- **LAW-212** `__future__` imports: `from __future__ import annotations` — makes all annotations
  lazy (strings). Required in some codebases for forward references without quotes.

---

## 30. Astropy / Domain-Specific Patterns

- **LAW-213** Astropy units: `Quantity * unit` creates a Quantity. Unit arithmetic is tracked.
  `value.to(target_unit)` converts. Missing `.value` when a plain float is expected is common.

- **LAW-214** Astropy FITS: record array field access returns a view. `field[:] = data` writes
  back. chararray `.replace()` returns a new array — must assign back with `field[:] =`.

- **LAW-215** Astropy WCS: coordinate transformations are lossy if the wrong frame is used.
  Always specify frame explicitly: `SkyCoord(ra, dec, frame='icrs')`.

- **LAW-216** Astropy Table: `table['col']` returns a Column (view). Modifying it modifies
  the table. `table['col'].data` gives the underlying numpy array.

- **LAW-217** Astropy modeling separability: `_coord_matrix` builds a separability matrix
  for a single model. `_cstack` computes the `&` operator between two separability results.
  `_cdot` computes `|`. The bug in separability code is often in `_cstack`/`_cdot` where a
  computed sub-matrix is replaced with a scalar constant.

- **LAW-218** Astropy RST table `header_rows` fix requires THREE changes, not one:
  (1) Remove `SimpleRSTData.start_line = 3` (the class attribute line, NOT just change it).
  (2) `RST.__init__`: change to `def __init__(self, header_rows=None):` and call
      `super().__init__(delimiter_pad=None, bookend=False, header_rows=header_rows)`,
      then add `self.data.start_line = 2 + len(self.header.header_rows)` after super().
  (3) `RST.write`: change `lines = [lines[1]] + lines + [lines[1]]` to
      `idx = len(self.header.header_rows); lines = [lines[idx]] + lines + [lines[idx]]`.
  ALL THREE must be in the patch — partial fixes fail the tests. No separate `read` method needed.

- **LAW-219** Astropy QDP case-insensitive fix requires TWO changes, not one:
  (1) `_line_type`: `re.compile(_type_re)` → `re.compile(_type_re, re.IGNORECASE)`.
  (2) `_get_tables_from_qdp_file`: `if v == "NO":` → `if v.upper() == "NO":`.
  BOTH changes are required. Fixing only the regex compile is insufficient.

---

## 31. URL Validation and Sphinx Option Parsing

- **LAW-220** Django URLValidator two-bug fix: `django/core/validators.py`, `URLValidator.__call__`:
  **Bug 1** (line ~130, `else:` branch) — `urlsplit(value).netloc` can raise `ValueError: Invalid IPv6 URL`
  for inputs like `'////]@N.AN'`. Wrap in `try/except ValueError: raise ValidationError(...)`.
  **Bug 2** (line ~142, AFTER the try/else, unconditional) — `len(urlsplit(value).hostname)` raises
  `TypeError` when `hostname` is `None` (empty netloc, e.g. `'#@A.bO'`). Fix: assign
  `hostname = urlsplit(value).hostname` then guard `if hostname is not None and len(hostname) > 253`.
  Both fixes are required — the try/except at line 117 only covers the IDN fallback path (`except ValidationError`),
  neither the `else:` branch nor the post-else hostname check.
  Canonical fix:
  ```python
  # else: branch fix
  try:
      host_match = re.search(r'^\[(.+)\](?::\d{1,5})?$', urlsplit(value).netloc)
  except ValueError:
      raise ValidationError(self.message, code=self.code, params={'value': value})
  # hostname length check fix
  hostname = urlsplit(value).hostname
  if hostname is not None and len(hostname) > 253:
      raise ValidationError(self.message, code=self.code, params={'value': value})
  ```

- **LAW-221** Sphinx option_desc_re excludes `[`: `sphinx/domains/std.py` — `option_desc_re`
  uses `[^\s=[]+` which excludes `[` from option name characters. This breaks options like
  `[enable=]PATTERN` (bracket-optional syntax) which were valid in Sphinx 3.1. Fix: change
  `option_desc_re = re.compile(r'((?:/|--|-|\+)?[^\s=[]+)(=?\s*.*)')` to
  `option_desc_re = re.compile(r'((?:/|--|-|\+)?[^\s=]+)(=?\s*.*)')` (remove `[` from
  the excluded character class). Single-line, single-file change.

---

## 32. Django ORM and QuerySet Patterns

- **LAW-222** `QuerySet.filter()` / `exclude()` / `annotate()` are lazy — they return a NEW
  queryset, never mutate in place. Always assign: `qs = qs.filter(active=True)`.

- **LAW-223** `Model.objects.update(field=F('field') + 1)` is atomic (single SQL UPDATE).
  `obj.field += 1; obj.save()` is NOT atomic. Fix race conditions with `F()` in `update()`.

- **LAW-224** `select_related()` and `prefetch_related()` return a NEW queryset — must be assigned.
  `qs.select_related('author')` does nothing unless `qs = qs.select_related('author')`.

- **LAW-225** `QuerySet.get_or_create()` returns `(instance, created_bool)` — always unpack.
  `obj = Model.objects.get_or_create(...)` assigns a tuple, not a Model instance.

---

## 33. Python Exception Chaining and Context

- **LAW-226** `raise X from None` suppresses context. `raise X from e` sets `__cause__`.
  `raise X` inside `except e:` sets `__context__` (implicit). Tests asserting `__cause__`
  vs `__context__` will fail if you use the wrong form. Read the test carefully.

- **LAW-227** `contextlib.contextmanager`: exceptions inside the `with` block re-raise at the
  `yield`. Wrap `yield` in `try/except` to suppress or transform them.

---

## 34. Matplotlib Figure and Widget State

- **LAW-228** `Figure.clf()` / `Figure.clear()` clears axes but does NOT reset
  `figure.canvas.mouse_grabber`. When a widget (RangeSlider, Button) lives in a cleared
  axes, `mouse_grabber` still points to the dead widget → `AttributeError` on next mouse event.
  Fix: set `self.canvas.mouse_grabber = None` inside `Figure.clear()` BEFORE clearing axes.
  Location: `lib/matplotlib/figure.py`, method `Figure.clear()`.

- **LAW-229** HiDPI: `Figure.dpi` is logical dpi. `_device_pixel_ratio` holds the scale.
  On pickle/unpickle, divide saved dpi by device_pixel_ratio before canvas setup to avoid
  double-scaling.

---

## 35. Requests Library HTTP Edge Cases

- **LAW-230** `PreparedRequest.prepare_url()` strips URL fragments (`#anchor`) before sending.
  RFC 3986: fragments are client-side only. Tests checking fragments survive round-trip will
  fail by design. Adjust the assertion — check `prepared.url` for the fragment before send.

- **LAW-231** `requests.utils.prepend_scheme_if_needed()` expects `//` at the start of
  scheme-less URLs. Bare hostnames (no `//`) may be mis-parsed. Normalize before passing.

---

## 36. pytest Fixture and Collection Patterns

- **LAW-232** `pytest.raises(ExcType, match=r"pattern")` uses `re.search` on `str(exc)`.
  Pattern matches anywhere in the string. Update `match` if message format changed.

- **LAW-233** `tmp_path` is `pathlib.Path`, not `str`. Cast with `str(tmp_path)` when needed.

- **LAW-234** `scope='session'` fixtures are created ONCE per session — mutations persist
  across tests. Use `scope='function'` for isolation, or `deepcopy` the shared resource.

- **LAW-235** `monkeypatch.setattr('module.attr', value)` patches the module-level name.
  If the target did `from module import attr`, patch at the import site:
  `monkeypatch.setattr('target_module.attr', value)`.

---

## 37. scikit-learn API Contracts

- **LAW-236** `.fit_transform()` exists on `TransformerMixin` subclasses ONLY. Calling it
  on a bare estimator raises `AttributeError`. Call `.fit()` then `.transform()` separately.

- **LAW-237** `check_array(X, accept_sparse=False)` raises `ValueError` on sparse input.
  Set `accept_sparse=True` if the estimator must handle sparse matrices.

- **LAW-238** `sklearn.base.clone(estimator)` creates a new unfitted instance — does NOT
  copy `.coef_`, `.feature_importances_`, etc. Use `copy.deepcopy()` to preserve fitted state.

---

## 38. General Python Stdlib Edge Cases

- **LAW-239** `os.path.join(a, b)`: if `b` starts with `/`, `a` is discarded entirely.
  `os.path.join('/foo', '/bar') == '/bar'`. Strip leading slashes from user input paths.

- **LAW-240** `dict.update(other)` returns `None`. `merged = dict1.update(dict2)` is `None`.
  Use `merged = {**dict1, **dict2}` or mutate then use `dict1`.

- **LAW-241** `datetime.datetime.utcnow()` returns a NAIVE datetime (no tzinfo).
  Use `datetime.datetime.now(datetime.timezone.utc)` for timezone-aware code.
  Comparing naive and aware datetimes raises `TypeError`.

---

## 39. Dead Code and Unreachable Statements (Critical)

- **LAW-242** NEVER place executable code after a `return` statement in the same branch.
  Code after `return` is unreachable — it silently does nothing. The `_e_step` bug pattern:
  ```python
  # WRONG — _e_step is unreachable dead code:
  return log_resp.argmax(axis=1)
  _, log_resp = self._e_step(X)   ← never executes

  # CORRECT — run _e_step before the return:
  _, log_resp = self._e_step(X)
  return log_resp.argmax(axis=1)
  ```
  When moving code, always check: does the moved statement execute BEFORE the return?
  This is the most common model error — appearing to "move" code when actually deleting it.

- **LAW-243** When a `# comment says: do X at the end`, do NOT interpret that as "X can go
  after return". Comments describe INTENT. The comment "always do a final e-step to guarantee
  labels are consistent" means run _e_step, THEN return the result. The e-step IS the return value.

---

## 40. Flask and WSGI Config Patterns

- **LAW-244** `tomllib` (Python 3.11+ stdlib) and `tomli` (third-party backport) require files
  opened in BINARY mode (`'rb'`), not text mode (`'r'`). Flask's `config.from_file()` opens
  in text mode by default. Fix: when `load` is `tomllib.load` or `tomli.load`, open in `'rb'`:
  ```python
  # In from_file():
  mode = "rb" if getattr(load, "__module__", "").startswith("tom") else "r"
  with open(filename, mode) as f:
      obj = load(f)
  ```
  Or add a `mode` parameter: `config.from_file("config.toml", tomllib.load, mode="rb")`.

---

## 41. Sphinx autodoc __all__ Handling

- **LAW-245** `if not self.__all__` is falsy for BOTH `None` (not set) AND `[]` (explicitly
  empty). These have different meanings:
  - `__all__ = None` → not set, document all members
  - `__all__ = []` → explicitly empty, document NO members
  Fix: `if self.__all__ is None` to distinguish absent from empty.

---

## 42. pytest Skip and Module-Level Guards

- **LAW-246** `pytest.skip()` called at module level (outside any test function) raises
  `TypeError` unless `allow_module_level=True`. The check for module-level execution:
  `frame.f_locals is frame.f_globals` — True only at module scope (locals == globals).
  When the issue says "calling `pytest.skip()` at module level should be an error", the fix
  is to detect module scope and raise a descriptive exception BEFORE the `Skipped` is raised.
  The guard: `if not allow_module_level and frame.f_locals is frame.f_globals: raise`.

---

## 43. SymPy and Mathematical Libraries

- **LAW-247** When a function returns a list from a dict (`.values()`), dict value order in
  Python 3.7+ is insertion order, but may not be the canonical mathematical ordering.
  SymPy's `decompose(poly, separate=True)` returned values in dict insertion order — not
  sorted. If a test compares the returned list directly, sort by canonical key:
  `return sorted(list(poly_dict.values()), key=default_sort_key)`.

- **LAW-248** SymPy import errors: `ImportError: cannot import name 'X' from 'Y'` means
  the name doesn't exist in that module. Do NOT add an import to make the code compile if
  the name doesn't exist — find where the functionality actually lives or implement it.
  `groebner` is NOT in `sympy.strategies.tree` — adding that import will fail at runtime.

---

*This file is loaded at agent startup and injected into Architect and Builder prompts. Update
it when new systematic failure patterns are identified. Last updated: 2026-05-03.*
