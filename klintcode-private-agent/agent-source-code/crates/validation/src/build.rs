//! L5-L6: Build and test validation

use agent_core::event::ValidationResult;

/// Parse cargo check output to create a validation result.
pub fn parse_cargo_check_output(
    exit_code: i32,
    stderr: &str,
    elapsed_secs: f64,
) -> ValidationResult {
    if exit_code == 0 {
        let warning_count = stderr.matches("warning").count() as u32;
        let mut result = super::pass(5, "build", elapsed_secs);
        result.warning_count = warning_count;
        result
    } else {
        let errors: Vec<String> = stderr
            .lines()
            .filter(|l| l.contains("error[") || l.starts_with("error"))
            .map(|l| l.to_string())
            .collect();

        let diagnostic = if stderr.len() > 12000 {
            stderr[..12000].to_string()
        } else {
            stderr.to_string()
        };

        super::fail(5, "build", errors, diagnostic, elapsed_secs)
    }
}

/// Parse cargo test output to create a validation result.
pub fn parse_cargo_test_output(
    exit_code: i32,
    stdout: &str,
    stderr: &str,
    elapsed_secs: f64,
) -> ValidationResult {
    if exit_code == 0 {
        super::pass(6, "test", elapsed_secs)
    } else {
        let mut errors: Vec<String> = Vec::new();
        for line in stdout.lines().chain(stderr.lines()) {
            if line.contains("FAILED") || line.contains("panicked") || line.contains("assertion") {
                errors.push(line.to_string());
            }
        }

        let combined = format!("{stdout}\n{stderr}");
        let diagnostic = if combined.len() > 12000 {
            combined[..12000].to_string()
        } else {
            combined
        };

        super::fail(6, "test", errors, diagnostic, elapsed_secs)
    }
}
