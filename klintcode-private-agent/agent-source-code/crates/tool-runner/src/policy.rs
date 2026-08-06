use serde::{Deserialize, Serialize};

/// Defines the set of allowed command templates.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandPolicy {
    pub templates: Vec<AllowedCommand>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AllowedCommand {
    pub name: String,
    pub template: String,
    pub description: String,
}

impl Default for CommandPolicy {
    fn default() -> Self {
        Self {
            templates: vec![
                AllowedCommand {
                    name: "cargo-check".to_string(),
                    template: "cargo check --manifest-path {manifest}".to_string(),
                    description: "Run cargo check on approved manifest".to_string(),
                },
                AllowedCommand {
                    name: "cargo-test".to_string(),
                    template: "cargo test --manifest-path {manifest}".to_string(),
                    description: "Run cargo test on approved manifest".to_string(),
                },
                AllowedCommand {
                    name: "teaql-evaluate".to_string(),
                    template: "cargo teaql evaluate --input {candidate}".to_string(),
                    description: "TeaQL evaluate on candidate model".to_string(),
                },
            ],
        }
    }
}
