# python_broken — fixture for CODEBASE_EXPLORER_SMOKE_LOCK_001

Intentionally broken Python fixture. `add()` returns the wrong value and the
pytest test asserts the correct value, so `pytest -x` exits non-zero.

DO NOT FIX. This is a fixture for `tests/intake/test_codebase_explorer_smoke_lock.py`.
