//! File system access control.
//! Canonicalizes paths, enforces manifests, rejects symlink escapes.

mod guard;
mod manifest;

pub use guard::*;
pub use manifest::*;
