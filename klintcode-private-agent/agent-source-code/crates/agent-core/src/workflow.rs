use serde::{Deserialize, Serialize};

/// Workflow describes which validation gates are enabled for a task type.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Workflow {
    pub name: String,
    pub description: String,
    /// Enable L1: file format parsing
    pub parse_validation: bool,
    /// Enable L2: acceptance spec checking
    pub acceptance_validation: bool,
    /// Enable L3: domain validation (e.g. TeaQL evaluate)
    pub domain_validation: bool,
    /// Domain validator command template
    pub domain_validator: Option<String>,
    /// Enable L4: code generation
    pub codegen: bool,
    /// Enable L5: build (cargo check)
    pub build_validation: bool,
    /// Build command template
    pub build_command: Option<String>,
    /// Enable L6: test (cargo test)
    pub test_validation: bool,
    /// Test command template
    pub test_command: Option<String>,
    /// Max repairs for this workflow (overrides profile if set)
    pub max_repairs: Option<u8>,
}

impl Default for Workflow {
    fn default() -> Self {
        Self {
            name: "default".to_string(),
            description: "Default workflow with all gates enabled".to_string(),
            parse_validation: true,
            acceptance_validation: true,
            domain_validation: true,
            domain_validator: None,
            codegen: false,
            build_validation: false,
            build_command: None,
            test_validation: false,
            test_command: None,
            max_repairs: None,
        }
    }
}

impl Workflow {
    /// KSML modeling workflow — used for first-phase evaluation
    pub fn ksml_modeling() -> Self {
        Self {
            name: "ksml-modeling".to_string(),
            description: "KSML XML model generation with TeaQL evaluation".to_string(),
            parse_validation: true,
            acceptance_validation: true,
            domain_validation: true,
            domain_validator: Some("cargo teaql evaluate --input {candidate}".to_string()),
            codegen: false,
            build_validation: false,
            build_command: None,
            test_validation: false,
            test_command: None,
            max_repairs: Some(8),
        }
    }

    /// Code generation workflow with full build and test
    pub fn code_generation() -> Self {
        Self {
            name: "code-generation".to_string(),
            description: "Code generation with compilation and testing".to_string(),
            parse_validation: true,
            acceptance_validation: false,
            domain_validation: false,
            domain_validator: None,
            codegen: true,
            build_validation: true,
            build_command: Some("cargo check --manifest-path {manifest}".to_string()),
            test_validation: true,
            test_command: Some("cargo test --manifest-path {manifest}".to_string()),
            max_repairs: Some(8),
        }
    }
}
