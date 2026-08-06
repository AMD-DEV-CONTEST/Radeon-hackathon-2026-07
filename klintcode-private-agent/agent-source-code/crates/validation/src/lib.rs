//! L0–L6 validation pipeline.
//!
//! | Level | Gate | Failure handling |
//! |-------|------|------------------|
//! | L0 | HTTP, JSON, finish_reason | Transport failure, not model-repairable |
//! | L1 | File format parsing | Parse errors → repair diagnostic |
//! | L2 | Acceptance spec | Missing/extra objects → diagnostic |
//! | L3 | Domain validation (TeaQL) | Errors only → diagnostic |
//! | L4 | Code generation | Save generator logs |
//! | L5 | Build (cargo check) | Truncated compiler errors |
//! | L6 | Test (cargo test) | Failed assertions |

pub mod acceptance;
pub mod build;
pub mod domain;
pub mod parse;
pub mod transport;

pub use acceptance::*;
pub use build::*;
pub use domain::*;
pub use parse::*;
pub use transport::*;

use agent_core::event::ValidationResult;

/// Create a passing validation result
pub fn pass(level: u8, level_name: &str, elapsed_secs: f64) -> ValidationResult {
    ValidationResult {
        level,
        level_name: level_name.to_string(),
        passed: true,
        error_count: 0,
        warning_count: 0,
        suggestion_count: 0,
        actionable_errors: vec![],
        structured_errors: vec![],
        diagnostic: String::new(),
        elapsed_secs,
    }
}

/// Create a failing validation result
pub fn fail(
    level: u8,
    level_name: &str,
    errors: Vec<String>,
    diagnostic: String,
    elapsed_secs: f64,
) -> ValidationResult {
    ValidationResult {
        level,
        level_name: level_name.to_string(),
        passed: false,
        error_count: errors.len() as u32,
        warning_count: 0,
        suggestion_count: 0,
        actionable_errors: errors,
        structured_errors: vec![],
        diagnostic,
        elapsed_secs,
    }
}
