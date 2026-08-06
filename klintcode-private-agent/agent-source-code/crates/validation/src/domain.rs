//! L3: Domain validation — TeaQL evaluate or other domain validators

use agent_core::event::ValidationResult;
use std::path::Path;
use std::process::Command;

/// Run cargo teaql evaluate on the given input file or directory
pub fn validate_domain(input_path: &Path) -> ValidationResult {
    let start = std::time::Instant::now();

    let output = Command::new("cargo")
        .arg("teaql")
        .arg("--input")
        .arg(input_path)
        .arg("evaluate")
        .output();

    let elapsed = start.elapsed().as_secs_f64();

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            let combined = format!("{}\n{}", stdout, stderr);
            let mut result = parse_teaql_output(&combined);
            result.elapsed_secs = elapsed;

            // If the command failed but we didn't parse any errors, add a generic error
            if !out.status.success() && result.error_count == 0 {
                result.error_count = 1;
                result.passed = false;
                result.actionable_errors.push(format!(
                    "Command failed with exit code: {:?}",
                    out.status.code()
                ));
            }
            result
        }
        Err(e) => super::fail(3, "domain", vec![e.to_string()], e.to_string(), elapsed),
    }
}

/// Parse TeaQL evaluate output to extract error/warning/suggestion counts.
pub fn parse_teaql_output(output: &str) -> ValidationResult {
    let mut errors = Vec::new();
    let mut error_count: u32 = 0;
    let mut warning_count: u32 = 0;
    let mut suggestion_count: u32 = 0;
    let mut in_error_table = false;

    for line in output.lines() {
        let line = line.trim();

        // Parse summary counts from "- **Errors**: 3" format
        if line.starts_with("- **Errors**:") {
            if let Some(count) = extract_count(line) {
                error_count = count;
            }
        }
        if line.starts_with("- **Warnings**:") {
            if let Some(count) = extract_count(line) {
                warning_count = count;
            }
        }
        if line.starts_with("- **Suggestions**:") {
            if let Some(count) = extract_count(line) {
                suggestion_count = count;
            }
        }

        // Detect error table section
        if line.contains("## ❌ Errors") || line.contains("## Errors") {
            in_error_table = true;
            errors.push(line.to_string());
            continue;
        }
        // End of error table on next section
        if in_error_table && line.starts_with("## ") {
            in_error_table = false;
        }
        // Collect error table rows (start with |, skip header/separator)
        if in_error_table && line.starts_with("| `") {
            errors.push(line.to_string());
        }
    }

    ValidationResult {
        level: 3,
        level_name: "domain".to_string(),
        passed: error_count == 0,
        error_count,
        warning_count,
        suggestion_count,
        actionable_errors: errors,
        structured_errors: vec![],
        diagnostic: output.to_string(),
        elapsed_secs: 0.0,
    }
}

/// Try to extract a numeric count from a line like "5 errors"
fn extract_count(line: &str) -> Option<u32> {
    for word in line.split_whitespace() {
        if let Ok(n) = word.parse::<u32>() {
            return Some(n);
        }
    }
    None
}
