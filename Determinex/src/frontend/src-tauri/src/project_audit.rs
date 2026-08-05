use serde::{Deserialize, Serialize};
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use crate::win_process::HideConsoleExt;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuditCategory {
    pub title: String,
    pub score: u32,
    pub status: String, // "pass" | "warn" | "fail" | "skipped"
    pub details: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectAuditReport {
    pub score: u32,
    pub categories: Vec<AuditCategory>,
    pub blockers: Vec<String>,
    pub snyk_output: String,
}

/// Runs `cmd` to completion but never longer than `timeout` -- kills and reports a
/// timeout instead of hanging. Found live 2026-07-19: `npm audit --json` (a real
/// network call to the npm registry) has no bound here, so a slow/unreachable
/// registry left CommandCenter's "Release Readiness" score stuck on its loading
/// skeleton forever with no error, no timeout, nothing -- the home screen's
/// flagship metric silently never resolves. Reader threads drain stdout/stderr
/// concurrently so a chatty child (npm audit's JSON can be large) can't deadlock
/// on a full pipe buffer while we're only polling exit status.
pub(crate) fn run_with_timeout(mut cmd: Command, timeout: Duration) -> std::io::Result<std::process::Output> {
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    let mut child = cmd.spawn()?;

    let stdout_pipe = child.stdout.take();
    let stderr_pipe = child.stderr.take();
    let stdout_handle = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut p) = stdout_pipe {
            let _ = p.read_to_end(&mut buf);
        }
        buf
    });
    let stderr_handle = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut p) = stderr_pipe {
            let _ = p.read_to_end(&mut buf);
        }
        buf
    });

    let start = Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if start.elapsed() > timeout {
            let _ = child.kill();
            break child.wait()?;
        }
        std::thread::sleep(Duration::from_millis(100));
    };

    let stdout = stdout_handle.join().unwrap_or_default();
    let stderr = stderr_handle.join().unwrap_or_default();
    Ok(std::process::Output { status, stdout, stderr })
}

