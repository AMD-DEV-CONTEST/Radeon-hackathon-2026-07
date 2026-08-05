/// compiler.rs — Zero-VRAM compiler feedback for the Observer stage.
///
/// Runs the language-appropriate compiler against the Engineer's generated code
/// inside an isolated temp project. The output is injected verbatim into the
/// Observer's prompt so the AI reads exact line numbers and error messages
/// instead of visually guessing whether syntax is valid.
///
/// Supported compilers:
///   Rust       — `cargo check --message-format=short`
///   TypeScript — `npx tsc --noEmit --strict`
///
/// Both compile in a throwaway temp directory that is deleted on return.
/// Zero interference with the real workspace.
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use crate::win_process::HideConsoleExt;

/// Maximum characters of compiler output forwarded to the Observer.
/// Caps to avoid overflowing the 2048-token context budget.
const MAX_OUTPUT_CHARS: usize = 1400;

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC TYPES
// ─────────────────────────────────────────────────────────────────────────────

/// Structured compiler output, ready for injection into the Observer prompt.
#[derive(Debug)]
pub struct CompilerFeedback {
    /// Human-readable tool label: "cargo check" or "tsc --noEmit".
    pub tool: String,
    /// True if the compiler exited successfully (no errors).
    pub success: bool,
    /// Captured stdout + stderr, trimmed and truncated to MAX_OUTPUT_CHARS.
    pub output: String,
    /// True if the output was cut short.
    pub truncated: bool,
    /// Dependency names that appear in unresolved import/module errors.
    /// Rust entries are crate names for Cargo.toml; TypeScript entries are npm
    /// packages or @types packages for package.json.
    pub missing_deps: Vec<String>,
}

