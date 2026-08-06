//! Task package loading, prompt construction and token admission control.
//!
//! A task package is an explicit directory containing all inputs for one task:
//! - task.md — business goal and scope
//! - grammar-example.xml — minimal legal example
//! - value-whitelist.txt — allowed value forms
//! - acceptance.json — machine-checkable completion conditions
//! - workspace-manifest.toml — readable/writable file lists
//! - tool-policy.toml — command whitelist

mod budget;
mod prompt;
mod task_package;
pub mod includes;

pub use budget::*;
pub use prompt::*;
pub use task_package::*;
pub use includes::*;
