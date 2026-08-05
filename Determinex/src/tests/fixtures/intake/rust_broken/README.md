# rust_broken — fixture for CODEBASE_EXPLORER_SMOKE_LOCK_001

Intentionally broken Rust fixture. `src/lib.rs::add` has a type mismatch
that `cargo check` rejects.

DO NOT FIX. Fixture for `tests/intake/test_codebase_explorer_smoke_lock.py`.
