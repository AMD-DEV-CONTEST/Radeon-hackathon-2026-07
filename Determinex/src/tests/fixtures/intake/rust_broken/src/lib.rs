// Intentionally broken — fixture for CODEBASE_EXPLORER_SMOKE_LOCK_001.

pub fn add(a: i32, b: i32) -> i32 {
    // BUG: returning a String literal from a fn declared to return i32.
    // `cargo check` will reject with E0308 mismatched types.
    "not an integer"
}

pub fn multiply(a: i32, b: i32) -> i32 {
    a * b
}