impl CompilerFeedback {
    /// Render as a compact block suitable for LLM prompt injection.
    pub fn to_prompt_block(&self) -> String {
        let status = if self.success {
            "PASS — no errors detected"
        } else {
            "FAIL — errors below"
        };
        let tail = if self.truncated {
            "\n[...output truncated]"
        } else {
            ""
        };

        let body = if self.output.is_empty() {
            format!("COMPILER ({}) → {}", self.tool, status)
        } else {
            format!(
                "COMPILER ({}) → {}:\n{}{}",
                self.tool, status, self.output, tail
            )
        };

        // Inject a hard-to-miss advisory when missing dependencies are detected.
        // The Observer must pass this through to the Engineer because source-only
        // rewrites cannot resolve a missing package manifest entry.
        if !self.missing_deps.is_empty() {
            if self.tool.contains("tsc") {
                format!(
                    "{}\n\n⚠ DEPENDENCY ALERT: The following npm packages/types are missing from package.json: [{}]\n\
                     The Engineer MUST add/install these packages — rewriting source code alone cannot fix this error.",
                    body,
                    self.missing_deps.join(", ")
                )
            } else {
                format!(
                    "{}\n\n⚠ DEPENDENCY ALERT: The following crates are missing from Cargo.toml: [{}]\n\
                     The Engineer MUST add these to [dependencies] in Cargo.toml — rewriting source code alone cannot fix this error.",
                    body,
                    self.missing_deps.join(", ")
                )
            }
        } else {
            body
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Run the appropriate compiler for `language` against `code`.
///
/// `filename` is used only to name the source file inside the temp project
/// (e.g. `"main.rs"`, `"auth.ts"`). Returns `None` if no suitable compiler
/// is available for the language or if the subprocess could not be spawned.
pub fn check(language: &str, filename: &str, code: &str) -> Option<CompilerFeedback> {
    match language.to_lowercase().as_str() {
        "rust" => check_rust(filename, code),
        "typescript" | "tsx" => check_typescript(filename, code),
        _ => None,
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// RUST
// ─────────────────────────────────────────────────────────────────────────────

fn check_rust(filename: &str, code: &str) -> Option<CompilerFeedback> {
    let dir = make_temp_dir("determinex_rust")?;
    let result = run_rust_check(&dir, filename, code);
    let _ = fs::remove_dir_all(&dir);

    match result {
        Ok(fb) => {
            log::info!(
                "[COMPILER] cargo check: {} — {} bytes",
                if fb.success { "PASS" } else { "FAIL" },
                fb.output.len()
            );
            Some(fb)
        }
        Err(e) => {
            log::warn!("[COMPILER] cargo check could not run: {}", e);
            None
        }
    }
}

fn run_rust_check(dir: &Path, filename: &str, code: &str) -> std::io::Result<CompilerFeedback> {
    let src_dir = dir.join("src");
    fs::create_dir_all(&src_dir)?;

    // Normalise the source filename to end in .rs
    let rs_name = if filename.ends_with(".rs") {
        filename.to_string()
    } else {
        "main.rs".to_string()
    };

    fs::write(src_dir.join(&rs_name), code)?;

    // If the user's file isn't main.rs, add a minimal main.rs shim so the
    // crate entry point is satisfied.
    if rs_name != "main.rs" {
        let mod_name = rs_name.trim_end_matches(".rs");
        fs::write(
            src_dir.join("main.rs"),
            format!("mod {};\nfn main() {{}}\n", mod_name),
        )?;
    }

    fs::write(
        dir.join("Cargo.toml"),
        "[package]\nname = \"determinex_check\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
    )?;

    let out = Command::new("cargo").hide_console()
        .args(["check", "--message-format=short", "--color=never"])
        .current_dir(dir)
        .env("CARGO_TERM_COLOR", "never")
        .output()?;

    let combined = merge_output(&out.stdout, &out.stderr);
    let missing_deps = extract_missing_deps(&combined);
    let (output, truncated) = truncate(combined);

    Ok(CompilerFeedback {
        tool: "cargo check".to_string(),
        success: out.status.success(),
        output,
        truncated,
        missing_deps,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// TYPESCRIPT
// ─────────────────────────────────────────────────────────────────────────────

fn check_typescript(filename: &str, code: &str) -> Option<CompilerFeedback> {
    let dir = make_temp_dir("determinex_ts")?;
    let result = run_tsc_check(&dir, filename, code);
    let _ = fs::remove_dir_all(&dir);

    match result {
        Ok(fb) => {
            log::info!(
                "[COMPILER] tsc: {} — {} bytes",
                if fb.success { "PASS" } else { "FAIL" },
                fb.output.len()
            );
            Some(fb)
        }
        Err(e) => {
            log::warn!("[COMPILER] tsc could not run: {}", e);
            None
        }
    }
}

fn run_tsc_check(dir: &Path, filename: &str, code: &str) -> std::io::Result<CompilerFeedback> {
    let ts_name = if filename.ends_with(".ts") || filename.ends_with(".tsx") {
        filename.to_string()
    } else {
        "output.ts".to_string()
    };
    fs::write(dir.join(&ts_name), code)?;

    // Standalone single-file tsc check — no tsconfig required for syntax validation.
    // Inject npm global bin into PATH so npx/tsc resolves regardless of spawn environment
    let appdata = std::env::var("APPDATA").unwrap_or_default();
    let npm_bin = format!("{}\\npm", appdata);
    let current_path = std::env::var("PATH").unwrap_or_default();
    let patched_path = format!("{};{}", npm_bin, current_path);

    let out = Command::new("npx").hide_console()
        .args([
            "--yes",
            "tsc",
            "--noEmit",
            "--strict",
            "--target",
            "esnext",
            "--module",
            "esnext",
            "--moduleResolution",
            "node",
            &ts_name,
        ])
        .env("PATH", &patched_path)
        .current_dir(dir)
        .output()?;

    let combined = merge_output(&out.stdout, &out.stderr);
    let missing_deps = extract_missing_deps(&combined);
    let (output, truncated) = truncate(combined);

    Ok(CompilerFeedback {
        tool: "tsc --noEmit".to_string(),
        success: out.status.success(),
        output,
        truncated,
        missing_deps,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

fn make_temp_dir(prefix: &str) -> Option<PathBuf> {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let dir = std::env::temp_dir().join(format!("{}_{}", prefix, ts));
    fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

/// Scan raw compiler output for missing dependency errors and extract package names.
///
/// Rust's relevant error codes / patterns:
///   error[E0433]: failed to resolve: use of undeclared crate or module `name`
///   error[E0432]: unresolved import `name`
///   can't find crate for `name`
///
/// TypeScript's relevant patterns:
///   error TS2307: Cannot find module 'name' or its corresponding type declarations.
///   error TS2688: Cannot find type definition file for 'name'.
///
/// Returns deduplicated names so the Observer can tell the Engineer to update the
/// manifest rather than spinning in an infinite source-rewrite loop.
fn extract_missing_deps(output: &str) -> Vec<String> {
    use std::collections::BTreeSet;
    let mut found: BTreeSet<String> = BTreeSet::new();

    for line in output.lines() {
        // "error[E0433]: failed to resolve: use of undeclared crate or module `foo`"
        // "error[E0432]: unresolved import `foo`"
        if line.contains("E0433") || line.contains("E0432") || line.contains("can't find crate for")
        {
            // Extract the name inside the first pair of backticks on the line.
            if let Some(start) = line.find('`') {
                let after = &line[start + 1..];
                if let Some(end) = after.find('`') {
                    let name = after[..end]
                        .split("::")
                        .next()
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    if !name.is_empty() {
                        found.insert(name);
                    }
                }
            }
        }

        if let Some(module) = quoted_after(line, "Cannot find module '") {
            if let Some(pkg) = npm_package_from_module_specifier(module) {
                found.insert(pkg);
            }
        }

        if let Some(type_name) = quoted_after(line, "Cannot find type definition file for '") {
            if let Some(pkg) = npm_type_package(type_name) {
                found.insert(pkg);
            }
        }
    }

    found.into_iter().collect()
}

fn quoted_after<'a>(line: &'a str, marker: &str) -> Option<&'a str> {
    let start = line.find(marker)? + marker.len();
    let rest = &line[start..];
    let end = rest.find('\'')?;
    Some(&rest[..end])
}

fn npm_package_from_module_specifier(specifier: &str) -> Option<String> {
    let specifier = specifier.trim();
    if specifier.is_empty()
        || specifier.starts_with('.')
        || specifier.starts_with('/')
        || specifier.contains("://")
    {
        return None;
    }

    let without_node_prefix = specifier.strip_prefix("node:").unwrap_or(specifier);
    if is_node_builtin(without_node_prefix) {
        return Some("@types/node".to_string());
    }

    if specifier.starts_with('@') {
        let mut parts = specifier.split('/');
        let scope = parts.next()?;
        let package = parts.next()?;
        if package.is_empty() {
            return None;
        }
        return Some(format!("{}/{}", scope, package));
    }

    specifier
        .split('/')
        .next()
        .filter(|name| !name.is_empty())
        .map(|name| name.to_string())
}

fn npm_type_package(type_name: &str) -> Option<String> {
    let type_name = type_name.trim();
    if type_name.is_empty() {
        return None;
    }
    if type_name.starts_with("@types/") {
        return Some(type_name.to_string());
    }
    if is_node_builtin(type_name) || type_name == "node" {
        return Some("@types/node".to_string());
    }
    Some(format!("@types/{}", type_name))
}

fn is_node_builtin(name: &str) -> bool {
    matches!(
        name,
        "assert"
            | "buffer"
            | "child_process"
            | "crypto"
            | "dns"
            | "events"
            | "fs"
            | "http"
            | "https"
            | "net"
            | "os"
            | "path"
            | "process"
            | "stream"
            | "timers"
            | "tls"
            | "tty"
            | "url"
            | "util"
            | "zlib"
    )
}

fn merge_output(stdout: &[u8], stderr: &[u8]) -> String {
    let s = String::from_utf8_lossy(stdout);
    let e = String::from_utf8_lossy(stderr);
    format!("{}\n{}", s, e).trim().to_string()
}

fn truncate(s: String) -> (String, bool) {
    if s.len() <= MAX_OUTPUT_CHARS {
        (s, false)
    } else {
        // Tail-bias: the fatal error is always at the END of a compiler trace.
        // Keeping the preamble (warnings) and cutting the error is worse than useless.
        let tail = &s[s.len() - MAX_OUTPUT_CHARS..];
        (
            format!(
                "[...{} chars omitted...]\n{}",
                s.len() - MAX_OUTPUT_CHARS,
                tail
            ),
            true,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_rust_missing_crates() {
        let output = "\
error[E0432]: unresolved import `serde`
error[E0433]: failed to resolve: use of undeclared crate or module `tokio::sync`
error: can't find crate for `anyhow`";

        assert_eq!(
            extract_missing_deps(output),
            vec![
                "anyhow".to_string(),
                "serde".to_string(),
                "tokio".to_string()
            ]
        );
    }

    #[test]
    fn extracts_typescript_missing_npm_packages() {
        let output = "\
main.ts(1,24): error TS2307: Cannot find module 'lodash/fp' or its corresponding type declarations.
main.ts(2,22): error TS2307: Cannot find module '@vitejs/plugin-react' or its corresponding type declarations.
main.ts(3,16): error TS2307: Cannot find module './local-file' or its corresponding type declarations.
error TS2688: Cannot find type definition file for 'node'.";

        assert_eq!(
            extract_missing_deps(output),
            vec![
                "@types/node".to_string(),
                "@vitejs/plugin-react".to_string(),
                "lodash".to_string()
            ]
        );
    }

    #[test]
    fn typescript_prompt_alert_points_to_package_json() {
        let feedback = CompilerFeedback {
            tool: "tsc --noEmit".to_string(),
            success: false,
            output: "Cannot find module 'react'".to_string(),
            truncated: false,
            missing_deps: vec!["react".to_string()],
        };

        let block = feedback.to_prompt_block();
        assert!(block.contains("package.json"));
        assert!(block.contains("react"));
        assert!(!block.contains("Cargo.toml"));
    }
}