/// Was hardcoded to `current_dir("frontend/src-tauri")` / `current_dir("frontend")` -- this
/// audited DETERMINEX'S OWN repo, not whatever project a user of the shipped IDE has open.
/// Now takes the real workspace path and only runs a check when the relevant project file
/// (Cargo.toml / package.json) actually exists there -- an absent tool/ecosystem is reported
/// as "skipped", never silently scored as if it passed or failed.
#[tauri::command]
pub async fn run_project_audit(workspace_path: String) -> Result<ProjectAuditReport, String> {
    let root = Path::new(&workspace_path);
    let mut categories = Vec::new();
    let mut blockers = Vec::new();
    let mut total_score = 100;
    let mut any_ecosystem_checked = false;

    // 1. Rust compiler health -- checks root, root/src-tauri, AND root/frontend/src-tauri
    // (this exact repo's shape: Cargo.toml lives two levels down under frontend/src-tauri/,
    // which the original one-level-deep check never found -- Rust health silently never
    // ran here at all).
    let cargo_dir = if root.join("Cargo.toml").is_file() {
        Some(root.to_path_buf())
    } else if root.join("src-tauri").join("Cargo.toml").is_file() {
        Some(root.join("src-tauri"))
    } else if root.join("frontend").join("src-tauri").join("Cargo.toml").is_file() {
        Some(root.join("frontend").join("src-tauri"))
    } else {
        None
    };

    if let Some(dir) = cargo_dir {
        any_ecosystem_checked = true;
        let mut cmd = Command::new("cargo");
        cmd.hide_console();
        cmd.args(["check"]).current_dir(&dir);
        match run_with_timeout(cmd, Duration::from_secs(90)) {
            Ok(output) => {
                if output.status.success() {
                    categories.push(AuditCategory {
                        title: "Rust Compiler Health".to_string(),
                        score: 100,
                        status: "pass".to_string(),
                        details: "cargo check passed with 0 errors.".to_string(),
                    });
                } else {
                    categories.push(AuditCategory {
                        title: "Rust Compiler Health".to_string(),
                        score: 0,
                        status: "fail".to_string(),
                        details: "cargo check failed. See console for details.".to_string(),
                    });
                    total_score -= 30;
                    blockers.push("Rust compilation is failing.".to_string());
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {
                categories.push(AuditCategory {
                    title: "Rust Compiler Health".to_string(),
                    score: 100,
                    status: "warn".to_string(),
                    details: "cargo check did not finish within 90s -- skipped, not scored as a failure.".to_string(),
                });
            }
            Err(e) => {
                categories.push(AuditCategory {
                    title: "Rust Compiler Health".to_string(),
                    score: 0,
                    status: "warn".to_string(),
                    details: format!("Failed to execute cargo check: {}", e),
                });
                total_score -= 30;
            }
        }
    } else {
        categories.push(AuditCategory {
            title: "Rust Compiler Health".to_string(),
            score: 100,
            status: "skipped".to_string(),
            details: "No Cargo.toml found in this workspace -- not a Rust project.".to_string(),
        });
    }

    // 2. Node.js npm audit -- only if package.json actually exists here.
    let npm_dir = if root.join("package.json").is_file() {
        Some(root.to_path_buf())
    } else if root.join("frontend").join("package.json").is_file() {
        Some(root.join("frontend"))
    } else {
        None
    };

    let mut snyk_output = String::from("npm Audit Security Scan Report\n--------------------------------------\n");
    if let Some(dir) = npm_dir {
        any_ecosystem_checked = true;
        // On Windows npm is a .cmd shim, not a direct .exe -- Command::new("npm").hide_console()
        // fails to resolve it (CreateProcess looks for npm.exe verbatim) and
        // .spawn() returns Err, which surfaced live as "npm audit could not be
        // executed" on this exact repo. Route through the shell exactly like
        // terminal.rs's run_terminal_command already does for the same reason.
        let mut cmd = if cfg!(target_os = "windows") {
            let mut c = Command::new("cmd");
            c.hide_console();
            c.args(["/C", "npm audit --json"]);
            c
        } else {
            let mut c = Command::new("npm");
            c.hide_console();
            c.args(["audit", "--json"]);
            c
        };
        cmd.current_dir(&dir);
        // Real network call to the npm registry -- bounded so a slow/unreachable
        // registry can never again hang the whole audit indefinitely.
        match run_with_timeout(cmd, Duration::from_secs(20)) {
            Ok(output) => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Ok(json) = crate::python_json::parse_python_json::<serde_json::Value>(&stdout, "project audit") {
                    if let Some(metadata) = json.get("metadata").and_then(|m| m.get("vulnerabilities")) {
                        let high = metadata["high"].as_u64().unwrap_or(0);
                        let low = metadata["low"].as_u64().unwrap_or(0);

                        if high > 0 {
                            categories.push(AuditCategory {
                                title: "Dependency Security Scan".to_string(),
                                score: 50,
                                status: "fail".to_string(),
                                details: format!("Found {} high-severity vulnerabilities.", high),
                            });
                            total_score -= 20;
                            blockers.push(format!("Fix {} high severity vulnerabilities.", high));
                            snyk_output.push_str(&format!("- {} high severity vulnerabilities found.\n", high));
                        } else if low > 0 {
                            categories.push(AuditCategory {
                                title: "Dependency Security Scan".to_string(),
                                score: 85,
                                status: "warn".to_string(),
                                details: format!("Found {} low-severity vulnerabilities.", low),
                            });
                            total_score -= 5;
                            snyk_output.push_str("+ No high severity vulnerabilities found.\n");
                            snyk_output.push_str(&format!("- {} low severity vulnerabilities found.\n", low));
                        } else {
                            categories.push(AuditCategory {
                                title: "Dependency Security Scan".to_string(),
                                score: 100,
                                status: "pass".to_string(),
                                details: "0 vulnerabilities found in dependencies.".to_string(),
                            });
                            snyk_output.push_str("+ No vulnerabilities found.\n");
                        }
                    } else {
                        categories.push(AuditCategory {
                            title: "Dependency Security Scan".to_string(),
                            score: 90,
                            status: "warn".to_string(),
                            details: "Audit completed but JSON parsing failed.".to_string(),
                        });
                        snyk_output.push_str("? Could not parse audit json.\n");
                    }
                } else {
                    categories.push(AuditCategory {
                        title: "Dependency Security Scan".to_string(),
                        score: 90,
                        status: "warn".to_string(),
                        details: "Audit completed but JSON parsing failed.".to_string(),
                    });
                    snyk_output.push_str("? Could not parse audit json.\n");
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {
                categories.push(AuditCategory {
                    title: "Dependency Security Scan".to_string(),
                    score: 100,
                    status: "warn".to_string(),
                    details: "npm audit did not finish within 20s (registry unreachable/slow?) -- skipped, not scored as a failure.".to_string(),
                });
                snyk_output.push_str("? npm audit timed out after 20s.\n");
            }
            Err(_) => {
                categories.push(AuditCategory {
                    title: "Dependency Security Scan".to_string(),
                    score: 100,
                    status: "warn".to_string(),
                    details: "Failed to execute npm audit.".to_string(),
                });
                snyk_output.push_str("? npm audit could not be executed.\n");
            }
        }
    } else {
        categories.push(AuditCategory {
            title: "Dependency Security Scan".to_string(),
            score: 100,
            status: "skipped".to_string(),
            details: "No package.json found in this workspace -- not a Node project.".to_string(),
        });
        snyk_output.push_str("(skipped -- no package.json in this workspace)\n");
    }

    // 3. Credential leak scan -- scoped to the real workspace, not the process's ambient cwd.
    if root.is_dir() {
        // Excludes corpus/programbench (ProgramBench's own task corpus includes
        // reimpl fixtures and specs FOR a secret-detection tool -- ripsecrets --
        // whose sample "leaked" secrets aren't real) and tests/ (fixtures that
        // exist specifically to verify fake-secret rejection). Without these,
        // this naive regex flagged "FAIL: Found potential hardcoded secrets!" on
        // Determinex's own repo while the project's real secret_scan.py reports
        // clean -- a false alarm found live 2026-07-19 on this exact audit run.
        let mut cmd = Command::new("git");
        cmd.hide_console();
        cmd.args([
            "grep",
            "-i",
            "-E",
            "(api_key|secret|password)\\s*=\\s*[\"'][a-zA-Z0-9_-]{16,}[\"']",
            "--",
            ".",
            ":(exclude)corpus/programbench",
            ":(exclude)tests",
        ])
        .current_dir(root);

        match run_with_timeout(cmd, Duration::from_secs(15)) {
            Ok(output) => {
                if output.stdout.is_empty() {
                    categories.push(AuditCategory {
                        title: "Credential Leak Detection".to_string(),
                        score: 100,
                        status: "pass".to_string(),
                        details: "No hardcoded secrets detected in tracked files.".to_string(),
                    });
                } else {
                    categories.push(AuditCategory {
                        title: "Credential Leak Detection".to_string(),
                        score: 0,
                        status: "fail".to_string(),
                        details: "Found potential hardcoded secrets!".to_string(),
                    });
                    total_score -= 50;
                    blockers.push("Remove hardcoded secrets from codebase.".to_string());
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {
                categories.push(AuditCategory {
                    title: "Credential Leak Detection".to_string(),
                    score: 100,
                    status: "warn".to_string(),
                    details: "git grep did not finish within 15s -- skipped, not scored as a failure.".to_string(),
                });
            }
            Err(_) => {
                categories.push(AuditCategory {
                    title: "Credential Leak Detection".to_string(),
                    score: 100,
                    status: "warn".to_string(),
                    details: "Could not run git grep for leaks (not a git repo, or git unavailable).".to_string(),
                });
            }
        }
    } else {
        categories.push(AuditCategory {
            title: "Credential Leak Detection".to_string(),
            score: 100,
            status: "skipped".to_string(),
            details: "No workspace open.".to_string(),
        });
    }

    if !any_ecosystem_checked {
        blockers.push(
            "No recognized project type (Rust/Cargo.toml or Node/package.json) found in this \
             workspace -- audit coverage is currently limited to those two ecosystems."
                .to_string(),
        );
    }

    Ok(ProjectAuditReport {
        score: total_score.max(0) as u32,
        categories,
        blockers,
        snyk_output,
    })
}
